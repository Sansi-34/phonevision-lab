"""
PhoneVision Lab — MjpegReader 离线单元测试。

不访问真实网络：用 unittest.mock 替换 mjpeg_reader.requests.get，
把 MJPEG 样本文件（或合成的字节流）通过假 response 喂给解析逻辑，验证：

  - 真实样本能解析出全部完整帧（79 帧）；
  - curl 截断的最后一 part 残缺，被静默丢弃，不误计入帧数、不抛异常；
  - Content-Length 声明与实际体长不符的帧被记为 invalid，不计入 received；
  - SOI/EOI 头尾缺失的帧被记为 invalid，不计入 received；
  - 后台线程喂入截断样本时不抛未处理异常。

关键设计：
  - 测试不复制 58.8MB 样本，直接从原路径读取；
  - 直接调用 reader._stream_once()（单次连接消费逻辑，不进入重连循环），
    最适合单元测试，也避免线程停不下来。

运行：python -m unittest tests.test_mjpeg_reader -v
"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

import cv2
import numpy as np

# 让本文件不依赖"当前工作目录"就能 import 到 mjpeg_reader
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mjpeg_reader  # noqa: E402

# 真实 MJPEG 样本：约 80 个 part，最后一 part 因 curl 超时截断不完整。
# 样本未纳入 Git（被 .gitignore 忽略，仅本机存在），测试读取时用相对仓库根路径。
_SAMPLE_REL = os.path.join("android", "v0-a4-stream-sample.mjpeg")
SAMPLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    _SAMPLE_REL,
)

BOUNDARY = "phonevision-boundary"
CONTENT_TYPE = "multipart/x-mixed-replace;boundary=%s" % BOUNDARY
BOUNDARY_DELIM = b"--" + BOUNDARY.encode("latin-1")

# 读取样本时的分块大小，与 MjpegReader 请求的 iter_content 大小一致，
# 也用来模拟网络分片（一帧会被切成多块，boundary 经常跨块出现）
_CHUNK_SIZE = 65536


def _make_jpeg_bytes() -> bytes:
    """离线生成一张合法的 JPEG 字节（64x64 蓝色块）。"""
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    img[:, :, 0] = 180  # B 通道设为 180 -> 蓝色
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise RuntimeError("cv2.imencode 失败，无法构造测试帧")
    return buf.tobytes()


def require_sample(func):
    """样本文件缺失时跳过依赖真实样本的测试，其余测试照常运行。"""
    return unittest.skipUnless(
        os.path.exists(SAMPLE_PATH),
        "样本文件缺失，跳过依赖真实样本的测试：%s" % SAMPLE_PATH,
    )(func)


class FakeResponse:
    """模拟 requests.Response，只实现 MjpegReader 用到的接口。

    真实代码会调用：resp.raise_for_status()、
    resp.headers.get("Content-Type")、resp.iter_content(chunk_size)、
    resp.close()。这里全部离线实现，不碰网络。
    """

    def __init__(self, chunks):
        self.headers = {"Content-Type": CONTENT_TYPE}
        self._chunks = chunks
        self.closed = False

    def raise_for_status(self):
        """模拟 HTTP 200，不抛错。"""
        pass

    def iter_content(self, chunk_size=65536):
        """逐块 yield 预先生成好的数据块，模拟网络分片。"""
        return iter(self._chunks)

    def close(self):
        self.closed = True


class MjpegReaderOfflineTest(unittest.TestCase):
    """把样本文件或合成字节流喂给 MjpegReader 的离线测试。"""

    sample_chunks = None  # 样本只读一次、切成块，多个测试复用

    @classmethod
    def setUpClass(cls):
        with open(SAMPLE_PATH, "rb") as f:
            data = f.read()
        cls.sample_chunks = [
            data[i : i + _CHUNK_SIZE] for i in range(0, len(data), _CHUNK_SIZE)
        ]

    @staticmethod
    def _run_stream(chunks):
        """创建 reader，用 mock 替换 requests.get，跑一次 _stream_once。

        _stream_once 是单次连接的消费逻辑：for chunk in resp.iter_content
        走完（或抛错）就返回，不进入重连退避循环，最适合单元测试。
        """
        reader = mjpeg_reader.MjpegReader("http://127.0.0.1:8080/stream")
        fake = FakeResponse(chunks)
        with mock.patch.object(mjpeg_reader.requests, "get", return_value=fake):
            reader._stream_once()
        return reader

    @staticmethod
    def _synthetic_stream(parts):
        """把 [(声明 Content-Length, body), ...] 拼成一条合法的 multipart 字节流。

        格式与样本一致：--boundary 后接 \r\n + part 头 + \r\n\r\n + 体 + \r\n，
        下一个 part 以 --boundary 开头。
        """
        stream = BOUNDARY_DELIM
        for declared_len, body in parts:
            headers = b"Content-Type: image/jpeg\r\n"
            headers += b"Content-Length: %d\r\n" % declared_len
            stream += b"\r\n" + headers + b"\r\n" + body + b"\r\n" + BOUNDARY_DELIM
        return stream

    # ------------------------------------------------------------------
    # 真实样本
    # ------------------------------------------------------------------

    @require_sample
    def test_parses_at_least_79_frames(self):
        """真实样本应解析出至少 79 个完整帧。"""
        reader = self._run_stream(self.sample_chunks)
        stats = reader.get_stats()
        self.assertGreaterEqual(stats["received"], 79)

    @require_sample
    def test_truncated_tail_ignored(self):
        """样本最后一 part 被 curl 截断（不完整），应被跳过：
        不计入 received，也不计入 invalid（悬挂在缓冲区、直接丢弃）。"""
        reader = self._run_stream(self.sample_chunks)
        stats = reader.get_stats()
        self.assertEqual(stats["received"], 79)  # 79 个完整 part 全部解析成功
        self.assertEqual(stats["invalid"], 0)    # 残缺尾部不算"解析失败"

    @require_sample
    def test_no_unhandled_exception_on_truncated_tail(self):
        """把截断样本喂给读取线程：线程不抛未处理异常、正常退出，
        之后 get_stats 可调用，状态是 Streaming 或 Reconnecting。"""
        errors = []
        result = {}

        def worker():
            try:
                result["reader"] = self._run_stream(self.sample_chunks)
            except Exception as exc:  # noqa: BLE001 - 测试里收集线程异常
                errors.append(exc)

        t = threading.Thread(target=worker, name="test-feed")
        t.start()
        t.join(timeout=120)
        self.assertFalse(t.is_alive(), "读取线程未在限时内退出")
        self.assertEqual(errors, [], "读取线程抛出未处理异常: %r" % (errors,))

        stats = result["reader"].get_stats()
        self.assertIn(stats["state"], ("Streaming", "Reconnecting"))
        self.assertIsInstance(stats["received"], int)

    # ------------------------------------------------------------------
    # 合成的异常帧
    # ------------------------------------------------------------------

    def test_content_length_mismatch_not_counted(self):
        """Content-Length 声明与实际体长不符的帧：不计入 received，invalid +1。"""
        body = _make_jpeg_bytes()
        wrong_declared = len(body) + 123  # 故意声明错
        stream = self._synthetic_stream([(wrong_declared, body)])
        reader = self._run_stream([stream])
        stats = reader.get_stats()
        self.assertEqual(stats["received"], 0)
        self.assertEqual(stats["invalid"], 1)

    def test_invalid_jpeg_increments_invalid(self):
        """SOI/EOI 头尾缺失的帧：不计入 received，invalid +1。"""
        body = _make_jpeg_bytes()
        bad_bodies = (
            ("missing-EOI", body[:-2]),  # 截掉结尾 \xff\xd9
            ("missing-SOI", body[2:]),   # 去掉开头 \xff\xd8
        )
        for label, bad_body in bad_bodies:
            with self.subTest(case=label):
                # 声明长度与体长相符，所以唯一失败原因是 SOI/EOI 校验
                stream = self._synthetic_stream([(len(bad_body), bad_body)])
                reader = self._run_stream([stream])
                stats = reader.get_stats()
                self.assertEqual(stats["received"], 0)
                self.assertEqual(stats["invalid"], 1)


class BlockingResponse(FakeResponse):
    """iter_content 一直阻塞到 close() 被调用，模拟真实 socket 读。

    用来验证 stop() 是"主动关闭连接打断读"，而不是干等 5s 读取超时。
    """

    def __init__(self):
        super().__init__([])
        self.released = threading.Event()
        self.close_calls = 0

    def iter_content(self, chunk_size=65536):
        def gen():
            # 阻塞到 stop() 关连接；随后像真实 requests 一样抛错，
            # 由 MjpegReader._run 的异常分支吞掉并退出。
            self.released.wait(timeout=30)
            raise OSError("connection closed by stop()")
            yield b""  # pragma: no cover - 让 gen 成为生成器
        return gen()

    def close(self):
        self.close_calls += 1
        self.closed = True
        self.released.set()


class MjpegReaderLifecycleTest(unittest.TestCase):
    """start()/stop() 生命周期：线程必须能被及时停止，连接必须被关闭。"""

    def test_stop_closes_response_and_joins_fast(self):
        """stop() 必须关闭底层连接并快速退出线程。

        原缺陷：stop() 只置 flag，读线程仍阻塞在 iter_content 的 socket read
        里（最多 5s），join(3.0) 常态超时；重连时旧线程继续占着连接和带宽。
        """
        reader = mjpeg_reader.MjpegReader("http://127.0.0.1:8080/stream")
        fake = BlockingResponse()
        with mock.patch.object(mjpeg_reader.requests, "get", return_value=fake):
            reader.start()
            for _ in range(500):  # 等线程真正进入 iter_content
                if reader.get_state() == "Streaming":
                    break
                time.sleep(0.01)
            self.assertEqual(reader.get_state(), "Streaming",
                             "线程应已建立连接并进入 Streaming")
            started = time.monotonic()
            reader.stop()
            elapsed = time.monotonic() - started

        self.assertTrue(fake.closed, "stop() 必须关闭底层连接以打断阻塞读")
        self.assertLess(elapsed, 1.0, f"stop() 应快速返回，实耗 {elapsed:.2f}s")
        self.assertFalse(reader._thread.is_alive(), "读线程必须已退出")

    def test_http_error_closes_response(self):
        """raise_for_status 抛错时也必须关闭连接。

        原缺陷：finally 从 for 循环才开始，status 检查失败会漏关 stream=True
        的连接，每失败一次重连就漏一个连接（靠 GC 兜底）。
        """
        class ErrorResponse(FakeResponse):
            def raise_for_status(self):
                raise RuntimeError("500 Server Error")

        reader = mjpeg_reader.MjpegReader("http://127.0.0.1:8080/stream")
        fake = ErrorResponse([])
        with mock.patch.object(mjpeg_reader.requests, "get", return_value=fake):
            with self.assertRaises(RuntimeError):
                reader._stream_once()
        self.assertTrue(fake.closed, "异常路径也必须关闭连接")
        self.assertIsNone(reader._resp)

    def test_missing_boundary_closes_response(self):
        """Content-Type 没有 boundary 时抛 ValueError 且关闭连接。"""
        class NoBoundaryResponse(FakeResponse):
            def __init__(self):
                super().__init__([])
                self.headers = {"Content-Type": "text/plain"}

        reader = mjpeg_reader.MjpegReader("http://127.0.0.1:8080/stream")
        fake = NoBoundaryResponse()
        with mock.patch.object(mjpeg_reader.requests, "get", return_value=fake):
            with self.assertRaises(ValueError):
                reader._stream_once()
        self.assertTrue(fake.closed)

    def test_503_raises_stream_not_ready(self):
        """上游 503（相机尚未推流）应抛 StreamNotReady，走快重试而非秒级退避。"""
        class NotReadyResponse(FakeResponse):
            status_code = 503

            def raise_for_status(self):  # 真实 requests 会在这里抛 503
                raise RuntimeError("503 Server Error")

        reader = mjpeg_reader.MjpegReader("http://127.0.0.1:8080/stream")
        fake = NotReadyResponse([])
        with mock.patch.object(mjpeg_reader.requests, "get", return_value=fake):
            with self.assertRaises(mjpeg_reader.StreamNotReady):
                reader._stream_once()
        self.assertTrue(fake.closed, "503 路径也必须关闭连接")

    def test_stream_not_ready_retries_fast(self):
        """StreamNotReady 的重试间隔必须远小于断线退避（1s 起）。"""
        reader = mjpeg_reader.MjpegReader("http://127.0.0.1:8080/stream")
        calls = []

        def fake_once():
            calls.append(time.monotonic())
            if len(calls) >= 3:
                reader._stop_event.set()   # 第 3 次后收工
            raise mjpeg_reader.StreamNotReady("camera starting")

        with mock.patch.object(reader, "_stream_once", side_effect=fake_once):
            started = time.monotonic()
            reader._run()
            elapsed = time.monotonic() - started

        self.assertGreaterEqual(len(calls), 2)
        # 两次快重试累计约 0.3s×2；若误用 1/2/3 秒退避这里会 >= 2s。
        self.assertLess(elapsed, 1.5, f"503 重试过快/过慢，实耗 {elapsed:.2f}s")
        self.assertEqual(reader.get_stats()["last_error"], "camera starting")


if __name__ == "__main__":
    unittest.main()
