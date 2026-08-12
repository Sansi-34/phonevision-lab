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

import numpy as np

# 确保 Qt 用 offscreen 平台（必须在 import PySide6 前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

import app_model
import vision_modes
from qt_client.main_window import MainWindow


class FakeAppModel:
    """替代 AppModel 的假体：无网络、无后台线程。

    P0-3E：增加可配置项，让测试能驱动完整 _refresh() 路径：
      - _set_frame(frame, num, received)：让 get_latest_frame() 返回一帧，
        同时把 received 计数抬高——UI 判断新帧（num 变化）依赖它。
      - _set_stale(True)：让 get_latest_frame() 返回 (None, None) 并标记
        snapshot().frame_stale=True——模拟模型层 stale 挡帧。
      - last_error 可设可清：驱动"错误显示与恢复"路径。
    """

    def __init__(self, **kw):
        self._started = False
        self._frame = None
        self._frame_num = None
        self._received = 0
        self._stale = False
        self.last_error = None
        self._ping_ok = True
        self._phone_fps = 0.0

    def start(self):
        self._started = True

    def stop(self):
        pass

    def _set_frame(self, frame, num, received):
        self._frame = frame
        self._frame_num = num
        self._received = received
        self._stale = False  # 新帧到达即解除 stale

    def _set_stale(self, stale=True):
        self._stale = stale

    def get_latest_frame(self):
        # stale 时模型层返回 (None, None)，UI 走占位分支
        if self._stale:
            return None, None
        return self._frame, self._frame_num

    def get_stats(self):
        return {"state": "Idle", "received": self._received, "invalid": 0,
                "bytes": 0, "last_error": self.last_error}

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

    def _snapshot_kw(self):
        state = "Idle"
        if self._stale:
            state = "Reconnecting"  # 让占位分支显示重连提示，便于断言
        return dict(
            connection_state=state, device_name="Fake", phone_fps=self._phone_fps,
            receive_fps=0.0, display_fps=0.0, width=640, height=480,
            average_jpeg_bytes=0.0, bandwidth_mbps=0.0,
            received_frames=self._received, invalid_frames=0,
            estimated_dropped_frames=0,
            last_error=self.last_error, last_ping_time=None,
            frame_stale=self._stale, frame_age_seconds=0.0,
        )

    def snapshot(self):
        # P0-3E：AppSnapshot 新增 frame_stale / frame_age_seconds 必填字段，
        # 假体构造时必须补上，否则 dataclass 构造抛 TypeError 使所有 Qt 测试崩。
        return app_model.AppSnapshot(**self._snapshot_kw())


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


