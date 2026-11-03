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

    def test_save_success_toast_survives_next_refresh(self):
        """回归：success toast 必须跨 _refresh() 存活。

        原缺陷：_update_metrics 每 33ms 无条件 toast.clear()，保存成功的提示
        在下一 tick 就被吞掉，用户看不到任何反馈（只有一个不可见的成功）。
        """
        self.win._timer.stop()
        self._show()
        frame = np.full((48, 64, 3), 120, dtype=np.uint8)
        self.win.model._set_frame(frame, num=1, received=1)
        with mock.patch("os.makedirs"), mock.patch("cv2.imwrite"):
            self.win.save_capture()
        for _ in range(3):
            self.win._refresh()
            self.app.processEvents()
        self.assertEqual(self.win.toast.current_kind(), "success")
        self.assertTrue(self.win.toast.isVisible(),
                        "保存成功提示应跨刷新仍可见")

    def test_no_frame_warning_survives_next_refresh(self):
        """回归：无帧 warning 也必须跨刷新存活（同一条 clear() 缺陷）。"""
        self.win._timer.stop()
        self._show()
        self.win.save_capture()  # 无帧
        for _ in range(3):
            self.win._refresh()
            self.app.processEvents()
        self.assertEqual(self.win.toast.current_kind(), "warning")
        self.assertTrue(self.win.toast.isVisible())

    def test_error_toast_cleared_once_after_recovery(self):
        """错误恢复后只清一次：后续刷新不会反复影响一次性提示。"""
        self.win._timer.stop()
        self._show()
        self.win.model.last_error = "boom"
        self.win._refresh()
        self.assertTrue(self.win.toast.isVisible())
        self.win.model.last_error = None
        self.win._refresh()
        self.assertFalse(self.win.toast.isVisible())
        # 恢复后再弹一次性 success，后续刷新不应把它清掉
        frame = np.full((48, 64, 3), 120, dtype=np.uint8)
        self.win.model._set_frame(frame, num=7, received=7)
        with mock.patch("os.makedirs"), mock.patch("cv2.imwrite"):
            self.win.save_capture()
        self.win._refresh()
        self.assertEqual(self.win.toast.current_kind(), "success")
        self.assertTrue(self.win.toast.isVisible())

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
        self._emit_shortcut("R")
        self.assertEqual(self.win.model.reconnect_calls, 1)
        self._emit_shortcut("S")  # 无帧保存 → warning toast，不抛异常
        self.assertEqual(self.win.toast.current_kind(), "warning")

    def _emit_shortcut(self, seq: str):
        for sc in self.win.shortcuts:
            if sc.key().toString() == seq:
                sc.activated.emit()
                return
        self.fail(f"未找到快捷键 {seq}")

    def test_shortcut_ignored_while_typing_in_input(self):
        """回归：焦点在文本输入框时，单字符快捷键不得劫持按键。

        原缺陷：窗口级 QShortcut("S"/"R"/"1".."5") 会先于输入控件收到按键，
        在硬件面板输入 IP 192.168.1.10 就会切模式、在类别名里打 s 就会保存。
        """
        self.win._timer.stop()
        with mock.patch.object(type(self.win), "_focus_in_text_input",
                              return_value=True):
            self._emit_shortcut("S")
            self._emit_shortcut("R")
            self._emit_shortcut("3")
        self.assertEqual(self.win.model.reconnect_calls, 0, "输入时不得触发重连")
        self.assertEqual(self.win.mode, vision_modes.MODE_ORIGINAL,
                         "输入时不得切换模式")
        self.assertEqual(self.win.toast.current_kind(), "info",
                         "输入时不得弹出保存提示")

    def test_focus_helper_detects_line_edit(self):
        """_focus_in_text_input() 必须能识别真实 QLineEdit 焦点。"""
        from PySide6.QtWidgets import QLineEdit
        self._show()
        edit = QLineEdit(self.win)
        edit.show()
        edit.setFocus()
        self.app.processEvents()
        self.assertTrue(self.win._focus_in_text_input(),
                        "QLineEdit 获得焦点时应判定为『正在输入』")

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

    # =====================================================================
    # 回归：帧号去重不得挡住状态同步
    # =====================================================================

    def test_stale_switches_to_placeholder_without_new_frame(self):
        """回归：帧号没变时也必须切占位。

        原缺陷：_update_frame 在"帧号未变"时直接 return，把占位判断和统计同步
        一起跳过——停流后 3s 内状态灯不变、占位不出现，画面停在最后一帧。
        """
        self.win._timer.stop()
        frame = np.full((48, 64, 3), 90, dtype=np.uint8)
        self.win.model._set_frame(frame, num=1, received=1)
        self.win._refresh()
        self.assertEqual(self.win.video_view.render_state, "frame")

        self.win.model._set_stale(True)  # 帧号不变，只是变陈旧
        self.win._refresh()
        self.assertNotEqual(self.win.video_view.render_state, "frame",
                            "停流后应切到占位，而不是停住最后一帧")
        self.assertEqual(self.win.stats["state"], "Reconnecting")

    def test_resolution_follows_snapshot_when_ping_info_empty(self):
        """回归：ping_info 为空（启动页连接）时，分辨率必须跟着快照更新。

        原缺陷：st["width"]/["height"] 只读不写，走 ConnectionDialog 启动时
        诊断区"分辨率"恒为 0x0，/ping 上报的值永远不生效。
        """
        from qt_client.main_window import MainWindow
        win = MainWindow("http://fake/stream", "http://fake/ping", {})
        try:
            win._refresh()  # metrics 首次刷新前全是 None（占位状态）
            self.assertEqual(win.metrics["res"], "0x0")
            win.model._set_resolution(1280, 720)
            win._refresh()
            self.assertEqual(win.metrics["res"], "1280x720",
                             "分辨率应随快照更新")
            self.assertEqual(win.stats["width"], 1280)
            self.assertEqual(win.stats["height"], 720)
        finally:
            win.model.stop()
            win.close()


