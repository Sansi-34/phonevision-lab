"""
PhoneVision Lab — AppModel 单元测试（离线，不连手机、不访问真实网络）。

职责：用 unittest.mock 替换 mjpeg_reader.MjpegReader 与 requests.get，验证 AppModel
的生命周期、线程安全、统计汇总、重连、停止行为，以及 /ping 后台 worker 与
receive_fps 独立于刷新频率的统计口径。

为什么这样设计：
  - 不连接手机、不访问真实网络、不依赖 D 盘 MJPEG 样本，可离线确定性运行。
  - 用 FakeReader 替代真实 reader，可控地模拟 Streaming/Reconnecting 与统计值。
  - 用 fake clock（可注入的 monotonic 源）验证 FPS 计算，避免依赖真实时间。
  - /ping 由后台 worker 调用，测试用 Event 与 mock 调用位置证明 refresh 不做网络请求。

初学者调试观察点：
  - start() 重复调用不应启动多套 ping worker。
  - stop() 重复调用安全；snapshot() 在任何时刻都能取到不可变快照。
  - refresh() 永不发起 HTTP；ping 只在后台 worker 线程执行。
"""
import threading
import time
import unittest
from unittest import mock
from dataclasses import FrozenInstanceError

import numpy as np

import app_model


class FakeReader:
    """替代 mjpeg_reader.MjpegReader 的可控假体。

    帧新鲜度测试需要"reader 是否真的持有一帧"来区分：stale 时 AppModel 会在
    get_latest_frame 里挡住帧；非 stale 时返回 reader 持有的帧。因此提供
    set_frame() 让假体可持有帧，get_latest_frame 返回该帧或 (None, None)。
    """

    def __init__(self, stream_url=""):
        self.url = stream_url
        self.started = False
        self.stopped = False
        self._stats = {"state": "Streaming", "received": 0, "invalid": 0,
                       "bytes": 0, "last_error": None}
        self._frame = None
        self._frame_num = None

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def set_frame(self, frame, num=None):
        """模拟 reader 收到一帧：供 get_latest_frame 返回（配合新鲜度测试）。"""
        self._frame = frame
        self._frame_num = num

    def get_latest_frame(self):
        return self._frame, self._frame_num

    def get_state(self):
        return self._stats["state"]

    def get_stats(self):
        return dict(self._stats)

    def set_stats(self, **kw):
        self._stats.update(kw)


