"""
PhoneVision Lab — PySide6 GUI 构建测试（offscreen，不显示真实窗口）。

职责：在 QT_QPA_PLATFORM=offscreen 下构建 MainWindow，用假 AppModel/AppSnapshot
验证关键控件存在、状态刷新不抛异常、正常关闭。

为什么这样设计：
  - 不连接网络、不显示真实窗口，可离线确定性运行。
  - 用 FakeAppModel 替换真实 AppModel，避免启动后台 reader 线程与真实网络访问。
  - 覆盖 PySide6 客户端"能构建、能刷新、能关闭"的验收基线。
"""
import os
import sys
import unittest
from unittest import mock

# 确保 Qt 用 offscreen 平台（必须在 import PySide6 前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from PySide6.QtWidgets import QApplication

import app_model
from qt_client.main_window import MainWindow


class FakeAppModel:
    """替代 AppModel 的假体：无网络、无后台线程。"""

    def __init__(self, **kw):
        self._started = False

    def start(self):
        self._started = True

    def stop(self):
        pass

    def get_latest_frame(self):
        return None, None

    def get_stats(self):
        return {"state": "Idle", "received": 0, "invalid": 0, "bytes": 0, "last_error": None}

    def get_state(self):
        return "Idle"

    def refresh(self):
        pass

    def mark_frame_displayed(self):
        pass

    def reconnect(self):
        pass

    def set_last_error(self, msg):
        pass

    def snapshot(self):
        return app_model.AppSnapshot(
            connection_state="Idle", device_name="Fake", phone_fps=0.0,
            receive_fps=0.0, display_fps=0.0, width=640, height=480,
            average_jpeg_bytes=0.0, bandwidth_mbps=0.0,
            received_frames=0, invalid_frames=0, estimated_dropped_frames=0,
            last_error=None, last_ping_time=None,
        )


class QtGuiBuildTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.patcher = mock.patch("qt_client.main_window.app_model.AppModel", FakeAppModel)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.win = MainWindow("http://fake/stream", "http://fake/ping",
                              {"width": 640, "height": 480, "actualFps": 15.0})

    def tearDown(self):
        self.win.model.stop()
        self.win.close()

    def test_window_created(self):
        self.assertIsNotNone(self.win)
        self.assertEqual(self.win.windowTitle(), "PhoneVision Lab")

    def test_mode_buttons_exist(self):
        self.assertEqual(len(self.win.mode_buttons), 5)

    def test_sliders_exist(self):
        self.assertEqual(len(self.win.sliders), 9)

    def test_metrics_chips_exist(self):
        # 指标块：状态 + 8 个指标（含 invalid）
        self.assertGreaterEqual(len(self.win.metrics), 8)
        self.assertIn("invalid", self.win.metrics)

    def test_refresh_does_not_raise(self):
        self.win._refresh()  # 不应抛异常
        self.win._update_metrics()
        self.win._refresh()

    def test_set_mode(self):
        self.win.set_mode(app_model.STATE_STREAMING) if False else None
        import vision_modes
        self.win.set_mode(vision_modes.MODE_CANNY)
        self.assertEqual(self.win.mode, vision_modes.MODE_CANNY)


if __name__ == "__main__":
    unittest.main()
