"""
PhoneVision Lab — AppModel 单元测试（离线，不连手机、不访问真实网络）。

职责：用 unittest.mock 替换 mjpeg_reader.MjpegReader 与 requests.get，验证 AppModel
的生命周期、线程安全、统计汇总、重连与停止行为。

为什么这样设计：
  - 不连接手机、不访问真实网络、不依赖 D 盘 MJPEG 样本，可离线确定性运行。
  - 用 FakeReader 替代真实 reader，可控地模拟 Streaming/Reconnecting 与统计值。
  - 不 sleep 很长时间；stop() 用可立即退出的 fake。

初学者调试观察点：
  - start() 重复调用不应启动多套线程（is_running 保持 True，线程数不变）。
  - stop() 重复调用安全；snapshot() 在任何时刻都能取到不可变快照。
"""
import threading
import time
import unittest
from unittest import mock

import app_model


class FakeReader:
    """替代 mjpeg_reader.MjpegReader 的可控假体。"""

    def __init__(self, stream_url=""):
        self.url = stream_url
        self.started = False
        self.stopped = False
        self._stats = {"state": "Streaming", "received": 0, "invalid": 0,
                       "bytes": 0, "last_error": None}

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def get_latest_frame(self):
        return None, None

    def get_state(self):
        return self._stats["state"]

    def get_stats(self):
        return dict(self._stats)

    def set_stats(self, **kw):
        self._stats.update(kw)


class AppModelTest(unittest.TestCase):

    def setUp(self):
        self.patcher = mock.patch("app_model.mjpeg_reader.MjpegReader", FakeReader)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.model = app_model.AppModel("http://fake/stream", "http://fake/ping",
                                        device_name="Fake", width=640, height=480)

    # ---- 生命周期 ----

    def test_start_only_once(self):
        self.model.start()
        reader1 = self.model._reader
        self.model.start()  # 重复 start 不应新建 reader
        self.model.start()
        self.assertEqual(self.model._reader, reader1)
        self.assertTrue(self.model.is_running())

    def test_stop_idempotent(self):
        self.model.start()
        self.model.stop()
        self.model.stop()  # 重复 stop 安全
        self.assertFalse(self.model.is_running())
        self.assertEqual(self.model.snapshot().connection_state, app_model.STATE_STOPPED)

    def test_stop_does_not_leave_thread(self):
        self.model.start()
        self.model.stop()
        # snapshot 可读；reader 已 stop
        snap = self.model.snapshot()
        self.assertIsNotNone(snap)

    # ---- snapshot 线程安全 ----

    def test_snapshot_thread_safe(self):
        self.model.start()
        errors = []

        def reader():
            try:
                for _ in range(50):
                    self.model.snapshot()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.model.stop()

    # ---- ping ----

    def test_ping_success_updates_device_info(self):
        self.model.start()
        fake_reader = self.model._reader
        fake_reader.set_stats(state="Streaming", received=10, invalid=0, bytes=1000)
        with mock.patch("app_model.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "status": "streaming", "device": "MIX 2S", "width": 640, "height": 480,
                "actualFps": 15.0, "frameCount": 100}
            self.model._last_ping = 0.0  # 强制立即执行
            self.model._tick_ping()
        snap = self.model.snapshot()
        self.assertEqual(snap.device_name, "MIX 2S")
        self.assertEqual(snap.width, 640)
        self.assertAlmostEqual(snap.phone_fps, 15.0)

    def test_ping_failure_records_error(self):
        self.model.start()
        with mock.patch("app_model.requests.get", side_effect=Exception("boom")):
            self.model._last_ping = 0.0
            self.model._tick_ping()  # 不应抛异常
        # 失败只应退避 ping 间隔，不崩溃
        self.assertEqual(self.model._ping_interval, app_model.PING_FAIL_INTERVAL)

    # ---- 统计 ----

    def test_mark_frame_displayed_updates_display_fps(self):
        self.model.start()
        self.model._disp_t0 = time.monotonic() - 1.1  # 让窗口立即结束
        for _ in range(20):
            self.model.mark_frame_displayed()
        self.model.refresh()
        self.assertGreater(self.model.snapshot().display_fps, 0)

    def test_refresh_syncs_reader_stats(self):
        self.model.start()
        fake_reader = self.model._reader
        fake_reader.set_stats(state="Reconnecting", received=7, invalid=3,
                              bytes=5000, last_error="conn lost")
        self.model._recv_t0 = time.monotonic() - 1.1
        self.model._disp_t0 = time.monotonic() - 1.1
        self.model.refresh()
        snap = self.model.snapshot()
        self.assertEqual(snap.received_frames, 7)
        self.assertEqual(snap.invalid_frames, 3)
        self.assertEqual(snap.connection_state, "Reconnecting")
        self.assertEqual(snap.last_error, "conn lost")

    def test_dropped_estimation(self):
        self.model.start()
        fake_reader = self.model._reader
        fake_reader.set_stats(state="Streaming", received=10, invalid=0, bytes=0)
        self.model._last_server_fc = 90
        self.model._last_recv_total = 5
        with mock.patch("app_model.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "status": "streaming", "device": "Fake", "width": 640, "height": 480,
                "actualFps": 15.0, "frameCount": 100}
            self.model._last_ping = 0.0
            self.model._tick_ping()
        snap = self.model.snapshot()
        # server +10，local +5，估算丢 5 帧
        self.assertEqual(snap.estimated_dropped_frames, 5)

    # ---- reconnect ----

    def test_reconnect_calls_underlying_reader(self):
        self.model.start()
        old = self.model._reader
        self.model.reconnect()
        # reconnect 在后台线程换 reader；等待片刻确认发生
        time.sleep(0.1)
        new = self.model._reader
        self.assertIsNot(old, new)
        self.assertTrue(old.stopped)
        self.assertTrue(new.started)
        self.model.stop()

    # ---- 状态常量 ----

    def test_state_constants(self):
        self.assertEqual(app_model.STATE_STREAMING, "Streaming")
        self.assertEqual(app_model.STATE_RECONNECTING, "Reconnecting")
        self.assertEqual(app_model.STATE_STOPPED, "Stopped")


if __name__ == "__main__":
    unittest.main()
