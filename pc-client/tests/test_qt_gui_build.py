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

    def test_placeholder_no_frame_does_not_raise(self):
        """回归：无帧占位分支不再抛 NameError。

        背景：历史 bug 中该分支用 np.zeros 但未 import numpy，_update_frame()
        进入占位分支时抛 `name 'np' is not defined`。注意必须直接调用
        _update_frame() 而不是 _refresh()——后者会把异常吞进 stats["error"]，
        掩盖问题。FakeAppModel.get_latest_frame() 返回 (None, None)，必然走占位分支。
        """
        self.win._timer.stop()  # 停掉 33ms 刷新定时器，保证离线确定性
        # 若 np 未导入，np.zeros 在这里直接抛 NameError，本条即失败
        self.win._update_frame()

    def test_placeholder_pixmap_rendered(self):
        """占位画面成功渲染：_update_frame() 后画面区有 QPixmap。

        若占位分支提前 return 或 _show_frame 未执行，pixmap() 会为 None。
        """
        self.win._timer.stop()
        self.win.show()
        self.app.processEvents()  # 触发布局，让 video_view 拿到真实尺寸
        self.win._update_frame()
        self.assertIsNotNone(self.win.video_view.pixmap())
        self.assertIsNotNone(self.win._qimg)  # _show_frame 已把占位图转为 QImage

    def test_placeholder_no_nameerror_in_ui(self):
        """错误信息不泄漏 'name 'np' is not defined'。

        修复后 np 可用，stats["error"] 保持为空、标题不变；若回归，_refresh()
        的兜底会把 NameError 写进 stats["error"]，标题栏也会带上错误串。
        """
        self.win._timer.stop()
        self.win._update_frame()
        self.assertNotIn("name 'np' is not defined", self.win.windowTitle())
        self.assertNotIn("name 'np' is not defined", self.win.stats["error"])
        # 状态一致性：快照为 Idle，占位文字走"等待画面... 状态: Idle"分支，
        # 统计应同步为 Idle（间接证明走了占位分支而非异常分支）
        self.assertEqual(self.win.stats["state"], "Idle")


if __name__ == "__main__":
    unittest.main()
