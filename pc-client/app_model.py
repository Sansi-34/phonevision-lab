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
  - 线程安全：后台 reader 线程 + ping worker 线程 + GUI 主线程并发访问，
    用一把锁保护所有共享状态，snapshot() 返回不可变快照，避免读到撕裂数据。
  - /ping 在 AppModel 管理的后台 worker 中执行，refresh() 永不发起 HTTP 请求，
    GUI 主线程不会被网络阻塞。

初学者调试观察点：
  - 状态在 Connecting / Streaming / Reconnecting / Stopped / Error 间切换，
    看 snapshot().connection_state。
  - 丢帧估算：手机 frameCount 增量 - 本机 received 增量，为正则累加 dropped。
  - 接收 FPS 基于 reader 实际新增接收帧数计算，与 GUI 调用 refresh 的频率无关。
  - stop() 后后台线程应有限退出（MjpegReader 用 daemon 线程 + stop_event；
    ping worker 用 stop_event.wait 及时退出）。
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
        # 接收 FPS 基于 reader 实际新增接收帧，不基于 refresh 调用次数
        self._recv_total_last = 0
        self._recv_t0 = time.monotonic()
        self._disp_count = 0
        self._disp_t0 = time.monotonic()
        self._last_bytes = 0
        self._last_time = time.monotonic()

        # ---- /ping worker 状态 ----
        self._ping_stop_event = threading.Event()
        self._ping_thread: threading.Thread | None = None
        self._ping_interval = PING_OK_INTERVAL
        self._last_server_fc: int | None = None
        self._last_recv_total = 0

        # ---- reconnect worker 状态 ----
        self._reconnect_thread: threading.Thread | None = None

    # =====================================================================
    # 生命周期
    # =====================================================================

    def start(self) -> None:
        """启动 reader 线程与 /ping worker。重复调用安全（不会启动多套线程）。"""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._state = STATE_CONNECTING
            self._reader = mjpeg_reader.MjpegReader(self._stream_url)
            # 重置 stop 事件，确保后续 start 能重启 ping worker
            self._ping_stop_event = threading.Event()
        self._reader.start()
        self._ping_thread = threading.Thread(
            target=self._ping_loop, daemon=True, name="app-model-ping")
        self._ping_thread.start()

    def stop(self) -> None:
        """停止 reader 线程与所有后台 worker。重复调用安全。stop 后有限时间内退出。"""
        with self._lock:
            if not self._running:
                # 已停止：仍回收可能残留的 reconnect worker
                rt = self._reconnect_thread
                self._reconnect_thread = None
                if rt is not None:
                    rt.join(timeout=2.0)
                return
            self._running = False
            self._state = STATE_STOPPED
            reader = self._reader
            self._reader = None
            rt = self._reconnect_thread
            self._reconnect_thread = None
        if reader is not None:
            reader.stop()  # set stop_event + join(3s)
        # 停止 /ping worker
        self._ping_stop_event.set()
        if self._ping_thread is not None and self._ping_thread.is_alive():
            self._ping_thread.join(timeout=2.0)
        # 回收 reconnect worker
        if rt is not None and rt.is_alive():
            rt.join(timeout=2.0)

    def reconnect(self) -> None:
        """手动重连：停旧 reader，起新 reader。在后台线程执行 stop+start。

        同一时刻最多一个 reconnect worker；连续点击不会产生线程风暴。
        """
        with self._lock:
            if not self._running:
                return
            # 防重：已有 reconnect worker 在运行则跳过本次请求
            if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
                return
            self._state = STATE_RECONNECTING
            self._last_error = None
            old = self._reader
            self._reader = mjpeg_reader.MjpegReader(self._stream_url)
            new = self._reader

        def _swap():
            try:
                if old is not None:
                    old.stop()
                # 停止后不得再启动新 reader / 覆盖状态
                with self._lock:
                    if not self._running:
                        return
                new.start()
            finally:
                with self._lock:
                    if self._reconnect_thread is threading.current_thread():
                        self._reconnect_thread = None

        t = threading.Thread(target=_swap, daemon=True, name="app-model-reconnect")
        with self._lock:
            self._reconnect_thread = t
        t.start()

    # =====================================================================
    # 每帧/每秒更新（GUI 主线程调用，绝不发起网络请求）
    # =====================================================================

    def mark_frame_displayed(self) -> None:
        """UI 每显示一帧调用，用于计算显示 FPS。"""
        self._disp_count += 1

    def refresh(self) -> None:
        """每帧调用一次：汇总 reader 统计、计算接收 FPS / 显示 FPS / 吞吐 / 平均 JPEG。

        本方法不做任何 HTTP 请求、阻塞等待或 sleep；/ping 由后台 worker 负责。
        """
        reader = self._reader
        if reader is None:
            return
        s = reader.get_stats()

        now = time.monotonic()

        # 接收 FPS：基于 reader 实际新增接收帧，与 refresh 调用频率无关
        self._update_receive_fps(s["received"], now)

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
            if byte_delta >= 0:
                self._bandwidth_mbps = (byte_delta * 8 / 1e6) / dt3
            else:
                # reader 计数归零（重连后新 reader），重置基线
                self._bandwidth_mbps = 0.0
        self._last_bytes = s["bytes"]
        self._last_time = now
        if s["received"] > 0:
            self._average_jpeg_bytes = s["bytes"] / s["received"]

        # 同步 reader 状态与计数
        with self._lock:
            # reconnect() 已置 Reconnecting：新 reader 初始为 Idle，
            # 不能把重连中的状态覆盖回 Idle，否则 UI 状态闪回
            if not (self._state == STATE_RECONNECTING and s["state"] == "Idle"):
                self._state = s["state"]
            self._invalid_frames = s["invalid"]
            if s["last_error"]:
                self._last_error = s["last_error"]

    def _update_receive_fps(self, received: int, now: float) -> None:
        """基于 reader 新增接收帧数计算接收 FPS。

        - 计数器重置或下降（重连后新 reader 从 0 开始）时重置基线，不产生负值。
        - 时间窗口不足 1 秒时保留旧值，避免抖动。
        - 没有新帧时 delta 为 0，不会继续虚增。
        """
        delta = received - self._recv_total_last
        dt = now - self._recv_t0
        if delta < 0:
            # 计数下降：重连后的新 reader 计数归零，重置基线
            self._recv_total_last = received
            self._recv_t0 = now
            return
        if dt >= 1.0:
            self._receive_fps = delta / dt
            self._recv_total_last = received
            self._recv_t0 = now

    # =====================================================================
    # /ping 后台 worker（绝不运行在 GUI 线程）
    # =====================================================================

    def _ping_loop(self) -> None:
        """/ping 轮询循环：先立即 ping 一次，之后按间隔循环。仅 ping worker 线程运行。"""
        while not self._ping_stop_event.is_set():
            self._ping_once()
            if self._ping_stop_event.wait(self._ping_interval):
                break

    def _ping_once(self) -> None:
        """执行一次 /ping 并在锁内更新共享状态。仅 ping worker 线程调用。"""
        resp = None
        try:
            resp = requests.get(self._ping_url, timeout=1.0)
            info = resp.json()
        except Exception:
            with self._lock:
                self._ping_interval = PING_FAIL_INTERVAL
            return
        finally:
            if resp is not None:
                resp.close()

        now = time.monotonic()
        with self._lock:
            self._phone_fps = float(info.get("actualFps", 0) or 0)
            self._ping_interval = PING_OK_INTERVAL
            self._last_ping_time = now
            if info.get("device"):
                self._device_name = info.get("device")
            if info.get("width"):
                self._width = int(info["width"])
            if info.get("height"):
                self._height = int(info["height"])
            fc = info.get("frameCount")
            reader = self._reader
            received = reader.get_stats()["received"] if reader else 0
            if self._last_server_fc is not None and fc is not None:
                server_delta = fc - self._last_server_fc
                local_delta = received - self._last_recv_total
                if server_delta > 0 and local_delta < server_delta:
                    self._estimated_dropped += (server_delta - local_delta)
            if fc is not None:
                self._last_server_fc = fc
            self._last_recv_total = received

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

    def get_state(self) -> str:
        """返回当前连接状态字符串（兼容 self.reader 别名下的旧调用）。"""
        with self._lock:
            return self._state

    def set_last_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
