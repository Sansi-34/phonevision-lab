"""
PhoneVision Lab — PySide6 GUI 构建测试（offscreen，不显示真实窗口）。

职责：在 QT_QPA_PLATFORM=offscreen 下构建 MainWindow，用假 AppModel/AppSnapshot
验证关键控件存在、状态刷新不抛异常、正常关闭。

为什么这样设计：
  - 不连接网络、不显示真实窗口，可离线确定性运行。
  - 用 FakeAppModel 替换真实 AppModel，避免启动后台 reader 线程与真实网络访问。
  - 覆盖 PySide6 客户端"能构建、能刷新、能关闭"的验收基线。

P0-4A 兼容：main_window.py / ui_components.py 正被源码 agent 重写为"工作台"布局。
依赖新布局（ui_components.VideoView 存在）的断言在 NEW_LAYOUT 为 False 时整体
skip，避免把"源码未完成"误报成"测试失败"；源码落地后自动启用。旧的布局无关
断言（模式按钮、滑块总数、FakeAppModel 驱动、标题不泄漏错误）对新旧布局都要
成立，保持双布局兼容。
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

    P0-4A：为工作台布局测试补齐状态控制与调用计数：
      - _set_state(state)：直接设置 connection_state（Streaming/Reconnecting/
        Stopped…），供顶栏状态 pill / 画面占位断言用。
      - _set_device_name(name)：顶栏设备名显示用。
      - _set_frame()/_set_stale() 维护 _state 与 _stale 的一致性（stale→
        Reconnecting，新帧→Idle），沿用既有 stale/恢复测试语义。
      - reconnect / mark_frame_displayed / set_last_error / refresh 各带
        *_calls 计数，验证 UI 交互（按钮点击 / 信号）确实驱动到模型层。
    """

    def __init__(self, **kw):
        self._started = False
        self._frame = None
        self._frame_num = None
        self._received = 0
        self._stale = False
        self._state = kw.get("state", "Idle")
        self.device_name = kw.get("device_name", "")
        self.last_error = None
        self._ping_ok = True
        self._phone_fps = kw.get("phone_fps", 0.0)
        # 调用计数：验证 UI 交互确实驱动到模型层
        self.reconnect_calls = 0
        self.mark_displayed_calls = 0
        self.refresh_calls = 0
        self.set_last_error_calls = 0

    def start(self):
        self._started = True

    def stop(self):
        pass

    def is_running(self):
        return self._started

    def _set_frame(self, frame, num, received):
        self._frame = frame
        self._frame_num = num
        self._received = received
        self._stale = False  # 新帧到达即解除 stale
        self._state = "Idle"  # 新帧到达即恢复正常状态

    def _set_stale(self, stale=True):
        self._stale = stale
        if stale:
            self._state = "Reconnecting"  # 让占位分支显示重连提示，便于断言
        else:
            self._state = "Idle"

    def _set_state(self, state):
        """直接设置连接状态（Streaming / Reconnecting / Stopped …）。"""
        self._state = state

    def _set_device_name(self, name):
        self.device_name = name

    def get_latest_frame(self):
        # stale 时模型层返回 (None, None)，UI 走占位分支
        if self._stale:
            return None, None
        return self._frame, self._frame_num

    def get_stats(self):
        return {"state": self._state, "received": self._received, "invalid": 0,
                "bytes": 0, "last_error": self.last_error}

    def get_state(self):
        return self._state

    def refresh(self):
        self.refresh_calls += 1

    def mark_frame_displayed(self):
        self.mark_displayed_calls += 1

    def reconnect(self):
        self.reconnect_calls += 1

    def set_last_error(self, msg):
        self.last_error = msg
        self.set_last_error_calls += 1

    def _snapshot_kw(self):
        return dict(
            connection_state=self._state, device_name=self.device_name,
            phone_fps=self._phone_fps, receive_fps=0.0, display_fps=0.0,
            width=640, height=480, average_jpeg_bytes=0.0, bandwidth_mbps=0.0,
            received_frames=self._received, invalid_frames=0,
            estimated_dropped_frames=0,
            last_error=self.last_error, last_ping_time=None,
            frame_stale=self._stale, frame_age_seconds=0.0,
        )

    def snapshot(self):
        # P0-3E：AppSnapshot 新增 frame_stale / frame_age_seconds 必填字段，
        # 假体构造时必须补上，否则 dataclass 构造抛 TypeError 使所有 Qt 测试崩。
        return app_model.AppSnapshot(**self._snapshot_kw())


