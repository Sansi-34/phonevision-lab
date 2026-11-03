"""
PhoneVision Lab Web — 设备会话（连接状态机 + 视觉模式 + 截图/采集帧源）。

职责：把"连手机、收流、算指标、按模式处理一帧"集中在服务端一个对象里，
所有 /api/device/* 与 /api/vision/* 请求都走它。

为什么这样设计：
  - 复用 pc-client 现有模块，不复制逻辑：connection.build_urls/ping_device 负责
    URL 与预检，mjpeg_reader.MjpegReader 负责严格 MJPEG 解析，
    app_model.AppModel 负责 /ping 轮询、接收/显示帧率与丢帧统计，
    vision_modes.apply_mode 负责五种视觉模式。web 层只做"驱动 + 序列化"。
  - 浏览器无法直接消费手机的 multipart MJPEG 流（<img> 只认单张 JPEG，
    且手机无 CORS 头），因此本服务提供 /api/vision/frame.jpg 单帧接口：
    由 AppModel 取最新帧 → OpenCV 按当前模式处理 → JPEG 编码返回。
    这样网页拿到的是真实帧，且不会把解析逻辑抄第二遍。
  - 连接状态机沿用 AppModel 的状态常量（Connecting/Streaming/Reconnecting/
    Stopped/Error），前端只做展示，不自行推断。
  - 采集/截图复用"最新帧 + 帧号"语义：dataset_panel 用 frame_provider 拿帧，
    web 端用同一个 get_latest_frame，保证两处客户端行为一致。
"""
from __future__ import annotations

import os
import sys
import threading
import time

import cv2
import numpy as np

# 复用 pc-client：把它的目录加进 sys.path（本服务是它的新客户端，不是替代品）。
_PC_CLIENT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

import app_model  # noqa: E402
import connection  # noqa: E402
import vision_modes  # noqa: E402

from .util import (  # noqa: E402
    ApiError, ERR_NOT_CONNECTED, ERR_NO_FRAME, safe_int, validate_private_host,
)

# 视觉模式元数据（顺序 = 界面按钮顺序）。name/params 与 pc-client 一致。
VISION_MODES = [
    {"id": vision_modes.MODE_ORIGINAL, "label": "原始",
     "label_en": "Original", "params": []},
    {"id": vision_modes.MODE_GRAY, "label": "灰度",
     "label_en": "Gray", "params": []},
    {"id": vision_modes.MODE_CANNY, "label": "Canny 边缘",
     "label_en": "Canny", "params": ["canny_low", "canny_high"]},
    {"id": vision_modes.MODE_HSV, "label": "HSV 颜色",
     "label_en": "HSV", "params": ["h_min", "h_max", "s_min", "s_max",
                                   "v_min", "v_max"]},
    {"id": vision_modes.MODE_CONTOUR, "label": "轮廓",
     "label_en": "Contours",
     "params": ["h_min", "h_max", "s_min", "s_max", "v_min", "v_max",
                "contour_min_area"]},
]

# 参数的中文说明（界面上显示在滑块旁；英文留待 i18n 扩展）。
PARAM_LABELS = {
    "canny_low": "Canny 低阈值",
    "canny_high": "Canny 高阈值",
    "h_min": "H 最小值",
    "h_max": "H 最大值",
    "s_min": "S 最小值",
    "s_max": "S 最大值",
    "v_min": "V 最小值",
    "v_max": "V 最大值",
    "contour_min_area": "最小轮廓面积",
}

# 参数范围（与 vision_modes.DEFAULT_PARAMS 的语义对应）。
PARAM_RANGES = {
    "canny_low": (0, 255),
    "canny_high": (0, 255),
    "h_min": (0, 179),
    "h_max": (0, 179),
    "s_min": (0, 255),
    "s_max": (0, 255),
    "v_min": (0, 255),
    "v_max": (0, 255),
    "contour_min_area": (0, 20000),
}

# 每个模式对应的教学说明（第三课"认识灰度、边缘检测和颜色空间"直接引用）。
MODE_HINTS = {
    vision_modes.MODE_ORIGINAL: (
        "原始画面：手机摄像头直接送出的 BGR 图像，没有做任何处理。"
        "这是所有后续处理的输入。"),
    vision_modes.MODE_GRAY: (
        "灰度：把 BGR 三通道按亮度权重合成一个通道。"
        "计算机视觉里大多数算法都先在灰度图上跑，因为计算量只有三分之一。"),
    vision_modes.MODE_CANNY: (
        "Canny 边缘检测：先高斯模糊去噪点，再找亮度梯度大的地方。"
        "低阈值决定“多弱的边缘也算”，高阈值决定“多强的边缘才保留”；"
        "两个阈值越接近，边缘越干净但越容易断。"),
    vision_modes.MODE_HSV: (
        "HSV：H 是色相（0-179 覆盖红橙黄绿青蓝紫），S 是饱和度，V 是明度。"
        "白色像素 = 落在你设定范围内的颜色，黑色 = 被过滤掉。"),
    vision_modes.MODE_CONTOUR: (
        "轮廓：先用 HSV 范围得到掩膜，再找连通区域的边界，"
        "绿色是轮廓、蓝色是外接矩形、红点是中心坐标。"
        "调大“最小轮廓面积”可以滤掉小噪点。"),
}