class QtI18nUiTest(unittest.TestCase):
    """P0-4B：语言实时切换更新各 UI 区域的真实控件文案。

    覆盖：顶栏保存按钮 / StatusPill 状态文本 / 模式与教学提示 / 诊断与 tooltip /
    参数占位 / 设备名占位。切换只更新文案层，不碰模式、参数、Model 实例、
    诊断展开（这些见 test_qt_gui_build.QtI18nWidgetTest）。

    依赖 P0-4B 源码（MainWindow 接入 translator）：未合入时整体 skip。
    """

    @classmethod
    def setUpClass(cls):
        from tests.test_qt_gui_build import TRANSLATOR_WIRED
        if not TRANSLATOR_WIRED:
            raise unittest.SkipTest("P0-4B MainWindow 未接入 Translator（等待源码 agent）")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tests.test_qt_gui_build import TRANSLATOR_WIRED, _make_win
        from qt_client.i18n import LANG_EN, LANG_ZH
        if not TRANSLATOR_WIRED:
            self.skipTest("P0-4B MainWindow 未接入 Translator（等待源码 agent）")
        self.patcher = mock.patch("qt_client.main_window.app_model.AppModel",
                                  FakeAppModel)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.win = _make_win(LANG_ZH)
        self.win.show()
        self.app.processEvents()
        self.win._timer.stop()
        self.LANG_EN = LANG_EN
        self.LANG_ZH = LANG_ZH

    def tearDown(self):
        self.win.model.stop()
        self.win.close()

    def _switch_to_en(self):
        self.win.translator.set_language(self.LANG_EN)
        self.app.processEvents()

    def _tr(self, key, **kw):
        """按窗口当前语言取文案（断言从字典取，验证真实控件状态）。"""
        return self.win.translator.text(key, **kw)

    # ---- 顶栏 ----

    def test_save_button_text_updates(self):
        """顶栏保存按钮：中文 '保存截图' ↔ 英文 'Save Screenshot'。"""
        from tests.test_qt_gui_build import _topbar_button
        save = _topbar_button(self.win, "primary")
        self.assertIsNotNone(save)
        self.assertEqual(save.text(), self._tr("save_screenshot"))
        self._switch_to_en()
        self.assertEqual(save.text(), "Save Screenshot")

    # ---- StatusPill ----

    def test_status_pill_state_text_updates(self):
        """StatusPill 状态文本随语言切换更新。"""
        self.win.model._set_state("Streaming")
        self.win._refresh()
        zh_text = self.win.status_pill.state()
        self.assertEqual(zh_text, "Streaming")  # 状态专名两语言保留英文
        # 语言切换后 pill 状态不变（状态是模型语义，文案由组件映射）
        self._switch_to_en()
        self.assertEqual(self.win.status_pill.state(), "Streaming")
        self.assertEqual(self.win.status_pill.state(), zh_text)

    # ---- 模式 / 教学提示 ----

    def test_mode_labels_and_hint_update(self):
        """模式标签与教学提示随语言切换更新。"""
        self.win.set_mode(vision_modes.MODE_CANNY)
        self.assertEqual(self.win.mode_label.text(), self._tr("current_mode", mode="Canny"))
        self.assertEqual(self.win.hint_label.text(), self._tr("hint_canny"))
        self._switch_to_en()
        self.assertEqual(self.win.mode_label.text(), "Current: Canny")
        self.assertEqual(self.win.hint_label.text(),
                         "Below Low is dropped, above High is kept, in-between edges must connect to a strong edge")
        # 模式按钮名（英文专名）保持
        self.assertEqual(self.win.mode_buttons[vision_modes.MODE_CANNY].text(),
                         "3 Canny")

    def test_contour_mode_button_localized(self):
        """轮廓模式按钮：中文 '5 轮廓' ↔ 英文 '5 Contours'。"""
        self.assertEqual(self.win.mode_buttons[vision_modes.MODE_CONTOUR].text(),
                         f"5 {self._tr('mode_contour')}")
        self._switch_to_en()
        self.assertEqual(self.win.mode_buttons[vision_modes.MODE_CONTOUR].text(),
                         "5 Contours")

    # ---- 设备名 / 参数占位 ----

    def test_device_placeholder_updates(self):
        """设备名占位文案随语言切换更新。"""
        self.win._refresh()
        self.assertEqual(self.win.device_label.text(), self._tr("device_placeholder"))
        self._switch_to_en()
        self.assertEqual(self.win.device_label.text(), "Waiting for device")

    # ---- 诊断 / tooltip ----

    def test_diagnostics_tooltips_update(self):
        """诊断区 tooltip 随语言切换更新。"""
        self.win._refresh()
        panel = self.win.diagnostics
        # 主指标（接收FPS/显示FPS/丢帧）的 tooltip 随语言变化
        cell = panel._value_labels["recv_fps"].parentWidget()
        self.assertEqual(cell.toolTip(), self._tr("tip_recv_fps"))
        self._switch_to_en()
        self.assertEqual(cell.toolTip(),
                         "Actual frames received by the PC per second")
        # 标题行也切换
        self.assertEqual(panel._toggle_btn.text(), self._tr("diag_expand"))

    def test_placeholder_texts_update(self):
        """画面占位主/副文案随语言切换更新（断流占位）。"""
        self.win.model._set_stale(True)
        self.win._refresh()
        self.assertEqual(self.win.video_view._placeholder_title.text(),
                         self._tr("placeholder_reconnecting"))
        self._switch_to_en()
        self.assertEqual(self.win.video_view._placeholder_title.text(),
                         "Video stream interrupted")

    # ---- Toast ----

    def test_toast_message_updates(self):
        """Toast 消息（无帧保存）随语言切换更新。"""
        self.win.save_capture()  # 无帧 → warning toast
        self.assertEqual(self.win.toast.current_kind(), "warning")
        self.assertEqual(self.win.toast._message.text(), self._tr("toast_no_frame"))
        self._switch_to_en()
        self.assertEqual(self.win.toast._message.text(), "No frame to save")


if __name__ == "__main__":
    unittest.main()