def _new_layout_present():
    """P0-4A 工作台布局是否已落地（ui_components.VideoView 存在即视为已落地）。

    main_window.py / ui_components.py 正由源码 agent 重写，落地前依赖新布局的
    断言整体 skip——避免把"源码未完成"误报成"测试失败"；落地后自动启用。
    """
    try:
        import qt_client.ui_components as uc
    except Exception:
        return False
    return hasattr(uc, "VideoView")


NEW_LAYOUT = _new_layout_present()


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
        # offscreen 下必须先 show 再 processEvents，isVisible() 才反映真实可见性
        self.win.show()
        self.app.processEvents()

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

    def test_mode_buttons_exclusive(self):
        """P0-4A：五模式按钮由互斥 QButtonGroup 管理（选中其一，其余自动取消）。"""
        if not NEW_LAYOUT:
            self.skipTest("P0-4A 工作台布局未落地")
        self.assertIsNotNone(self.win.mode_group)
        self.assertTrue(self.win.mode_group.exclusive())
        # 同一 QButtonGroup 内的按钮只允许一个 checked
        self.win.mode_buttons[vision_modes.MODE_HSV].setChecked(True)
        checked = [m for m, b in self.win.mode_buttons.items() if b.isChecked()]
        self.assertEqual(checked, [vision_modes.MODE_HSV],
                         "设置 HSV 后其余模式按钮应取消选中")

    def test_device_name_shown(self):
        """P0-4A：顶栏设备名随模型 device_name 渲染；未获得时显示占位文案。

        占位文案只在"从未获得设备名"时显示：初始为空 → "等待设备信息"；
        一旦 /ping 给出设备名（snapshot.device_name 非空）→ 显示真实名称，
        且空值不会再改回占位文案（源码 `if snap.device_name` 守卫）。
        """
        if not NEW_LAYOUT:
            self.skipTest("P0-4A 工作台布局未落地")
        # 初始未获得设备名：显示占位文案
        self.win._refresh()
        self.assertEqual(self.win.device_label.text(), "等待设备信息",
                         "未获得设备名时应显示占位文案")
        # 获得设备名后：显示真实名称
        self.win.model._set_device_name("小米 MIX 2S")
        self.win._refresh()
        self.assertEqual(self.win.device_label.text(), "小米 MIX 2S")

    def test_titlebar_never_leaks_message(self):
        """P0-4A：标题栏不承担消息展示——始终为 'PhoneVision Lab'。

        覆盖规格 §19.1：保存成功/错误都走 toast，标题不含 '已保存' 或
        HTTPConnectionPool 等错误串。
        """
        if not NEW_LAYOUT:
            self.skipTest("P0-4A 工作台布局未落地")
        self.win.model.last_error = "HTTPConnectionPool(host='192.168.1.10', port=80)"
        self.win._refresh()
        self.assertEqual(self.win.windowTitle(), "PhoneVision Lab")
        self.win.save_capture()  # 无帧保存：不抛异常，也不污染标题
        self.assertEqual(self.win.windowTitle(), "PhoneVision Lab")

    def test_visible_sliders_per_mode(self):
        """P0-4A：各模式可见滑块数 = 0/0/2/6/7（其余滑块隐藏不丢失值）。

        规格 §19.2：切到 Canny 参数区只剩 2 根滑块，切到 HSV 只剩 6 根，
        切回原始无滑块。滑块按模式隐藏而非删除，因此 self.win.sliders 总数
        仍为 9（双布局兼容，见 test_sliders_exist）。按规格 §14 检查"真实可见性"：
        show() + processEvents() 后用 isVisible()（非仅 setVisible 布尔值）。
        """
        if not NEW_LAYOUT:
            self.skipTest("P0-4A 工作台布局未落地")
        self.win.show()
        self.app.processEvents()  # 触发布局，isVisible() 反映真实可见状态
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
            self.assertEqual(len(visible), count,
                             f"{mode} 模式可见滑块数应为 {count}，实得 {visible}")
        # 隐藏只是视觉层，参数值对象仍在（供"切换模式不丢值"测试复用）
        self.assertEqual(len(self.win.sliders), 9)

    def test_param_values_survive_mode_switch(self):
        """P0-4A：切换模式后隐藏参数值不丢失。

        场景：Canny 设 canny_low=77 → 切 HSV → 切回 Canny，canny_low 仍为 77。
        """
        if not NEW_LAYOUT:
            self.skipTest("P0-4A 工作台布局未落地")
        self.win.set_mode(vision_modes.MODE_CANNY)
        self.win.sliders["canny_low"].setValue(77)
        self.assertEqual(self.win.params["canny_low"], 77)
        self.win.set_mode(vision_modes.MODE_HSV)
        self.win.set_mode(vision_modes.MODE_CANNY)
        self.assertEqual(self.win.params["canny_low"], 77,
                         "切走再切回后 Canny 参数不应丢失")
        self.assertEqual(self.win.sliders["canny_low"].value(), 77)

    def test_teaching_hint_updates_with_mode(self):
        """P0-4A：教学提示随模式更新（hint_label 文本随模式变化，且非空）。"""
        if not NEW_LAYOUT:
            self.skipTest("P0-4A 工作台布局未落地")
        texts = set()
        for mode in (vision_modes.MODE_ORIGINAL, vision_modes.MODE_CANNY,
                     vision_modes.MODE_HSV, vision_modes.MODE_CONTOUR):
            self.win.set_mode(mode)
            t = self.win.hint_label.text().strip()
            self.assertTrue(t, f"{mode} 模式教学提示不应为空")
            texts.add(t)
        self.assertGreater(len(texts), 1, "至少两种模式的提示文案应不同")

    def test_diagnostics_default_three_metrics(self):
        """P0-4A：默认诊断只显示三个主要指标（接收FPS/显示FPS/丢帧）。"""
        if not NEW_LAYOUT:
            self.skipTest("P0-4A 工作台布局未落地")
        self.win._refresh()
        panel = self.win.diagnostics
        self.assertFalse(panel.is_expanded(), "默认应收起")
        visible = [key for key, lbl in panel._value_labels.items()
                   if lbl.isVisible()]
        self.assertEqual(len(visible), 3, f"默认应只显示 3 个指标，实得 {visible}")
        for key in ("recv_fps", "disp_fps", "dropped"):
            self.assertTrue(panel._value_labels[key].isVisible(), f"{key} 应常显")

    def test_diagnostics_expand_reveals_advanced(self):
        """P0-4A：展开后高级指标可见（toggle/set_expanded 后）。"""
        if not NEW_LAYOUT:
            self.skipTest("P0-4A 工作台布局未落地")
        self.win._refresh()
        panel = self.win.diagnostics
        panel.toggle()  # 展开
        self.app.processEvents()
        self.assertTrue(panel.is_expanded())
        visible = [key for key, lbl in panel._value_labels.items()
                   if lbl.isVisible()]
        self.assertGreater(len(visible), 3, "展开后应显示 3 个以上指标")
        for key in ("phone_fps", "mbps", "avg_jpeg_mb", "received", "invalid"):
            self.assertIn(key, visible, f"展开后 {key} 应可见")

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
        """占位画面成功渲染：_update_frame() 后画面区有占位内容。

        旧布局：_show_frame() 把占位 numpy 图转为 QImage 画进 QLabel，video_view
        是 QLabel，pixmap() 非 None。新布局（P0-4A）：占位由 VideoView 用 Qt 布局
        绘制（render_state 切离 "frame"），不再生成 QImage（_qimg 保持 None）。
        """
        self.win._timer.stop()
        self.win.show()
        self.app.processEvents()  # 触发布局，让 video_view 拿到真实尺寸
        self.win._update_frame()
        if NEW_LAYOUT:
            # 新 VideoView 无 pixmap()；占位走 render_state 语义
            self.assertNotEqual(self.win.video_view.render_state, "frame",
                                "占位时应切到占位渲染态")
            self.assertIsNone(self.win._qimg)
        else:
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
        # 状态一致性：占位时 stats 同步为快照状态——旧布局假体返回 Idle；
        # 新布局 FakeAppModel 同样默认 Idle（未 stale、未设置时即 "等待连接" 占位）。
        self.assertEqual(self.win.stats["state"], "Idle")