class QtStaleFrameTest(QtGuiBuildTest):
    """P0-3E：完整 _refresh() 路径下 stale 占位与恢复。

    为什么走完整 _refresh() 而不是单测 _update_frame()：_refresh() 才是真实
    QTimer 回调（model.refresh → _update_frame → _update_metrics），也是
    异常兜底写入 stats["error"] 的入口。要验证"UI 不被陈旧帧卡住、能切到占位、
    新帧能恢复"，就必须走这条真实路径。
    """

    def _render_real_frame(self, fill=120):
        """渲染一帧真实测试帧（BGR），记录此时画面区 Pixmap 的 cacheKey。"""
        frame = np.full((48, 64, 3), fill, dtype=np.uint8)
        self.win.model._set_frame(frame, num=1, received=1)
        self.win.show()
        self.app.processEvents()  # 触发布局，让 video_view 拿到真实尺寸
        self.win._refresh()  # 完整路径：渲染真实帧
        pm = self.win.video_view.pixmap()
        self.assertIsNotNone(pm, "真实帧应渲染出 Pixmap")
        return pm.cacheKey()

    def test_stale_placeholder_replaces_old_frame(self):
        """超过 3 秒无新帧后，完整 _refresh() 应把画面区换成占位图。

        步骤：渲染一帧 → fake clock 前进超过阈值 → reader 仍返回同一缓存帧
        （FakeAppModel.get_latest_frame 不再返回帧以模拟 stale）→ 再 _refresh()。
        """
        self.win._timer.stop()  # 保证离线确定性：手动驱动刷新，不走 33ms 定时器
        key = self._render_real_frame()

        # 模拟超过 stale 阈值：模型层收到"无新帧超时"，get_latest_frame 挡帧。
        # 帧数据始终在 reader 缓存里，但模型层必须拒绝返回它。
        self.win.model._set_stale(True)
        self.win._refresh()  # 完整 _refresh 路径

        pm = self.win.video_view.pixmap()
        self.assertIsNotNone(pm, "占位分支也应渲染出 Pixmap")
        # 占位图是新画出的 Pixmap，cacheKey 必然与旧帧不同
        self.assertNotEqual(pm.cacheKey(), key,
                            "stale 后画面应切换到占位图而不是旧帧")
        # stats 不应残留异常文本
        self.assertEqual(self.win.stats["error"], "")
        self.assertNotIn("Traceback", self.win.windowTitle())

    def test_stale_placeholder_content_text(self):
        """stale 占位画面应绘制"等待/重连"提示文字，而非残留旧帧内容。"""
        self.win._timer.stop()
        self._render_real_frame()
        self.win.model._set_stale(True)
        self.win._refresh()

        # 用像素摘要证明画面内容已变：占位图中心应是文字覆盖区（非纯色填充帧）
        pm = self.win.video_view.pixmap()
        img = pm.toImage().convertToFormat(QImage.Format_RGB888)
        # PySide6 的 bits() 返回 memoryview（无 setsize），直接用 frombuffer 读取
        arr = np.frombuffer(img.bits(), dtype=np.uint8).reshape(img.height(), img.width(), 3)
        # 原帧是纯色 120；占位图有文字和深色底，中心区域像素不应全部等于 120
        center = arr[img.height() // 2 - 5:img.height() // 2 + 5,
                     img.width() // 2 - 5:img.width() // 2 + 5]
        self.assertFalse(
            (center == np.array([120, 120, 120], dtype=np.uint8)).all(),
            "stale 后中心区域应是占位文字而非原纯色帧")

    def test_stale_then_new_frame_recovers(self):
        """stale 占位出现后加入新帧，完整 _refresh() 后占位被新画面替换。"""
        self.win._timer.stop()
        key = self._render_real_frame()

        # 进入 stale 占位
        self.win.model._set_stale(True)
        self.win._refresh()
        placeholder_key = self.win.video_view.pixmap().cacheKey()
        self.assertNotEqual(placeholder_key, key)

        # 新帧到达：received 增加、模型层解除 stale，_refresh 后应显示新帧
        new_frame = np.full((48, 64, 3), 90, dtype=np.uint8)
        self.win.model._set_frame(new_frame, num=2, received=2)
        self.win._refresh()

        pm = self.win.video_view.pixmap()
        self.assertIsNotNone(pm, "新帧应渲染出 Pixmap")
        # 新帧是新画的 Pixmap：既不同于旧帧，也不同于占位图
        self.assertNotEqual(pm.cacheKey(), key, "新帧应替换旧帧画面")
        self.assertNotEqual(pm.cacheKey(), placeholder_key, "新帧应替换占位画面")
        # 原模式不变：模式是 UI 用户状态，stale/恢复不应改变它
        self.assertEqual(self.win.mode, vision_modes.MODE_ORIGINAL, "模式（原始）不变")
        self.assertEqual(self.win._last_frame_num, 2, "UI 帧序号应同步到新帧")
        # 占位时 stats 是 Reconnecting；新帧到达后模型层解除 stale，回到 Idle
        self.assertEqual(self.win.stats["state"], "Idle",
                         "新帧恢复后 stats 状态应回到 Idle（非 Reconnecting 占位）")

    def test_error_then_recovery_clears_ui(self):
        """错误清理：第一次 snapshot 含错误 → UI 显示；恢复且 last_error 空 → 恢复正常。

        覆盖"不残留旧字符串"：标题从 'PhoneVision Lab — HTTPConnectionPool…'
        回到 'PhoneVision Lab'，stats["error"] 也被清空。
        """
        self.win._timer.stop()
        import vision_modes
        self.win.set_mode(vision_modes.MODE_CANNY)  # 验证模式不受错误清理影响
        self.win.model.last_error = "HTTPConnectionPool(host='192.168.1.10', port=80)"
        self.win._refresh()
        self.assertIn("HTTPConnectionPool", self.win.windowTitle())
        self.assertEqual(self.win.stats["error"], self.win.model.last_error)

        # 连接恢复：模型清空 last_error 并收到新帧（错误清理正是发生在"有新事件
        # 触发 _update_frame"时）。若只把 last_error 置 None 而不推新帧，
        # _update_frame 因帧号未变而跳过同步，残留断言会误判实现错误。
        self.win.model.last_error = None
        frame = np.full((48, 64, 3), 30, dtype=np.uint8)
        self.win.model._set_frame(frame, num=3, received=3)
        self.win._refresh()
        self.assertEqual(self.win.stats["error"], "", "错误恢复后 stats 不应残留")
        self.assertEqual(self.win.windowTitle(), "PhoneVision Lab",
                         "错误恢复后标题不应残留旧错误串")


if __name__ == "__main__":
    unittest.main()
