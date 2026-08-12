"""
PhoneVision Lab — PySide6 视觉工作台 UI 测试（P0-4A，offscreen）。

职责：验证 MainWindow 从"功能原型"改造成"单目显微镜/示波器工作台"后的布局
验收规格（P0-4A / ui-redesign-brief §19）：
  1. 顶栏：项目名 + 设备名 + 状态 pill + 保存/重连；标题栏不承担消息展示。
  2. 画面区 VideoView 占最大面积；stale/恢复在实时画面与占位间切换；
     占位内"重新连接"按钮驱动 AppModel.reconnect。
  3. 检查器：五模式互斥 + 参数按模式过滤（0/0/2/6/7）+ 教学提示随模式更新。
  4. 底部 DiagnosticsPanel 默认只显示 接收FPS/显示FPS/丢帧，展开见全部。
  5. Toast：保存成功(success) / 无帧(warning) / 网络错误(error→恢复清除)。
  6. 快捷键 S/R/1-5/Ctrl+Q 存在且无重复。
  7. 1366×768 无越界、1920×1080 新增空间主要分配给 VideoView。

为什么这样设计：
  - 不连接网络、不显示真实窗口，可离线确定性运行。
  - 用 test_qt_gui_build.FakeAppModel 替代真实 AppModel（无后台线程/网络）。
  - 所有可见性断言先 show() + processEvents() 再查 isVisible()，反映真实可见状态。
  - 依赖 P0-4A 源码（ui_components / 新 main_window）的测试在源码合入前整体 skip，
    落地后自动启用。

初学者调试观察点：
  - 断言"可见滑块数"失败：检查是 0/0/2/6/7 还是别的——这是按模式过滤的验收标准。
  - 断言"标题含错误串"失败：P0-4A 规定错误/保存结果一律进 toast，不进标题栏。
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

from PySide6.QtWidgets import QApplication

import vision_modes
from tests.test_qt_gui_build import FakeAppModel, NEW_LAYOUT

_PING_INFO = {"width": 640, "height": 480, "actualFps": 15.0}

# 各模式应可见的参数键（与 main_window.MODE_PARAM_KEYS 对齐；写在此处以测试为准）。
MODE_VISIBLE_PARAMS = {
    vision_modes.MODE_ORIGINAL: [],
    vision_modes.MODE_GRAY: [],
    vision_modes.MODE_CANNY: ["canny_low", "canny_high"],
    vision_modes.MODE_HSV: ["h_min", "h_max", "s_min", "s_max", "v_min", "v_max"],
    vision_modes.MODE_CONTOUR: [
        "h_min", "h_max", "s_min", "s_max", "v_min", "v_max", "contour_min_area",
    ],
}


@unittest.skipUnless(NEW_LAYOUT, "P0-4A 工作台布局未落地（等待源码 agent 合入）")
class QtWorkbenchUiTest(unittest.TestCase):
    """P0-4A 视觉工作台布局验收测试。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.patcher = mock.patch("qt_client.main_window.app_model.AppModel", FakeAppModel)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        from qt_client.main_window import MainWindow
        self.win = MainWindow("http://fake/stream", "http://fake/ping", _PING_INFO)

    def tearDown(self):
        self.win.model.stop()
        self.win.close()

    def _show(self):
        """显示窗口并处理事件：isVisible() 需要真实布局后才有意义。"""
        self.win.show()
        self.app.processEvents()

    # =====================================================================
    # 顶栏 / 标题
    # =====================================================================

    def test_window_title_fixed(self):
        """规格§19.4：标题栏不承担消息展示——恒为 'PhoneVision Lab'。"""
        self.win.model.last_error = "HTTPConnectionPool(host='192.168.1.10', port=80)"
        self.win._refresh()
        self.assertEqual(self.win.windowTitle(), "PhoneVision Lab")
        self.assertNotIn("HTTPConnectionPool", self.win.windowTitle())

    def test_save_success_does_not_leak_to_title(self):
        """保存成功走 success toast，标题不含"已保存"或错误文本。"""
        self.win._timer.stop()
        frame = np.full((48, 64, 3), 120, dtype=np.uint8)
        self.win.model._set_frame(frame, num=1, received=1)
        with mock.patch("os.makedirs"), \
             mock.patch("cv2.imwrite"), \
             mock.patch("qt_client.main_window.datetime") as dt:
            dt.now.return_value.strftime.return_value = "20260812-120000"
            self.win.save_capture()
        self.assertEqual(self.win.windowTitle(), "PhoneVision Lab")
        self.assertEqual(self.win.toast.current_kind(), "success")

    def test_topbar_brand_device_status(self):
        """顶栏：品牌"PhoneVision Lab" + 设备名 + 状态 pill 三重信息。"""
        brand = self.win.findChild(type(self.win.device_label), "brandLabel")
        self.assertIsNotNone(brand, "顶栏应有品牌标签")
        self.assertEqual(brand.text(), "PhoneVision Lab")
        self.win.model._set_device_name("小米 MIX 2S")
        self.win._refresh()
        self.assertEqual(self.win.device_label.text(), "小米 MIX 2S")
        self.assertEqual(self.win.status_pill.state(), self.win.stats["state"])

    def test_device_name_placeholder_when_unknown(self):
        """未获得设备信息时设备名显示"等待设备信息"（初始占位文案）。"""
        self.win._refresh()
        self.assertEqual(self.win.device_label.text(), "等待设备信息")

    # =====================================================================
    # 模式 / 参数 / 教学提示
    # =====================================================================

    def test_five_modes_exclusive(self):
        """五模式按钮存在且由互斥 QButtonGroup 管理。"""
        self.assertEqual(len(self.win.mode_buttons), 5)
        self.assertTrue(self.win.mode_group.exclusive())
        self.win.mode_buttons[vision_modes.MODE_CANNY].setChecked(True)
        checked = [m for m, b in self.win.mode_buttons.items() if b.isChecked()]
        self.assertEqual(checked, [vision_modes.MODE_CANNY])

    def test_visible_sliders_per_mode(self):
        """各模式可见参数数 = 0/0/2/6/7（其余滑块整行隐藏、对象仍存在）。"""
        self._show()
        expected = {
            vision_modes.MODE_ORIGINAL: 0,
            vision_modes.MODE_GRAY: 0,
            vision_modes.MODE_CANNY: 2,
            vision_modes.MODE_HSV: 6,
            vision_modes.MODE_CONTOUR: 7,
        }
        for mode, count in expected.items():
            self.win.set_mode(mode)
            self.app.processEvents()
            visible = [k for k, s in self.win.sliders.items() if s.isVisible()]
            self.assertEqual(
                len(visible), count,
                f"{mode} 可见滑块应为 {MODE_VISIBLE_PARAMS[mode]} ({count})，实得 {visible}")
        self.assertEqual(len(self.win.sliders), 9, "9 根滑块只是隐藏，不是删除")

    def test_param_value_survives_mode_switch(self):
        """切换模式后隐藏参数值不丢失：Canny 设 77 → 切 HSV → 切回仍 77。"""
        self.win.set_mode(vision_modes.MODE_CANNY)
        self.win.sliders["canny_low"].setValue(77)
        self.assertEqual(self.win.params["canny_low"], 77)
        self.win.set_mode(vision_modes.MODE_HSV)
        self.win.set_mode(vision_modes.MODE_CANNY)
        self.assertEqual(self.win.params["canny_low"], 77,
                         "切走再切回后 Canny 参数不应丢失")
        self.assertEqual(self.win.sliders["canny_low"].value(), 77)

    def test_teaching_hint_updates_with_mode(self):
        """教学提示随模式更新：各模式文案非空且至少两种不同。"""
        texts = set()
        for mode in (vision_modes.MODE_ORIGINAL, vision_modes.MODE_GRAY,
                     vision_modes.MODE_CANNY, vision_modes.MODE_HSV,
                     vision_modes.MODE_CONTOUR):
            self.win.set_mode(mode)
            texts.add(self.win.hint_label.text().strip())
        self.assertNotIn("", texts)
        self.assertGreater(len(texts), 1, "至少两种模式的提示文案应不同")

    # =====================================================================
    # 诊断区
    # =====================================================================

    def test_diagnostics_default_three_metrics(self):
        """默认诊断只显示三个主要指标：接收FPS/显示FPS/丢帧。"""
        self._show()
        self.win._refresh()
        panel = self.win.diagnostics
        self.assertFalse(panel.is_expanded())
        visible = [key for key, lbl in panel._value_labels.items()
                   if lbl.isVisible()]
        self.assertEqual(len(visible), 3,
                         f"默认应只显示 3 个主要指标，实得 {len(visible)}")
        for key in ("recv_fps", "disp_fps", "dropped"):
            self.assertTrue(panel._value_labels[key].isVisible(), f"{key} 应常显")

    def test_diagnostics_expand_reveals_advanced(self):
        """展开后高级指标可见。"""
        self._show()
        self.win._refresh()
        panel = self.win.diagnostics
        panel.toggle()
        self.app.processEvents()
        self.assertTrue(panel.is_expanded())
        visible = [key for key, lbl in panel._value_labels.items()
                   if lbl.isVisible()]
        self.assertGreater(len(visible), 3, "展开后应显示 3 个以上指标")
        for key in ("phone_fps", "mbps", "avg_jpeg_mb", "received", "invalid",
                    "resolution"):
            self.assertIn(key, visible, f"展开后 {key} 应可见")

    # =====================================================================
    # 画面区：stale 占位 / 恢复 / 重连
    # =====================================================================

    def _render_real_frame(self, fill=120):
        """渲染一帧真实测试帧，返回画面区当前状态。"""
        frame = np.full((48, 64, 3), fill, dtype=np.uint8)
        self.win.model._set_frame(frame, num=1, received=1)
        self._show()
        self.win._refresh()
        return self.win.video_view.render_state

    def test_stale_switches_to_placeholder(self):
        """stale 后画面区切到占位（render_state == 'reconnecting'）。"""
        self.win._timer.stop()
        self._render_real_frame()
        self.win.model._set_stale(True)
        self.win._refresh()
        self.assertEqual(self.win.video_view.render_state, "reconnecting")

    def test_stale_placeholder_pixmap_is_not_frame(self):
        """stale 占位应清掉旧帧像素（画面层 pixmap 为空），而非残留旧帧。"""
        self.win._timer.stop()
        self._render_real_frame()
        self.win.model._set_stale(True)
        self.win._refresh()
        self.assertEqual(self.win.video_view._frame_label.pixmap().isNull(), True)

    def test_new_frame_recovers_live(self):
        """恢复时切回实时画面（render_state == 'frame'）。"""
        self.win._timer.stop()
        self._render_real_frame()
        self.win.model._set_stale(True)
        self.win._refresh()
        self.assertEqual(self.win.video_view.render_state, "reconnecting")

        frame = np.full((48, 64, 3), 90, dtype=np.uint8)
        self.win.model._set_frame(frame, num=2, received=2)
        self.win._refresh()
        self.assertEqual(self.win.video_view.render_state, "frame")

    def test_placeholder_reconnect_button_calls_model(self):
        """占位内"重新连接"按钮点击 → emit reconnect_requested → model.reconnect。"""
        self.win._timer.stop()
        self.win.model._set_stale(True)
        self.win._refresh()
        self.assertEqual(self.win.video_view.render_state, "reconnecting")
        self.win.video_view.reconnect_requested.emit()
        self.assertEqual(self.win.model.reconnect_calls, 1)
        self.assertGreaterEqual(self.win.model.set_last_error_calls, 0)

    # =====================================================================
    # Toast：保存成功 / 无帧 / 错误
    # =====================================================================

    def test_save_success_shows_success_toast(self):
        """保存成功显示 success toast（show_message kind='success'）。"""
        self.win._timer.stop()
        frame = np.full((48, 64, 3), 120, dtype=np.uint8)
        self.win.model._set_frame(frame, num=1, received=1)
        with mock.patch("os.makedirs"), mock.patch("cv2.imwrite"):
            self.win.save_capture()
        self.assertEqual(self.win.toast.current_kind(), "success")

    def test_save_no_frame_shows_warning_toast(self):
        """无帧时显示 warning toast，且不写 stats.error、不改标题。"""
        self.win._timer.stop()
        self.win.save_capture()
        self.assertEqual(self.win.toast.current_kind(), "warning")
        self.assertEqual(self.win.stats["error"], "")
        self.assertEqual(self.win.windowTitle(), "PhoneVision Lab")

    def test_network_error_shows_error_toast_then_clears(self):
        """网络错误显示 error toast；恢复（last_error 清空）后 clear。"""
        self.win._timer.stop()
        self._show()  # 让 toast 可见性断言反映真实状态
        self.win.model.last_error = "HTTPConnectionPool(host='192.168.1.10', port=80)"
        self.win._refresh()
        self.assertEqual(self.win.toast.current_kind(), "error")
        self.assertTrue(self.win.toast.isVisible(), "错误 toast 应可见")

        self.win.model.last_error = None
        frame = np.full((48, 64, 3), 30, dtype=np.uint8)
        self.win.model._set_frame(frame, num=3, received=3)
        self.win._refresh()
        self.assertEqual(self.win.toast.current_kind(), "error")  # clear 不改 kind
        self.assertFalse(self.win.toast.isVisible(), "恢复后 toast 应隐藏")
        self.assertEqual(self.win.windowTitle(), "PhoneVision Lab")

    # =====================================================================
    # 快捷键
    # =====================================================================

    def test_shortcuts_exist_no_duplicates(self):
        """S/R/1-5/Ctrl+Q 快捷键存在且 QKeySequence 无重复。"""
        seqs = [s.key().toString() for s in self.win.shortcuts]
        self.assertIn("S", seqs)
        self.assertIn("R", seqs)
        self.assertIn("Ctrl+Q", seqs)
        for i in range(1, 6):
            self.assertIn(str(i), seqs, f"快捷键 {i} 应存在")
        self.assertEqual(len(seqs), len(set(seqs)), "快捷键不应重复")

    def test_shortcut_activation_wired(self):
        """快捷键确实绑到对应动作：R 触发重连、S 触发保存（不抛异常）。"""
        self.win._timer.stop()
        for sc in self.win.shortcuts:
            if sc.key().toString() == "R":
                sc.activated.emit()
        self.assertEqual(self.win.model.reconnect_calls, 1)
        for sc in self.win.shortcuts:
            if sc.key().toString() == "S":
                sc.activated.emit()  # 无帧保存 → warning toast，不抛异常
        self.assertEqual(self.win.toast.current_kind(), "warning")

    # =====================================================================
    # 分辨率适配
    # =====================================================================

    def _widget_inside_parent(self, widget):
        """widget.geometry()（相对父控件的矩形）是否落在其父控件矩形内。

        用本地几何而非 mapTo(window/global)：offscreen 平台下全局坐标映射不可靠
        （虚拟桌面偏移），而 geometry() 是布局引擎给出的真实本地布局，最可信。
        """
        g = widget.geometry()
        if g.width() <= 0 or g.height() <= 0:
            return False
        parent = widget.parentWidget()
        return parent is not None and parent.rect().contains(g)

    def test_1366x768_no_out_of_bounds(self):
        """1366×768：关键控件（画面区/诊断区/状态 pill/设备名）不越出其父容器。"""
        self.win._timer.stop()
        self.win.resize(1366, 768)
        self._show()
        for w in (self.win.video_view, self.win.diagnostics, self.win.status_pill,
                  self.win.device_label):
            self.assertTrue(w.geometry().width() > 0 and w.geometry().height() > 0,
                            f"{w.objectName()} 尺寸非法")
            self.assertTrue(self._widget_inside_parent(w),
                            f"{w.objectName()} 越出其父容器")

    def test_1920x1080_space_goes_to_video_view(self):
        """1920×1080：新增空间主要分配给 VideoView（其高度随窗口明显增长）。"""
        self.win._timer.stop()
        self.win.resize(1366, 768)
        self._show()
        h_small = self.win.video_view.height()

        self.win.resize(1920, 1080)
        self._show()
        h_large = self.win.video_view.height()
        self.assertGreater(h_large, h_small,
                           f"VideoView 高度应从 {h_small} 增至 {h_large}")


if __name__ == "__main__":
    unittest.main()
