"""
PhoneVision Lab — 共享客户端状态模型（AppModel）。

职责：把"连接管理 + /ping 轮询 + 状态统计 + 生命周期"从两套 GUI 中抽出来，
供 Tkinter（app_gui.py）与 PySide6（qt_client/main_window.py）共同使用。
两套 GUI 只负责渲染与用户事件，网络、统计、丢帧全部在这里算。

为什么这样设计：
  - 此前 Tkinter 与 PySide6 各自在 _update_ping/_update_frame 里实现了一模一样的
    FPS/吞吐/丢帧算法，口径容易分叉。AppModel 成为唯一事实来源。
  - 本模块不 import tkinter / PySide6，不创建任何窗口，不依赖全局 GUI 对象，
    可被任意界面层安全使用，也便于离线单元测试。
  - 线程安全：后台 reader 线程 + GUI 主线程并发访问，用一把锁保护所有共享状态，
    snapshot() 返回不可变快照，避免主线程读到撕裂数据。

初学者调试观察点：
  - 状态在 Connecting / Streaming / Reconnecting / Stopped / Error 间切换，
    看 snapshot().connection_state。
  - 丢帧估算：手机 frameCount 增量 - 本机 received 增量，为正则累加 dropped。
  - stop() 后后台线程应有限退出（MjpegReader 用 daemon 线程 + stop_event）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import requests

import mjpeg_reader

# 状态常量
STATE_CONNECTING = "Connecting"
STATE_STREAMING = "Streaming"
STATE_RECONNECTING = "Reconnecting"
STATE_STOPPED = "Stopped"
STATE_ERROR = "Error"

# /ping 轮询间隔：成功 1s，失败退避到 5s
PING_OK_INTERVAL = 1.0
PING_FAIL_INTERVAL = 5.0


@dataclass(frozen=True)
class AppSnapshot:
    """不可变状态快照，GUI 每帧读取。所有字段原子、线程安全。"""
    connection_state: str
    device_name: str
    phone_fps: float            # 手机采集 FPS（来自 /ping actualFps）
    receive_fps: float          # PC 接收 FPS（解析成功的帧数/秒）
    display_fps: float          # PC 显示 FPS（UI 标记已显示帧数/秒）
    width: int
    height: int
    average_jpeg_bytes: float   # 平均 JPEG 大小（字节）
    bandwidth_mbps: float       # 网络吞吐
    received_frames: int
    invalid_frames: int
    estimated_dropped_frames: int
    last_error: str | None
    last_ping_time: float | None


class AppModel:
    """共享客户端状态模型。"""

    def __init__(self, stream_url: str, ping_url: str, device_name: str = "",
                 width: int = 0, height: int = 0, phone_fps: float = 0.0):
        self._stream_url = stream_url
        self._ping_url = ping_url

        # ---- 受锁保护的共享状态 ----
        self._lock = threading.RLock()
        self._reader: mjpeg_reader.MjpegReader | None = None
        self._running = False
        self._state = STATE_STOPPED

        self._device_name = device_name
        self._phone_fps = phone_fps
        self._receive_fps = 0.0
        self._display_fps = 0.0
        self._width = width
        self._height = height
        self._average_jpeg_bytes = 0.0
        self._bandwidth_mbps = 0.0
        self._invalid_frames = 0
        self._estimated_dropped = 0
        self._last_error: str | None = None
        self._last_ping_time: float | None = None

        # ---- 统计用本地状态（只在各自归属的线程写）----
        self._last_bytes = 0
        self._last_time = time.monotonic()
        self._recv_count = 0
        self._recv_t0 = time.monotonic()
        self._disp_count = 0
        self._disp_t0 = time.monotonic()
        self._last_ping = 0.0
        self._ping_interval = PING_OK_INTERVAL
        self._last_server_fc: int | None = None
        self._last_recv_total = 0

    # =====================================================================
    # 生命周期
    # =====================================================================

    def start(self) -> None:
        """启动 reader 线程。重复调用安全（不会启动多套线程）。"""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._state = STATE_CONNECTING
            self._reader = mjpeg_reader.MjpegReader(self._stream_url)
        self._reader.start()

    def stop(self) -> None:
        """停止 reader 线程。重复调用安全。stop 后线程在有限时间内退出。"""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._state = STATE_STOPPED
            reader = self._reader
            self._reader = None
        if reader is not None:
            reader.stop()  # set stop_event + join(3s)

    def reconnect(self) -> None:
        """手动重连：停旧 reader，起新 reader。在后台线程执行 stop+start。"""
        with self._lock:
            if not self._running:
                return
            self._state = STATE_RECONNECTING
            self._last_error = None
            old = self._reader
            self._reader = mjpeg_reader.MjpegReader(self._stream_url)
            new = self._reader

        def _swap():
            if old is not None:
                old.stop()
            new.start()

        threading.Thread(target=_swap, daemon=True, name="app-model-reconnect").start()

    # =====================================================================
    # 每帧/每秒更新（GUI 主线程调用）
    # =====================================================================

    def mark_frame_displayed(self) -> None:
        """UI 每显示一帧调用，用于计算显示 FPS。"""
        self._disp_count += 1

    def refresh(self) -> None:
        """每帧调用一次：汇总 reader 统计、计算接收 FPS / 吞吐 / 平均 JPEG。"""
        reader = self._reader
        if reader is None:
            return
        s = reader.get_stats()

        now = time.monotonic()

        # 接收 FPS
        self._recv_count += 1
        dt = now - self._recv_t0
        if dt >= 1.0:
            self._receive_fps = self._recv_count / dt
            self._recv_count = 0
            self._recv_t0 = now

        # 显示 FPS
        dt2 = now - self._disp_t0
        if dt2 >= 1.0:
            self._display_fps = self._disp_count / dt2
            self._disp_count = 0
            self._disp_t0 = now

        # 吞吐与平均 JPEG
        byte_delta = s["bytes"] - self._last_bytes
        dt3 = now - self._last_time
        if dt3 > 0:
            self._bandwidth_mbps = (byte_delta * 8 / 1e6) / dt3
        self._last_bytes = s["bytes"]
        self._last_time = now
        if s["received"] > 0:
            self._average_jpeg_bytes = s["bytes"] / s["received"]

        # 同步 reader 状态与计数
        with self._lock:
            self._state = s["state"]
            self._invalid_frames = s["invalid"]
            if s["last_error"]:
                self._last_error = s["last_error"]

        self._tick_ping()

    def _tick_ping(self) -> None:
        """按间隔请求 /ping 更新手机采集 FPS + 丢帧估算。不阻塞 UI 太久。"""
        now = time.monotonic()
        if now - self._last_ping < self._ping_interval:
            return
        self._last_ping = now
        reader = self._reader
        if reader is None:
            return
        try:
            info = requests.get(self._ping_url, timeout=1.0).json()
            self._phone_fps = float(info.get("actualFps", 0) or 0)
            self._ping_interval = PING_OK_INTERVAL
            self._last_ping_time = now
            with self._lock:
                if info.get("device"):
                    self._device_name = info.get("device")
                if info.get("width"):
                    self._width = int(info["width"])
                if info.get("height"):
                    self._height = int(info["height"])
            fc = info.get("frameCount")
            s = reader.get_stats()
            if self._last_server_fc is not None and fc is not None:
                server_delta = fc - self._last_server_fc
                local_delta = s["received"] - self._last_recv_total
                if server_delta > 0 and local_delta < server_delta:
                    self._estimated_dropped += (server_delta - local_delta)
            if fc is not None:
                self._last_server_fc = fc
            self._last_recv_total = s["received"]
        except Exception:
            self._ping_interval = PING_FAIL_INTERVAL

    # =====================================================================
    # 读取
    # =====================================================================

    def get_latest_frame(self):
        """返回 (BGR 帧 或 None, 帧序号 或 None)。"""
        reader = self._reader
        if reader is None:
            return None, None
        return reader.get_latest_frame()

    def snapshot(self) -> AppSnapshot:
        """线程安全地取不可变快照。"""
        with self._lock:
            return AppSnapshot(
                connection_state=self._state,
                device_name=self._device_name,
                phone_fps=self._phone_fps,
                receive_fps=self._receive_fps,
                display_fps=self._display_fps,
                width=self._width,
                height=self._height,
                average_jpeg_bytes=self._average_jpeg_bytes,
                bandwidth_mbps=self._bandwidth_mbps,
                received_frames=self._reader.get_stats()["received"] if self._reader else 0,
                invalid_frames=self._invalid_frames,
                estimated_dropped_frames=self._estimated_dropped,
                last_error=self._last_error,
                last_ping_time=self._last_ping_time,
            )

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def set_last_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
