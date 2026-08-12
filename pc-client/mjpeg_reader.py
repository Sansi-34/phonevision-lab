"""
PhoneVision Lab — MJPEG-over-HTTP 流接收器。

职责：在独立后台线程里读取手机的 multipart/x-mixed-replace MJPEG 流，
严格按 boundary + Content-Length 解析出 JPEG 帧，解码后只保留最新一帧，
供主线程实时取用。

为什么这样设计：
  - 不用 cv2.VideoCapture(URL)：它的内部缓冲不透明，消费者变慢时帧会持续
    堆积，造成"延迟随运行时间累积"。这里"只保留最新帧、新帧覆盖旧帧"，
    处理多慢都只落后一帧，延迟可控。
  - 独立线程 + 有界语义：网络 I/O 不阻塞主线程的 OpenCV 处理。
  - 断线自动重连（1,2,3,5 秒退避）：网络抖动、手机推流停止再启动都能恢复。
  - 严格按 boundary/Content-Length 解析而不是搜 JPEG 标志，保证协议正确。

初学者调试观察点：
  - 看状态从 Streaming 变 Reconnecting，通常是手机推流停了或 WiFi 断。
  - invalidFrames 增加说明网络丢包导致 JPEG 不完整，属可接受，会跳过。
"""
import threading
import time
import requests

# 每个请求的最大字节数。示例帧约 740KB，这里给足余量但不无限增长。
# 若一帧超过该上限，视为异常帧跳过。
_MAX_FRAME_BYTES = 5 * 1024 * 1024  # 5 MB

# 字节常量
_SOI = b"\xff\xd8"  # JPEG 起始标志
_EOI = b"\xff\xd9"  # JPEG 结束标志
_CRLF = b"\r\n"