class DeviceSession:
    """单例：当前连接的手机会话与视觉实验状态。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._model: app_model.AppModel | None = None
        self._stream_url = ""
        self._ping_url = ""
        self._host = ""
        self._port = 0
        self._ping_info: dict = {}
        self._mode = vision_modes.MODE_ORIGINAL
        self._params = dict(vision_modes.DEFAULT_PARAMS)
        self._connected_at = 0.0
        self._last_error = ""

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    def connect(self, host: str, port: int = 8080) -> dict:
        """连接手机：先 /ping 预检，通过后启动 reader 与 ping worker。

        host 只允许局域网私网 IP（服务端会真的向它发 HTTP 请求，不能让
        请求体指定任意目标，否则就变成 SSRF）。
        """
        host = validate_private_host(host, "手机 IP 地址")
        port = safe_int(port, 8080, minimum=1, maximum=65535)

        stream_url, ping_url = connection.build_urls(host=host, port=port)
        result = connection.ping_device(ping_url)
        if not result.success:
            # 明确失败原因，不进入"半连接"状态。
            self._last_error = result.error or "连接失败"
            raise ApiError("device_error", result.error or "连接失败")

        with self._lock:
            self.disconnect()
            self._host, self._port = host, int(port)
            self._stream_url, self._ping_url = stream_url, ping_url
            self._ping_info = dict(result.info or {})
            self._model = app_model.AppModel(
                stream_url=stream_url,
                ping_url=ping_url,
                device_name=str(result.info.get("device", "")),
                width=int(result.info.get("width") or 0),
                height=int(result.info.get("height") or 0),
                phone_fps=float(result.info.get("actualFps") or 0),
            )
            self._model.start()
            self._connected_at = time.time()
            self._last_error = ""
        return self.status()

    def disconnect(self) -> None:
        with self._lock:
            model = self._model
            self._model = None
        if model is not None:
            try:
                model.stop()
            except Exception:  # noqa: BLE001 - 停止失败不影响后续连接
                pass

    @property
    def is_connected(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """给前端的连接状态快照（字段与 /ping 口径保持一致，不自造指标）。"""
        model = self._model
        if model is None:
            return {
                "connected": False,
                "state": "disconnected",
                "state_label": "未连接",
                "host": "",
                "port": 0,
                "device": "",
                "width": 0,
                "height": 0,
                "phone_fps": None,
                "receive_fps": None,
                "display_fps": None,
                "dropped_frames": None,
                "received_frames": 0,
                "invalid_frames": 0,
                "frame_stale": True,
                "frame_age_seconds": 0.0,
                "bandwidth_mbps": None,
                "average_jpeg_bytes": None,
                "last_error": self._last_error,
                "last_ping_at": None,
            }

        snap = model.snapshot()
        state = snap.connection_state
        return {
            "connected": True,
            "state": state,
            "state_label": _STATE_LABELS.get(state, state),
            "host": self._host,
            "port": self._port,
            "stream_url": self._stream_url,
            "device": snap.device_name or "未命名设备",
            "width": snap.width,
            "height": snap.height,
            "phone_fps": round(snap.phone_fps, 2) if snap.phone_fps else None,
            "receive_fps": round(snap.receive_fps, 2) if snap.receive_fps else None,
            "display_fps": round(snap.display_fps, 2) if snap.display_fps else None,
            "dropped_frames": snap.estimated_dropped_frames,
            "received_frames": snap.received_frames,
            "invalid_frames": snap.invalid_frames,
            "frame_stale": snap.frame_stale,
            "frame_age_seconds": round(snap.frame_age_seconds, 2),
            "bandwidth_mbps": round(snap.bandwidth_mbps, 2) if snap.bandwidth_mbps else None,
            "average_jpeg_bytes": (round(snap.average_jpeg_bytes)
                                   if snap.average_jpeg_bytes else None),
            "last_error": snap.last_error,
            "last_ping_at": (round(snap.last_ping_time, 3)
                             if snap.last_ping_time else None),
        }

    # ------------------------------------------------------------------
    # 视觉模式
    # ------------------------------------------------------------------

    def set_mode(self, mode_id: str) -> None:
        known = {m["id"] for m in VISION_MODES}
        if mode_id not in known:
            raise ApiError("bad_request", f"未知视觉模式: {mode_id}")
        with self._lock:
            self._mode = mode_id

    def set_params(self, values: dict) -> None:
        """按范围校验并更新当前参数（只接受已知键，避免注入任意参数）。"""
        if not isinstance(values, dict):
            raise ApiError("bad_request", "参数必须是对象")
        with self._lock:
            for key, value in values.items():
                if key not in PARAM_RANGES:
                    continue
                low, high = PARAM_RANGES[key]
                try:
                    number = int(round(float(value)))
                except (TypeError, ValueError):
                    raise ApiError("bad_request", f"参数 {key} 必须是数字")
                self._params[key] = max(low, min(high, number))

    def reset_params(self) -> None:
        with self._lock:
            self._params = dict(vision_modes.DEFAULT_PARAMS)

    def vision_state(self) -> dict:
        with self._lock:
            mode = self._mode
            params = dict(self._params)
        meta = next((m for m in VISION_MODES if m["id"] == mode), VISION_MODES[0])
        return {
            "mode": mode,
            "mode_label": meta["label"],
            "params": [
                {
                    "key": key,
                    "label": PARAM_LABELS.get(key, key),
                    "value": params[key],
                    "min": PARAM_RANGES[key][0],
                    "max": PARAM_RANGES[key][1],
                }
                for key in meta["params"]
            ],
            "hint": MODE_HINTS.get(mode, ""),
            "modes": [
                {"id": m["id"], "label": m["label"],
                 "label_en": m["label_en"]} for m in VISION_MODES
            ],
        }

    # ------------------------------------------------------------------
    # 帧
    # ------------------------------------------------------------------

    def latest_frame(self):
        """返回 (BGR ndarray, 帧号) 或 (None, None)。

        帧号是接收序号，用于"避免同一帧重复采集"（与 dataset_panel 一致）。
        """
        model = self._model
        if model is None:
            raise ApiError(ERR_NOT_CONNECTED, "尚未连接手机，请先连接设备")
        frame, number = model.get_latest_frame()
        if frame is None or number is None:
            raise ApiError(ERR_NO_FRAME,
                           "当前没有可用画面：请确认手机正在推流且网络正常")
        return frame, number

    def processed_frame(self):
        """返回 (处理后的 BGR ndarray, 帧号)。"""
        frame, number = self.latest_frame()
        with self._lock:
            mode = self._mode
            params = dict(self._params)
        return vision_modes.apply_mode(mode, frame, params), number

    def frame_jpeg(self, quality: int = 82) -> bytes:
        processed, _number = self.processed_frame()
        ok, buffer = cv2.imencode(
            ".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            raise ApiError("internal_error", "JPEG 编码失败")
        return buffer.tobytes()

    def snapshot_jpeg(self, quality: int = 92) -> bytes:
        """截图：原始画面（不应用当前模式），便于复盘"看到的是什么"。"""
        frame, _number = self.latest_frame()
        ok, buffer = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            raise ApiError("internal_error", "JPEG 编码失败")
        return buffer.tobytes()

    # ------------------------------------------------------------------
    # 指标（性能页 / 状态栏共用）
    # ------------------------------------------------------------------

    def transport_metrics(self) -> dict:
        """采集/接收/显示帧率与丢帧。

        口径与 docs/protocol.md、pvl_perf 一致：
          - 采集帧率：手机 /ping 自报 actualFps（手机侧测得）；
          - 接收帧率：PC 每秒成功解析的帧数；
          - 显示帧率：PC 实际绘制的帧数（web 端由前端显示回调累加）；
          - 丢帧：手机 frameCount 增量 - 本机 received 增量（AppModel 估算）。
        手机推理帧率、推理各阶段耗时、功耗不在本服务范围内，一律"未采集"。
        """
        status = self.status()
        return {
            "phone_capture_fps": status["phone_fps"],
            "pc_receive_fps": status["receive_fps"],
            "pc_display_fps": status["display_fps"],
            "dropped_frames": status["dropped_frames"],
            "received_frames": status["received_frames"],
            "invalid_frames": status["invalid_frames"],
            "bandwidth_mbps": status["bandwidth_mbps"],
            "average_jpeg_bytes": status["average_jpeg_bytes"],
            "resolution": (f"{status['width']}x{status['height']}"
                           if status["width"] and status["height"] else None),
        }

    def mark_frame_displayed(self) -> None:
        """前端每显示一帧调用一次，用于计算真实显示帧率。"""
        model = self._model
        if model is not None:
            model.mark_frame_displayed()


_STATE_LABELS = {
    app_model.STATE_CONNECTING: "连接中",
    app_model.STATE_STREAMING: "已连接 · 正在推流",
    app_model.STATE_RECONNECTING: "重连中",
    app_model.STATE_STOPPED: "已停止",
    app_model.STATE_ERROR: "连接错误",
}