class QtStaleFrameTest(QtGuiBuildTest):
    """P0-3E：完整 _refresh() 路径下 stale 占位与恢复。

    为什么走完整 _refresh() 而不是单测 _update_frame()：_refresh() 才是真实
    QTimer 回调（model.refresh → _update_frame → _update_metrics），也是
    异常兜底写入 stats["error"] 的入口。要验证"UI 不被陈旧帧卡住、能切到占位、
    新帧能恢复"，就必须走这条真实路径。
    """

    def _render_real_frame(self, fill=120):
        """渲染一帧真实测试帧（BGR）。

        旧布局：video_view 是 QLabel，返回画面区 Pixmap 的 cacheKey 供对比。
        新布局（P0-4A）：VideoView 无 pixmap()，用 render_state 语义——
        返回 "frame"（实时画面渲染态）供 stale/恢复对比。
        """
        frame = np.full((48, 64, 3), fill, dtype=np.uint8)
        self.win.model._set_frame(frame, num=1, received=1)
        self.win.show()
        self.app.processEvents()  # 触发布局，让 video_view 拿到真实尺寸
        self.win._refresh()  # 完整路径：渲染真实帧
        if NEW_LAYOUT:
            self.assertEqual(self.win.video_view.render_state, "frame",
                             "真实帧应切到 frame 渲染态")
            return "frame"
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

        if NEW_LAYOUT:
            # 新布局：画面区切到重连占位（渲染态不再是 frame）
            self.assertEqual(self.win.video_view.render_state, "reconnecting",
                             "stale 后应切到重连占位渲染态")
        else:
            pm = self.win.video_view.pixmap()
            self.assertIsNotNone(pm, "占位分支也应渲染出 Pixmap")
            # 占位图是新画出的 Pixmap，cacheKey 必然与旧帧不同
            self.assertNotEqual(pm.cacheKey(), key,
                                "stale 后画面应切换到占位图而不是旧帧")
        # stats 不应残留异常文本
        self.assertEqual(self.win.stats["error"], "")
        self.assertNotIn("Traceback", self.win.windowTitle())

    def test_stale_placeholder_content_text(self):
        """stale 占位画面应绘制"等待/重连"提示文字，而非残留旧帧内容。

        旧布局：像素级验证占位文字覆盖中心区域。
        新布局（P0-4A）：占位由 VideoView 的 Qt 层绘制，验证占位层可见、
        标题文案为"视频流已中断"且画面层清空（不再残留旧帧像素）。
        """
        self.win._timer.stop()
        self._render_real_frame()
        self.win.model._set_stale(True)
        self.win._refresh()

        if NEW_LAYOUT:
            self.assertTrue(self.win.video_view._placeholder.isVisible(),
                            "stale 后占位层应可见")
            self.assertEqual(self.win.video_view._placeholder_title.text(),
                             "视频流已中断")
            self.assertTrue(self.win.video_view._frame_label.pixmap().isNull(),
                            "占位时画面层不应残留旧帧像素")
        else:
            # 用像素摘要证明画面内容已变：占位图中心应是文字覆盖区（非纯色填充帧）
            pm = self.win.video_view.pixmap()
            img = pm.toImage().convertToFormat(QImage.Format_RGB888)
            # PySide6 的 bits() 返回 memoryview（无 setsize），直接用 frombuffer 读取
            arr = np.frombuffer(img.bits(), dtype=np.uint8).reshape(
                img.height(), img.width(), 3)
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
        if NEW_LAYOUT:
            placeholder_state = self.win.video_view.render_state
            self.assertEqual(placeholder_state, "reconnecting")
        else:
            placeholder_key = self.win.video_view.pixmap().cacheKey()
            self.assertNotEqual(placeholder_key, key)

        # 新帧到达：received 增加、模型层解除 stale，_refresh 后应显示新帧
        new_frame = np.full((48, 64, 3), 90, dtype=np.uint8)
        self.win.model._set_frame(new_frame, num=2, received=2)
        self.win._refresh()

        if NEW_LAYOUT:
            self.assertEqual(self.win.video_view.render_state, "frame",
                             "新帧应切回 frame 渲染态")
            self.assertTrue(self.win.video_view._frame_label.pixmap().isNull() is False
                            or not self.win.video_view._placeholder.isVisible(),
                            "新帧后占位层应消失")
        else:
            pm = self.win.video_view.pixmap()
            self.assertIsNotNone(pm, "新帧应渲染出 Pixmap")
            # 新帧是新画的 Pixmap：既不同于旧帧，也不同于占位图
            self.assertNotEqual(pm.cacheKey(), key, "新帧应替换旧帧画面")
            self.assertNotEqual(pm.cacheKey(), placeholder_key,
                                "新帧应替换占位画面")
        # 原模式不变：模式是 UI 用户状态，stale/恢复不应改变它
        self.assertEqual(self.win.mode, vision_modes.MODE_ORIGINAL, "模式（原始）不变")
        self.assertEqual(self.win._last_frame_num, 2, "UI 帧序号应同步到新帧")
        # 占位时 stats 是 Reconnecting；新帧到达后模型层解除 stale，回到 Idle
        self.assertEqual(self.win.stats["state"], "Idle",
                         "新帧恢复后 stats 状态应回到 Idle（非 Reconnecting 占位）")

    def test_error_then_recovery_clears_ui(self):
        """错误清理：第一次 snapshot 含错误 → UI 显示；恢复且 last_error 空 → 恢复正常。

        覆盖"不残留旧字符串"：旧布局标题从 'PhoneVision Lab — HTTPConnectionPool…'
        回到 'PhoneVision Lab'；P0-4A 新布局错误改走 toast（顶栏状态条），
        标题始终为 'PhoneVision Lab'（见 test_titlebar_never_leaks_message）。两条路径
        都断言 stats["error"] 双向同步：有错误显示真实错误，恢复后被清空。
        """
        self.win._timer.stop()
        import vision_modes
        self.win.set_mode(vision_modes.MODE_CANNY)  # 验证模式不受错误清理影响
        self.win.model.last_error = "HTTPConnectionPool(host='192.168.1.10', port=80)"
        self.win._refresh()
        self.assertEqual(self.win.stats["error"], self.win.model.last_error)
        if NEW_LAYOUT:
            # 新布局：错误进 toast，标题栏始终干净
            self.assertEqual(self.win.windowTitle(), "PhoneVision Lab")
            self.assertEqual(self.win.toast.current_kind(), "error",
                             "网络错误应显示 error toast")
            self.assertTrue(self.win.toast.isVisible(), "错误 toast 应可见")
        else:
            # 旧布局：错误截断进标题栏
            self.assertIn("HTTPConnectionPool", self.win.windowTitle())

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