class MjpegReader:
    """读取手机 MJPEG 流的后台线程封装。"""

    def __init__(self, stream_url: str, max_backlog_reconnect: int = 5):
        self._url = stream_url
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mjpeg-reader")

        # ---- 共享状态（主线程读，读线程写）----
        self._lock = threading.Lock()
        self._latest_frame = None          # 最新解码帧 (BGR ndarray)
        self._latest_frame_num = None      # 该帧的接收序号
        self._state = "Idle"               # Idle / Connecting / Streaming / Reconnecting
        self._received_frames = 0          # 完整解析并解码的帧数
        self._invalid_frames = 0           # 解析失败的帧数
        self._bytes_read = 0               # 收到的原始字节总数（算带宽用）
        self._last_error = None            # 最近一次错误信息

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def start(self):
        """启动后台读取线程。"""
        self._thread.start()

    def stop(self):
        """请求停止，并等待线程退出。"""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def get_latest_frame(self):
        """返回 (帧, 序号)；无可用帧时返回 (None, None)。"""
        with self._lock:
            return self._latest_frame, self._latest_frame_num

    def get_state(self):
        """返回当前状态字符串。"""
        with self._lock:
            return self._state

    def get_stats(self):
        """返回统计字典，供显示叠加。"""
        with self._lock:
            return {
                "state": self._state,
                "received": self._received_frames,
                "invalid": self._invalid_frames,
                "bytes": self._bytes_read,
                "last_error": self._last_error,
            }

    def reset_received_baseline(self):
        """复位已接收帧计数，用于计算"每单位时间的接收速率"。"""
        with self._lock:
            self._received_frames = 0
            self._bytes_read = 0

    # ------------------------------------------------------------------
    # 后台线程主体
    # ------------------------------------------------------------------

    def _run(self):
        """重连循环：Connecting -> Streaming，断线后按退避重连。"""
        # 有限退避：1, 2, 3 秒（共 6 秒），保证断线后 10 秒内能重试
        backoff_seconds = [1, 2, 3]

        while not self._stop_event.is_set():
            self._set_state("Connecting")
            try:
                self._stream_once()
            except Exception as e:  # noqa: BLE001 - 读线程吞掉所有异常继续重连
                self._set_state("Reconnecting")
                self._set_last_error(str(e))
            # 无论正常断开还是异常，都退避等待后重连；期间收到停止请求则退出
            if self._backoff_wait(backoff_seconds):
                return

    def _backoff_wait(self, backoff_seconds):
        """按退避序列等待一轮；若期间收到停止请求返回 True。"""
        for delay in backoff_seconds:
            if self._stop_event.wait(delay):
                return True
        return False

    def _stream_once(self):
        """建立一次连接并持续消费流，直到断开或停止。"""
        resp = requests.get(
            self._url,
            stream=True,
            timeout=(3.0, 5.0),  # (连接超时, 读取超时)
            headers={"Connection": "keep-alive"},
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        boundary = self._extract_boundary(content_type)
        if boundary is None:
            resp.close()
            raise ValueError(f"Content-Type 缺少 boundary: {content_type!r}")

        # 状态改为 Streaming
        self._set_state("Streaming")
        # 连接成功：清空上次的错误，避免状态栏永久滞留旧错误
        self._set_last_error(None)

        # 用迭代器逐块读取，按 boundary 切分
        boundary_delim = b"--" + boundary.encode("latin-1")
        buffer = bytearray()
        boundary_found = False  # 第一个 boundary 之前的内容（空 HTTP 体之前）忽略

        try:
            for chunk in resp.iter_content(chunk_size=65536):
                if self._stop_event.is_set():
                    break
                buffer.extend(chunk)
                self._add_bytes(len(chunk))

                # 从 buffer 中逐个提取 part
                while True:
                    # 找当前 buffer 里第一个 boundary
                    idx = buffer.find(boundary_delim)
                    if idx == -1:
                        # 缓冲过大（一整个大帧都装不下），说明协议异常
                        if len(buffer) > _MAX_FRAME_BYTES * 2:
                            self._count_invalid()
                            buffer.clear()
                        break

                    # boundary 之前是一个完整 part（首 boundary 前为空）
                    part = buffer[:idx]
                    buffer = buffer[idx + len(boundary_delim):]

                    if not boundary_found:
                        boundary_found = True
                        continue  # 第一个 part 通常为空（头部之后）

                    self._handle_part(part)
        finally:
            resp.close()
            # 流结束（正常断开或被停止），若仍在读则标记重连
            if not self._stop_event.is_set():
                self._set_state("Reconnecting")

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------

    def _handle_part(self, part: bytes):
        """处理一个 part：跳过 HTTP 头，校验并解码 JPEG。"""
        # 去掉前导 CRLF（boundary 后面通常是 \r\n）
        if part.startswith(_CRLF):
            part = part[len(_CRLF):]

        # 找到 part 头结束（\r\n\r\n）
        header_end = part.find(_CRLF + _CRLF)
        if header_end == -1:
            self._count_invalid()
            return

        headers_blob = part[:header_end]
        body = part[header_end + len(_CRLF + _CRLF):]

        # 去掉尾部 CRLF（part 结束处）
        if body.endswith(_CRLF):
            body = body[:-len(_CRLF)]

        content_length = self._parse_content_length(headers_blob)
        if content_length is None:
            self._count_invalid()
            return

        # Content-Length 校验：不匹配视为残缺帧
        if len(body) != content_length:
            self._count_invalid()
            return

        # JPEG 头尾校验
        if not body.startswith(_SOI) or not body.endswith(_EOI):
            self._count_invalid()
            return

        # 解码
        frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            self._count_invalid()
            return

        with self._lock:
            self._latest_frame = frame
            self._latest_frame_num = self._received_frames
            self._received_frames += 1

    def _parse_content_length(self, headers_blob: bytes) -> int | None:
        """从 part 头里解析 Content-Length。"""
        for line in headers_blob.split(_CRLF):
            low = line.lower()
            if low.startswith(b"content-length:"):
                try:
                    return int(line.split(b":", 1)[1].strip())
                except ValueError:
                    return None
        return None

    @staticmethod
    def _extract_boundary(content_type: str) -> str | None:
        """从 Content-Type 里提取 boundary 参数。"""
        for part in content_type.split(";"):
            part = part.strip()
            if part.lower().startswith("boundary="):
                val = part[len("boundary="):].strip().strip('"')
                return val or None
        return None

    # ------------------------------------------------------------------
    # 状态/统计辅助
    # ------------------------------------------------------------------

    def _set_state(self, state: str):
        with self._lock:
            self._state = state

    def _set_last_error(self, msg: str):
        with self._lock:
            self._last_error = msg

    def _add_bytes(self, n: int):
        with self._lock:
            self._bytes_read += n

    def _count_invalid(self):
        with self._lock:
            self._invalid_frames += 1


# cv2 / numpy 在模块顶层导入，避免循环依赖，也便于测试替换
import cv2  # noqa: E402
import numpy as np  # noqa: E402