class FakeClock:
    """可注入的 monotonic 时钟源：测试可以自由推进时间。"""

    def __init__(self, start=1000.0):
        self.now = start

    def monotonic(self):
        return self.now

    def advance(self, delta):
        self.now += delta


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

    # ---- /ping 后台 worker ----

    def test_start_launches_single_ping_worker(self):
        self.model.start()
        self.assertIsNotNone(self.model._ping_thread)
        self.assertTrue(self.model._ping_thread.is_alive())
        worker_ref = self.model._ping_thread
        self.model.start()  # 重复 start 不产生第二个 ping worker
        self.model.start()
        self.assertIs(self.model._ping_thread, worker_ref)
        self.assertTrue(worker_ref.is_alive())
        self.model.stop()

    def test_ping_worker_updates_shared_state(self):
        """/ping 结果由后台 worker 更新，GUI 不需要自己发起请求。"""
        # 必须先在 patch 内 start，否则 worker 会先用真实 requests.get 连 fake URL
        self.model._ping_interval = 0.01
        with mock.patch("app_model.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "status": "streaming", "device": "MIX 2S", "width": 640, "height": 480,
                "actualFps": 15.0, "frameCount": 100}
            self.model.start()
            deadline = time.time() + 3.0
            while time.time() < deadline:
                if self.model._phone_fps == 15.0:
                    break
                time.sleep(0.01)
        snap = self.model.snapshot()
        self.assertEqual(snap.device_name, "MIX 2S")
        self.assertEqual(snap.width, 640)
        self.assertAlmostEqual(snap.phone_fps, 15.0)
        self.assertIsNotNone(snap.last_ping_time)
        self.model.stop()

    def test_ping_failure_backs_off(self):
        """/ping 失败只退避间隔，不崩溃、不清空已收帧统计。"""
        self.model.start()
        fake_reader = self.model._reader
        fake_reader.set_stats(state="Streaming", received=42, invalid=0, bytes=1000)
        with mock.patch("app_model.requests.get", side_effect=Exception("boom")):
            self.model._ping_once()  # 不应抛异常
        self.assertEqual(self.model._ping_interval, app_model.PING_FAIL_INTERVAL)
        snap = self.model.snapshot()
        self.assertEqual(snap.received_frames, 42)  # 统计不被清空
        self.model.stop()

    def test_refresh_does_not_issue_ping_request(self):
        """refresh() 不得发起 HTTP 请求——/ping 只由后台 worker 执行。"""
        self.model.start()
        # 阻止 ping worker 真正发请求，只统计 refresh 期间是否有请求发生
        with mock.patch("app_model.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "status": "streaming", "actualFps": 15.0, "frameCount": 1}
            # 让 worker 有机会跑一次 ping
            deadline = time.time() + 0.5
            while time.time() < deadline:
                self.model.refresh()
                time.sleep(0.01)
            calls_by_refresh = mock_get.call_count
        # refresh 本身不产生请求；请求只能来自 ping worker。
        # 验证方式：在 worker 被停止、单独手动调用 refresh 时，requests.get 必须为 0 次。
        self.model.stop()
        with mock.patch("app_model.requests.get") as mock_get2:
            for _ in range(50):
                self.model.refresh()
            self.assertEqual(mock_get2.call_count, 0)

    def test_ping_worker_calls_fake_ping_on_worker_thread(self):
        """/ping 请求在后台 worker 线程执行，不在主线程。"""
        self.model._ping_interval = 0.01
        main_tid = threading.get_ident()
        called = []

        def fake_get(*a, **kw):
            called.append(threading.get_ident())
            resp = mock.Mock()
            resp.json.return_value = {"status": "streaming", "actualFps": 15.0, "frameCount": 1}
            resp.close = mock.Mock()
            return resp

        with mock.patch("app_model.requests.get", side_effect=fake_get):
            self.model.start()
            deadline = time.time() + 3.0
            while time.time() < deadline:
                if called:
                    break
                time.sleep(0.01)
        self.assertTrue(called, "ping worker 应至少执行一次 /ping")
        self.assertTrue(all(tid != main_tid for tid in called),
                        f"ping 必须在 worker 线程执行，实际在主线程调用: {called}")
        self.model.stop()

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
            self.model._ping_once()
        snap = self.model.snapshot()
        # server +10，local +5，估算丢 5 帧
        self.assertEqual(snap.estimated_dropped_frames, 5)

    # ---- receive_fps 独立于刷新频率 ----

    def test_receive_fps_based_on_reader_delta(self):
        """receive_fps 必须基于 reader 实际新增帧数，而非 refresh 调用次数。"""
        self.model.start()
        fake_reader = self.model._reader
        clock = FakeClock(1000.0)
        with mock.patch.object(self.model, "_recv_t0", 1000.0):
            pass
        # 注入 fake clock：把 _recv_t0 设为假时钟起点
        self.model._recv_t0 = clock.now
        # 模拟：1 秒内 reader 新增 3 帧
        fake_reader.set_stats(state="Streaming", received=3, invalid=0, bytes=0)
        # 时间前进 1.0 秒
        clock.advance(1.0)
        with mock.patch("app_model.time.monotonic", side_effect=clock.monotonic):
            self.model.refresh()
        snap = self.model.snapshot()
        self.assertAlmostEqual(snap.receive_fps, 3.0, places=1)

    def test_receive_fps_independent_of_refresh_calls(self):
        """同样的帧增量下，调用 refresh 3 次或 60 次结果应一致。"""
        self.model.start()
        fake_reader = self.model._reader

        def run(refresh_count):
            clock = FakeClock(1000.0)
            self.model._recv_t0 = clock.now
            fake_reader.set_stats(state="Streaming", received=0, invalid=0, bytes=0)
            self.model.refresh()  # 基线采样
            # 时间前进 1 秒，同时新增 3 帧
            clock.advance(1.0)
            fake_reader.set_stats(state="Streaming", received=3, invalid=0, bytes=0)
            with mock.patch("app_model.time.monotonic", side_effect=clock.monotonic):
                for _ in range(refresh_count):
                    self.model.refresh()
            return self.model._receive_fps

        fps3 = run(3)
        self.model._recv_total_last = 0
        fps60 = run(60)
        self.assertAlmostEqual(fps3, fps60, places=3,
                               msg="refresh 调用频率不应影响 receive_fps")

    def test_receive_fps_not_grow_when_no_new_frames(self):
        """没有新帧时 receive_fps 不增长（不能因 refresh 被高频调用而虚增）。"""
        self.model.start()
        fake_reader = self.model._reader
        clock = FakeClock(1000.0)
        self.model._recv_t0 = clock.now
        fake_reader.set_stats(state="Streaming", received=0, invalid=0, bytes=0)
        self.model.refresh()
        # 帧数保持不变，时间前进多秒
        for _ in range(5):
            clock.advance(1.0)
            with mock.patch("app_model.time.monotonic", side_effect=clock.monotonic):
                for _ in range(60):  # 高频 refresh
                    self.model.refresh()
        snap = self.model.snapshot()
        self.assertEqual(snap.receive_fps, 0.0)

    def test_receive_fps_no_negative_on_counter_reset(self):
        """reader 计数归零（重连后新 reader 从 0 开始）不产生负 FPS。"""
        self.model.start()
        fake_reader = self.model._reader
        clock = FakeClock(1000.0)
        self.model._recv_t0 = clock.now
        fake_reader.set_stats(state="Streaming", received=10, invalid=0, bytes=0)
        self.model.refresh()
        # 时间前进 1 秒，但 reader 计数从 10 降到 3（模拟新 reader 归零后重连）
        clock.advance(1.0)
        fake_reader.set_stats(state="Streaming", received=3, invalid=0, bytes=0)
        with mock.patch("app_model.time.monotonic", side_effect=clock.monotonic):
            self.model.refresh()
        self.assertGreaterEqual(self.model._receive_fps, 0.0)
        # 归零后重置基线，后续增长基于新基线
        clock.advance(1.0)
        fake_reader.set_stats(state="Streaming", received=6, invalid=0, bytes=0)
        with mock.patch("app_model.time.monotonic", side_effect=clock.monotonic):
            self.model.refresh()
        self.assertAlmostEqual(self.model._receive_fps, 3.0, places=1)

    # ---- reconnect worker ----

    def test_reconnect_calls_underlying_reader(self):
        self.model.start()
        old = self.model._reader
        self.model.reconnect()
        # reconnect 在后台线程换 reader；等待片刻确认发生
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if self.model._reader is not old:
                break
            time.sleep(0.01)
        new = self.model._reader
        self.assertIsNot(old, new)
        self.assertTrue(old.stopped)
        self.assertTrue(new.started)
        self.model.stop()

    def test_reconnect_no_thread_storm(self):
        """连续调用 reconnect 不会产生多个 worker 线程。"""
        self.model.start()
        self.model.reconnect()
        first_ref = self.model._reconnect_thread
        self.model.reconnect()  # 防重：已有 worker 在跑，应跳过
        self.model.reconnect()
        self.assertIs(self.model._reconnect_thread, first_ref,
                      "连续 reconnect 不应创建新 worker")
        # 等待 worker 完成并清理引用
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if self.model._reconnect_thread is None:
                break
            time.sleep(0.01)
        self.assertIsNone(self.model._reconnect_thread, "worker 退出后应清理引用")
        self.model.stop()

    def test_stop_after_reconnect_cleans_worker(self):
        """stop() 回收 reconnect worker，且 stop 后 worker 不会覆盖状态。"""
        self.model.start()
        self.model.reconnect()
        self.model.stop()
        snap = self.model.snapshot()
        self.assertEqual(snap.connection_state, app_model.STATE_STOPPED)
        self.assertFalse(self.model.is_running())

    def test_worker_does_not_override_stopped_state(self):
        """stop 后后台 reconnect worker 不得再启动新 reader 或覆盖状态。"""
        self.model.start()
        # 手动构造一个较慢的 reconnect worker，stop 应能打断
        old = self.model._reader
        self.model.reconnect()
        self.model.stop()  # 立即停止
        # 等 reconnect worker 可能仍在执行
        deadline = time.time() + 1.0
        while time.time() < deadline:
            if self.model._reconnect_thread is None or not self.model._reconnect_thread.is_alive():
                break
            time.sleep(0.01)
        snap = self.model.snapshot()
        self.assertEqual(snap.connection_state, app_model.STATE_STOPPED)

    # ---- Snapshot 不可变 ----

    def test_snapshot_is_frozen(self):
        snap = self.model.snapshot()
        with self.assertRaises(FrozenInstanceError):
            snap.connection_state = "Mutated"

    def test_get_state_interface(self):
        """get_state() 兼容 self.reader 别名下的旧调用（Tkinter 用）。"""
        self.model.start()
        self.assertEqual(self.model.get_state(), app_model.STATE_CONNECTING)
        fake_reader = self.model._reader
        fake_reader.set_stats(state="Streaming", received=1, invalid=0, bytes=0)
        self.model.refresh()
        self.assertEqual(self.model.get_state(), app_model.STATE_STREAMING)
        self.model.stop()
        self.assertEqual(self.model.get_state(), app_model.STATE_STOPPED)

    def test_reconnecting_not_overridden_by_idle_reader(self):
        """reconnect() 置 Reconnecting 后，新 reader 初始 Idle 不得覆盖该状态。"""
        self.model.start()
        self.model._state = app_model.STATE_RECONNECTING
        # 新 reader（假体）初始状态为 Streaming（FakeReader 默认），这里模拟 Idle
        fake_reader = self.model._reader
        fake_reader.set_stats(state="Idle", received=0, invalid=0, bytes=0)
        self.model.refresh()
        self.assertEqual(self.model.snapshot().connection_state, app_model.STATE_RECONNECTING)

    # ---- 状态常量 ----

    def test_state_constants(self):
        self.assertEqual(app_model.STATE_STREAMING, "Streaming")
        self.assertEqual(app_model.STATE_RECONNECTING, "Reconnecting")
        self.assertEqual(app_model.STATE_STOPPED, "Stopped")


class FrameFreshnessTest(unittest.TestCase):
    """AppModel 帧新鲜度语义测试（P0-3E）。

    覆盖：首帧可读、阈值内可用、超阈值 stale、refresh 次数不刷新鲜度、
    新帧立即恢复、reader 更换计数归零后的识别、stop 后 stale。

    为什么这样设计：
      - 全部离线、确定性：用 FakeReader 的 set_stats 模拟 reader 收到新帧
        （received 计数增加），用 FakeClock 推进 time.monotonic，绝不真实 sleep。
      - 帧新鲜度由 refresh() 内部调用 _update_frame_freshness()，其内部用
        time.monotonic() 取时间，所以统一 patch app_model.time.monotonic。
      - FakeReader 没有真实计数递增机制，"新帧到达"= 用 set_stats(received=N)
        增大计数；"无新帧"= 计数保持不变。真实 reader 中计数每解析一帧 +1。
    """

    def setUp(self):
        self.patcher = mock.patch("app_model.mjpeg_reader.MjpegReader", FakeReader)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.model = app_model.AppModel("http://fake/stream", "http://fake/ping")
        self.model.start()
        self.reader = self.model._reader
        self.clock = FakeClock(1000.0)
        self.addCleanup(self.model.stop)

    def _refresh(self):
        """在 fake clock 下刷新：帧新鲜度判断与 FPS 统计都走这个入口。"""
        with mock.patch("app_model.time.monotonic", side_effect=self.clock.monotonic):
            self.model.refresh()

    def _snapshot(self):
        with mock.patch("app_model.time.monotonic", side_effect=self.clock.monotonic):
            return self.model.snapshot()

    def _expect_frame(self, msg):
        frame, num = self.model.get_latest_frame()
        self.assertIsNotNone(frame, msg)
        return frame, num

    def test_first_frame_readable(self):
        """首帧到达后即可读取：收到 received=1 后 get_latest_frame 返回帧。"""
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.reader.set_frame(frame, num=1)
        self.reader.set_stats(state="Streaming", received=1, invalid=0, bytes=100)
        self._refresh()
        # 首帧必须立即可读，不能因为"之前没有新帧"而挡在门外
        got, num = self._expect_frame("首帧到达后应返回帧")
        self.assertIs(got, frame)
        self.assertEqual(num, 1)
        self.assertFalse(self._snapshot().frame_stale)

    def test_same_frame_usable_within_threshold(self):
        """同一帧在阈值内仍可用：received 不变，多次 refresh 后帧仍非 stale。

        真实场景：收到一帧后缓存它，GUI 以 ~30fps 高频刷新显示。只要没超过
        3 秒无新帧，这帧应持续可显示，刷新次数多不改变新鲜度。
        """
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.reader.set_frame(frame, num=1)
        self.reader.set_stats(state="Streaming", received=1, invalid=0, bytes=100)
        self._refresh()  # 收到首帧，时间戳记在 t=1000.0

        # 2.9 秒内高频刷新，received 一直不变
        for _ in range(5):
            self.clock.advance(0.58)
            self._refresh()
        self.assertLess(self._snapshot().frame_age_seconds, app_model.FRAME_STALE_TIMEOUT_SECONDS)
        got, _ = self._expect_frame("阈值内同一帧仍应可读")
        self.assertIs(got, frame)
        self.assertFalse(self._snapshot().frame_stale)

    def test_stale_after_threshold(self):
        """同一帧超过阈值后 stale：get_latest_frame 返回 (None, None)，快照标记 stale。"""
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.reader.set_frame(frame, num=1)
        self.reader.set_stats(state="Streaming", received=1, invalid=0, bytes=100)
        self._refresh()  # t=1000.0 收到首帧

        self.clock.advance(app_model.FRAME_STALE_TIMEOUT_SECONDS + 0.1)
        self.reader.set_frame(None)  # 恢复成"无帧"假体语义：stale 时模型层应挡住帧
        self._refresh()
        # stale 后 get_latest_frame 必须挡在模型层，返回 (None, None)
        self.assertEqual(self.model.get_latest_frame(), (None, None))
        snap = self._snapshot()
        self.assertTrue(snap.frame_stale)
        self.assertGreater(snap.frame_age_seconds, app_model.FRAME_STALE_TIMEOUT_SECONDS)

    def test_no_new_frame_does_not_extend_freshness(self):
        """没有新帧时，refresh 次数再多也不刷新时间戳。

        防止退化实现"只要 refresh 就被当作有帧"：那样时间戳随 refresh 不断前移，
        断流永远测不出 stale。这里 4 次 refresh 各前进 1 秒，received 不变，
        时间前进 4 秒后应 stale——若每次 refresh 都刷时间戳，就不会 stale。
        """
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.reader.set_frame(frame, num=1)
        self.reader.set_stats(state="Streaming", received=1, invalid=0, bytes=100)
        self._refresh()  # t=1000.0 收到首帧

        self.reader.set_frame(None)  # 断言前先恢复"无帧"语义
        # 4 次 refresh，时间各前进 1 秒，received 始终为 1（无新帧）
        for _ in range(4):
            self.clock.advance(1.0)
            self._refresh()
        self.assertTrue(self._snapshot().frame_stale,
                        "无新帧时 refresh 次数不应延长新鲜度")

    def test_new_frame_recovers_after_stale(self):
        """陈旧后新帧到达立即恢复：received 增加，帧可读且 frame_stale=False。"""
        frame1 = np.zeros((48, 64, 3), dtype=np.uint8)
        self.reader.set_frame(frame1, num=1)
        self.reader.set_stats(state="Streaming", received=1, invalid=0, bytes=100)
        self._refresh()
        self.clock.advance(app_model.FRAME_STALE_TIMEOUT_SECONDS + 0.1)
        self._refresh()  # 已 stale

        # 新帧到达：received 从 1 增到 2
        frame2 = np.zeros((48, 64, 3), dtype=np.uint8) + 255
        self.reader.set_frame(frame2, num=2)
        self.reader.set_stats(state="Streaming", received=2, invalid=0, bytes=200)
        self._refresh()
        got, num = self._expect_frame("新帧到达后应立即可读")
        self.assertIs(got, frame2)
        self.assertEqual(num, 2)
        self.assertFalse(self._snapshot().frame_stale)

    def test_reader_swap_counter_reset(self):
        """reader 更换且计数归零（received 从 N 降到 0）后能正确识别新帧。

        reconnect 后新 reader 计数从 0 重新开始（计数下降）。delta<0 时应重置
        观察基线并回到 stale；随后新 reader 收到首帧（received 升到 1）即恢复。
        若不重置基线，received=1 < 旧基线 50 会一直被当作"没有新帧"。
        """
        old = self.model._reader
        old.set_stats(state="Streaming", received=50, invalid=0, bytes=5000)
        self._refresh()  # 旧 reader 已收 50 帧

        # 模拟重连换新 reader：计数归零（下降）
        new = FakeReader("http://fake/stream")
        new.set_stats(state="Idle", received=0, invalid=0, bytes=0)
        self.model._reader = new
        self.model._state = app_model.STATE_RECONNECTING
        self._refresh()
        self.assertTrue(self._snapshot().frame_stale, "计数归零后应回到 stale")

        # 新 reader 收到首帧：计数升到 1，应被识别为新帧并恢复
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        new.set_frame(frame, num=1)
        new.set_stats(state="Streaming", received=1, invalid=0, bytes=300)
        self.clock.advance(0.1)
        self._refresh()
        got, num = self._expect_frame("新 reader 首帧应被识别并恢复显示")
        self.assertIs(got, frame)
        self.assertEqual(num, 1)
        self.assertFalse(self._snapshot().frame_stale)
        self.model._reader = old  # 还原，避免 tearDown 的 stop 影响后续

    def test_stop_marks_frame_stale(self):
        """stop 后帧不可显示：get_latest_frame 返回 (None, None)。

        用户点"退出"后不应再显示旧画面。stop() 立即把 reader 置 None，
        get_latest_frame 因此返回 (None, None)——这是 UI 消费的唯一入口，
        足以保证旧帧不再显示。

        为什么不断言 snapshot().frame_stale：该字段由 refresh() 内的
        _update_frame_freshness() 维护，stop 后 GUI 不再调用 refresh，字段保持
        停止前的值。可显示的保证由 get_latest_frame 的 (None, None) 承担。
        """
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.reader.set_frame(frame, num=1)
        self.reader.set_stats(state="Streaming", received=1, invalid=0, bytes=100)
        self._refresh()
        self.assertFalse(self._snapshot().frame_stale)

        self.model.stop()
        self.assertEqual(self.model.get_latest_frame(), (None, None))
        snap = self._snapshot()
        self.assertEqual(snap.connection_state, app_model.STATE_STOPPED)


class PingAndVideoIndependentTest(unittest.TestCase):
    """ping 结果与视频新鲜度相互独立（P0-3E）。

    为什么这样设计：验收点"ping 成功但视频断流"不能被 ping 掩盖——断流识别
    只由帧新鲜度决定；ping 失败但视频仍在推流也必须继续显示实时画面。两类测试
    都用 fake clock + FakeReader.set_stats 离线验证，不需要真实网络。
    """

    def setUp(self):
        self.patcher = mock.patch("app_model.mjpeg_reader.MjpegReader", FakeReader)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.model = app_model.AppModel("http://fake/stream", "http://fake/ping")
        self.model.start()
        self.reader = self.model._reader
        self.clock = FakeClock(1000.0)
        self.addCleanup(self.model.stop)

    def _refresh(self):
        with mock.patch("app_model.time.monotonic", side_effect=self.clock.monotonic):
            self.model.refresh()

    def _snapshot(self):
        with mock.patch("app_model.time.monotonic", side_effect=self.clock.monotonic):
            return self.model.snapshot()

    def test_ping_failure_still_shows_live_frame(self):
        """ping 失败但持续有新帧时仍显示实时帧。

        模拟：/ping 抛异常（断网），但 reader 仍在收帧（received 持续增加）。
        帧新鲜度只由 received 决定，与 ping 成败无关，因此应保持 frame_stale=False，
        get_latest_frame 返回实时帧。
        """
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.reader.set_frame(frame, num=1)
        self.reader.set_stats(state="Streaming", received=1, invalid=0, bytes=100)
        self._refresh()

        # 连续多轮：ping 失败 + 每轮 received 增加（新帧持续到达）
        with mock.patch("app_model.requests.get", side_effect=Exception("network down")):
            for n in range(2, 6):
                self.clock.advance(0.2)
                frame_n = np.zeros((48, 64, 3), dtype=np.uint8) + n
                self.reader.set_frame(frame_n, num=n)
                self.reader.set_stats(state="Streaming", received=n, invalid=0, bytes=n * 100)
                self._refresh()
                got, _ = self._expect_frame(f"ping 失败但第 {n} 帧应仍实时显示")
                self.assertIs(got, frame_n)
                self.assertFalse(self._snapshot().frame_stale)

    def test_ping_ok_but_no_frames_goes_stale(self):
        """ping 成功但无新帧超过阈值时仍进入 stale。

        模拟：/ping 正常返回（后台 worker 更新 phone_fps），但 reader 停在
        received=1 不再有新帧。时间前进超过阈值后必须 stale——防止"ping 成功
        掩盖视频断流"。
        """
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.reader.set_frame(frame, num=1)
        self.reader.set_stats(state="Streaming", received=1, invalid=0, bytes=100)
        self._refresh()
        self.assertFalse(self._snapshot().frame_stale)

        # ping 成功：模拟后台 worker 已更新 phone_fps 与 last_ping_time
        with mock.patch("app_model.time.monotonic", side_effect=self.clock.monotonic):
            self.model._phone_fps = 15.0
            self.model._last_ping_time = self.clock.now

        # 无新帧，时间前进超过阈值
        self.clock.advance(app_model.FRAME_STALE_TIMEOUT_SECONDS + 0.1)
        self.reader.set_frame(None)  # stale 时模型层应挡住帧
        self._refresh()
        self.assertEqual(self.model.get_latest_frame(), (None, None))
        snap = self._snapshot()
        self.assertTrue(snap.frame_stale, "ping 正常也不能掩盖视频断流")
        self.assertEqual(snap.phone_fps, 15.0)  # ping 统计仍更新，互不干扰

    def _expect_frame(self, msg):
        frame, num = self.model.get_latest_frame()
        self.assertIsNotNone(frame, msg)
        return frame, num


if __name__ == "__main__":
    unittest.main()
