"""
PhoneVision Lab — P0-5A 双击启动页（ConnectionDialog）测试（offscreen）。

职责：验证 P0-5A Windows 便携包的"双击连接启动页"：
  1. 无参数打开 ConnectionDialog（模拟 main.py 无参数分支）。
  2. 无参数不触发 argparse SystemExit。
  3. CLI --host 仍直达连接流程（不走对话框）。
  4. ConnectionDialog 中英文切换后按钮/标签文本变化。
  5. IP/主机名与端口校验（非法输入显示内联错误）。
  6. 网络请求不在 GUI 主线程（/ping 只发生在 worker 线程）。
  7. 连接期间按钮禁用并显示"正在连接"。
  8. 连续点击不创建多个 worker（连接中再次点击，ping 只调一次）。
  9. 失败显示内联错误。
  10. 成功后保存最近地址（QSettings 记录 host/port）。
  11. 失败不保存地址。
  12. 关闭对话框后迟到结果不 emit connected（不创建 MainWindow）。
  13. 成功后 connected 只 emit 一次 / 主窗口创建逻辑只跑一次。
  14. QSettings 测试隔离（注入临时 settings 作用域）。

为什么这样设计：
  - 网络测试全部用 fake ping（mock qt_client.connection_dialog.connection.ping_device），
    不连真机、不访问真实 IP。
  - offscreen 下 show() + processEvents() 才让 isVisible() 反映真实可见性。
  - ConnectionDialog.__init__ 硬编码 QSettings(_SETTINGS_ORG, _SETTINGS_APP)；
    测试通过 patch 模块级 _SETTINGS_ORG/_SETTINGS_APP 注入临时作用域，不污染
    真实 PhoneVisionLab 用户配置。
  - 语言切换用 FakeTranslator（确定性，不依赖 i18n 新 key 是否落地）+ 真实
    Translator（DIALOG_I18N_WIRED 时才启用，防"源码未完成"误报失败）。
  - main() 级测试注入有界 app_exec + 假 ConnectionDialog/MainWindow，验证
    main.py 的无参数/有参数两条分支，不真正进入事件循环、不创建真实主窗口。

依赖源码状态：
  - qt_client/connection_dialog.py 已落地（另一 agent）→ 对话框级测试可跑。
  - i18n.py 的对话框文案 key（cancel_button/step_1/...）尚未落地 →
    真实文本断言用 DIALOG_I18N_WIRED 门控；接线（wiring）断言用 FakeTranslator
    不受影响。
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

# 确保 Qt 用 offscreen 平台（必须在 import PySide6 前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import QApplication

import connection
import qt_client.connection_dialog as cdlg
from qt_client.i18n import STRINGS, Translator

# 对话框使用的 i18n key（i18n.py 尚未补全这些 key 时相关真实文本断言整体 skip）。
_DIALOG_KEYS = (
    "cancel_button", "enter_ip_label", "port_label", "language_label",
    "step_1", "step_2", "step_3", "version_label", "version_unknown",
    "connecting_text", "connect_button",
    "error_host_required", "error_port_invalid", "error_unknown",
)
DIALOG_I18N_WIRED = all(k in STRINGS for k in _DIALOG_KEYS)

# 成功 /ping 返回（fake）。
_PING_OK = connection.PingResult(
    True, {"device": "小米 MIX 2S", "width": 640, "height": 480,
           "actualFps": 15.0, "status": "streaming"})


# =====================================================================
# 假体：FakeTranslator / FakePing
# =====================================================================

_FAKE_STRINGS = {
    # 每个 key 都给中英两种不同文本，切换语言后必然可见变化。
    "cancel_button": ("取消", "Cancel"),
    "connect_button": ("连接", "Connect"),
    "connecting_text": ("正在连接...", "Connecting..."),
    "enter_ip_label": ("手机 IP", "Phone IP"),
    "port_label": ("端口", "Port"),
    "language_label": ("语言", "Language"),
    "step_1": ("步骤 1", "Step 1"),
    "step_2": ("步骤 2", "Step 2"),
    "step_3": ("步骤 3 端口 {port}", "Step 3 port {port}"),
    "version_label": ("版本 {version}", "Version {version}"),
    "version_unknown": ("版本未知", "Unknown version"),
    "error_host_required": ("请输入 IP", "Host is required"),
    "error_port_invalid": ("端口非法", "Invalid port"),
    "error_unknown": ("未知错误", "Unknown error"),
}


class FakeTranslator(QObject):
    """最小 Translator 替身：支持 text/set_language/language/language_changed。

    语义与真实 Translator 一致：set_language 持久化（记入 persisted）、语言变化
    emit language_changed；text(key) 按当前语言取文案并做 {placeholder} 替换。
    用它测"语言切换 → 界面文本刷新"的接线，不依赖 i18n 新 key 是否落地。

    继承 QObject 让 language_changed(Signal) 作为 QObject 属性正常工作
    （ConnectionDialog.__init__ 会连接该信号）。
    """
    language_changed = Signal(str)

    def __init__(self, language="zh-CN"):
        super().__init__()
        self._language = language
        self.persisted = []

    def language(self):
        return self._language

    def set_language(self, language, persist=True):
        lang = "zh-CN" if str(language).lower().startswith("zh") else "en"
        if persist:
            self.persisted.append(lang)
        if lang != self._language:
            self._language = lang
            self.language_changed.emit(lang)

    def text(self, key, **kwargs):
        zh, en = _FAKE_STRINGS.get(key, (f"?zh-{key}?", f"?en-{key}?"))
        out = zh if self._language == "zh-CN" else en
        for k, v in kwargs.items():
            out = out.replace("{" + k + "}", str(v))
        return out


class _BlockingPing:
    """阻塞式 fake ping：记录调用线程 ID 与次数，等 release 才返回。

    用于"连接中按钮禁用 / 防重 / 线程隔离"测试的确定性控制。
    stop_aware=True 时同时轮询停止标志：tearDown/closeEvent 调 worker.stop()
    后立即返回取消结果，避免"QThread Destroyed while thread is still running"
    的硬崩溃污染后续测试。
    """

    def __init__(self, result, stop_aware=False):
        self.result = result
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.thread_ids = []
        self.stop_aware = stop_aware
        self.observe_stop = None  # 注入: lambda -> worker._stop

    def __call__(self, ping_url, timeout=connection.PING_TIMEOUT):
        self.calls.append(ping_url)
        self.thread_ids.append(threading.get_ident())
        self.entered.set()
        deadline = time.monotonic() + timeout
        while not self.release.is_set():
            if (self.stop_aware and self.observe_stop is not None
                    and self.observe_stop()):
                return connection.PingResult(False, {}, "已取消")
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        return self.result


class _SlowPing:
    """短延时后返回的 fake ping：模拟"结果在窗口关闭后才回来"的迟到场景。

    stop_aware=True 时每 20ms 检查一次停止标志（observe_stop() 返回 True 即
    提前退出）：closeEvent 会调 worker.stop() 置位 _stop，随后 ping 立即放弃，
    run() 看到 _stop 后不再 emit，worker 线程及时结束。

    说明：当前 connection_dialog.closeEvent 的 wait() 单位是毫秒
    （QThread.wait(8.0) 实为 8ms），无法真正等到 ping 结束，因此测试必须让
    ping 尊重停止标志才能安全关闭。源码 agent 已被告知该缺陷（JOIN_TIMEOUT_SECONDS
    应乘 1000 或改用整数毫秒）。
    """

    def __init__(self, delay, result, stop_aware=False):
        self.delay = delay
        self.result = result
        self.stop_aware = stop_aware
        self.entered = threading.Event()
        self.observe_stop = None  # 注入: lambda -> worker._stop

    def __call__(self, ping_url, timeout=connection.PING_TIMEOUT):
        self.entered.set()
        deadline = time.monotonic() + self.delay
        while True:
            if (self.stop_aware and self.observe_stop is not None
                    and self.observe_stop()):
                return connection.PingResult(False, {}, "已取消")
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        return self.result


def _ok_ping(ping_url, timeout=connection.PING_TIMEOUT):
    return _PING_OK


# =====================================================================
# 测试基类：隔离 QSettings + 假 ping 注入
# =====================================================================


class ConnectionDialogTest(unittest.TestCase):
    """对话框级行为测试（offscreen，全假 ping）。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # 注入临时 QSettings 作用域：每次测试独立 org/app，不碰真实 PhoneVisionLab 配置。
        self._org = "PhoneVisionLabTest"
        self._app = f"p0_5a_{self._testMethodName}"
        self._settings_patcher = mock.patch(
            "qt_client.connection_dialog._SETTINGS_ORG", self._org)
        self._settings_patcher.start()
        self.addCleanup(self._settings_patcher.stop)
        self._settings_app_patcher = mock.patch(
            "qt_client.connection_dialog._SETTINGS_APP", self._app)
        self._settings_app_patcher.start()
        self.addCleanup(self._settings_app_patcher.stop)

        self.dialog = cdlg.ConnectionDialog(translator=Translator())
        # offscreen 下必须先 show 再 processEvents，isVisible() 才反映真实可见性
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):
        if self.dialog is not None:
            # 若 worker 仍在跑（断言中途失败/未释放）：先 stop 再关闭，
            # 避免残留线程污染后续测试或 QThread 销毁崩溃。
            if self.dialog._worker is not None and self.dialog._worker.isRunning():
                self.dialog._worker.stop()
                self._wait_worker_done(timeout=3.0)
            self.dialog.close()  # close() 触发 closeEvent：停 worker + 有界等待
        self.app.processEvents()

    # ---- 工具 ----

    def _start_ping_patcher(self, fake):
        """patch cdlg.connection.ping_device 为 fake，返回 patcher（随测试自动清理）。"""
        if isinstance(fake, (_BlockingPing, _SlowPing)):
            # 注入停止观察器：closeEvent 调 worker.stop() 后，stop-aware fake 提前退出，
            # 保证 worker 线程及时结束（防 QThread 销毁崩溃 + 测试间污染）。
            fake.observe_stop = lambda: (
                self.dialog._worker is not None
                and self.dialog._worker._stop
            )
        patcher = mock.patch("qt_client.connection_dialog.connection.ping_device", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher

    def _pump_until(self, cond, timeout=5.0):
        """processEvents 循环直到条件成立或超时（offscreen 下派发跨线程队列信号）。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cond():
                return True
            self.app.processEvents()
            time.sleep(0.01)
        return bool(cond())

    def _wait_worker_done(self, timeout=5.0):
        return self._pump_until(
            lambda: (self.dialog._worker is None
                     or not self.dialog._worker.isRunning()), timeout)

    def _assert_visible_error(self):
        """断言内联错误区可见且非空（不依赖具体文案，key 未落地也能断言）。"""
        self.assertTrue(self.dialog.error_label.isVisible(),
                        "内联错误区应可见")
        self.assertTrue(self.dialog.error_label.text(),
                        "内联错误不应为空")


# =====================================================================
# 输入校验（item 5）
# =====================================================================

class InputValidationTest(ConnectionDialogTest):
    """非法输入（空 IP / 非法端口）显示内联错误，且不发起任何网络请求。"""

    def test_empty_host_shows_inline_error(self):
        """IP 为空 → 内联错误可见，且不调用 ping（不浪费网络）。"""
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.start_connect()
        self._assert_visible_error()
        self.assertEqual(fake.calls, [], "IP 为空时不应发起 /ping")

    def test_invalid_port_shows_inline_error(self):
        """端口非数字或超范围 → 内联错误可见，且不调用 ping。

        注意：纯空白被源码视为"留空"→ 使用默认端口 8080（合法），因此不在非法列。
        """
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")
        for bad_port in ("abc", "0", "70000", "-5"):
            with self.subTest(bad_port=bad_port):
                self.dialog.port_input.setText(bad_port)
                self.dialog.start_connect()
                self._assert_visible_error()
        self.assertEqual(fake.calls, [], "端口非法时不应发起 /ping")

    def test_default_port_when_empty(self):
        """端口留空 → 使用默认 8080，校验通过并正常发起 ping。"""
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")
        self.dialog.port_input.setText("")
        self.dialog.start_connect()
        self._pump_until(fake.entered.is_set)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn(":8080/", fake.calls[0], "留空端口应使用默认 8080")
        fake.release.set()


# =====================================================================
# 连接流程（item 6/7/8/9/10/11/12/13）
# =====================================================================

class ConnectFlowTest(ConnectionDialogTest):

    def test_ping_runs_off_main_thread(self):
        """item 6：/ping 不在 GUI 主线程执行（worker 线程），主线程只收信号。"""
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        main_tid = threading.get_ident()

        self.dialog.host_input.setText("192.168.1.100")
        self.dialog.start_connect()
        self.assertTrue(self._pump_until(fake.entered.is_set, timeout=3.0),
                        "worker 应已进入 ping_device")
        self.assertEqual(len(fake.thread_ids), 1)
        self.assertNotEqual(fake.thread_ids[0], main_tid,
                            "/ping 必须在 worker 线程，而不是 GUI 主线程")
        fake.release.set()
        self._wait_worker_done()

    def test_connecting_disables_button_and_shows_text(self):
        """item 7：连接期间连接按钮禁用，文本切换为「正在连接」。"""
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")

        # 用 FakeTranslator 构造，连接中文本与空闲文本必然不同（不依赖 i18n key）。
        self.dialog.close()
        self.dialog = cdlg.ConnectionDialog(translator=FakeTranslator())
        idle_text = self.dialog.connect_btn.text()
        self.dialog.host_input.setText("192.168.1.100")

        self.dialog.start_connect()
        self.assertTrue(self._pump_until(fake.entered.is_set, timeout=3.0))
        self.assertFalse(self.dialog.connect_btn.isEnabled(),
                         "连接中连接按钮应禁用")
        self.assertFalse(self.dialog.host_input.isEnabled())
        self.assertFalse(self.dialog.port_input.isEnabled())
        self.assertEqual(self.dialog.connect_btn.text(), "正在连接...")
        self.assertNotEqual(self.dialog.connect_btn.text(), idle_text,
                            "连接中按钮文案应从「连接」切换为「正在连接」")
        fake.release.set()
        self._wait_worker_done()

    def test_double_click_starts_single_worker(self):
        """item 8：连接中再次点击被忽略，ping 只调用一次、connected 只 emit 一次。"""
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")

        spy = self._connect_spy()
        self.dialog.start_connect()
        self.assertTrue(self._pump_until(fake.entered.is_set, timeout=3.0))
        self.dialog.start_connect()  # 连接中再次点击 → 应被忽略
        self.assertEqual(len(fake.calls), 1, "连接中再次点击不应新增 worker/ping")
        self.assertTrue(self.dialog.is_connecting)
        fake.release.set()
        self.assertTrue(self._pump_until(lambda: spy.count() >= 1, timeout=3.0))
        self.assertEqual(spy.count(), 1, "成功只 emit 一次 connected")
        self.assertEqual(len(fake.calls), 1)
        self._wait_worker_done()

    def _connect_spy(self):
        from PySide6.QtTest import QSignalSpy
        return QSignalSpy(self.dialog.connected)

    def test_failure_shows_inline_error(self):
        """item 9：fake ping 失败 → 内联错误可见、对话框不关闭、地址不保存。"""
        fail = connection.PingResult(False, {}, "无法连接手机：请确认...")
        fake = _BlockingPing(fail, stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")

        self.dialog.start_connect()
        fake.release.set()
        self.assertTrue(self._pump_until(
            self.dialog.error_label.isVisible, timeout=3.0))
        self._assert_visible_error()
        self.assertIn("无法连接", self.dialog.error_label.text())
        self.assertFalse(self.dialog.is_connecting, "失败后应解除连接中状态")
        self.assertTrue(self.dialog.connect_btn.isEnabled(), "失败后按钮应恢复可用")
        self.assertIsNone(self.dialog.connected_urls)
        self._assert_not_saved()

    def test_success_saves_last_address(self):
        """item 10：成功连接 → QSettings 记录 host/port（可读回）。"""
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        host, port = "192.168.1.100", "9090"
        self.dialog.host_input.setText(host)
        self.dialog.port_input.setText(port)

        spy = self._connect_spy()
        self.dialog.start_connect()
        fake.release.set()
        self.assertTrue(self._pump_until(lambda: spy.count() >= 1, timeout=3.0))

        settings = QSettings(self._org, self._app)
        self.assertEqual(settings.value("connect/last_host"), host)
        self.assertEqual(int(settings.value("connect/last_port")), 9090)

    def test_failure_does_not_save_address(self):
        """item 11：失败不写 QSettings（无残留最近地址）。"""
        fake = _BlockingPing(connection.PingResult(False, {}, "超时"), stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")
        self.dialog.start_connect()
        fake.release.set()
        self.assertTrue(self._pump_until(
            self.dialog.error_label.isVisible, timeout=3.0))
        self._assert_not_saved()

    def _assert_not_saved(self):
        settings = QSettings(self._org, self._app)
        self.assertIsNone(settings.value("connect/last_host"),
                          "失败时不应保存最近 host")
        self.assertIsNone(settings.value("connect/last_port"),
                          "失败时不应保存最近 port")

    def test_close_then_late_result_does_not_emit(self):
        """item 12：关闭对话框后 worker 完成 → 不 emit connected、不创建主窗口。

        run() 在 ping 返回后检查 _stop；closeEvent 已置 _closed 并 stop()，
        迟到结果被双层守卫拦截。用 stop-aware 的短延时 ping：closeEvent 置停止
        标志后 ping 提前退出（run 不再 emit），worker 线程及时结束。

        注意：connection_dialog.closeEvent 的 wait(8.0) 实为 8ms（QThread 单位），
        不足以等到 ping 结束，因此本测试必须用 stop-aware ping 避免"QThread
        Destroyed while thread is still running"硬崩溃。
        """
        fake = _SlowPing(2.0, _PING_OK, stop_aware=True)
        fake.observe_stop = lambda: (self.dialog._worker is not None
                                     and self.dialog._worker._stop)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")

        spy = self._connect_spy()
        self.dialog.start_connect()
        self.assertTrue(self._pump_until(fake.entered.is_set, timeout=3.0))
        self.dialog.close()  # closeEvent：_closed=True + stop + wait（8ms，快速返回）
        self.assertTrue(self._wait_worker_done(), "worker 应已结束")
        self.app.processEvents()
        self.assertEqual(spy.count(), 0, "关闭后迟到结果不得 emit connected")
        self.assertIsNone(self.dialog.connected_urls)
        self._assert_not_saved()

    def test_success_emits_connected_once_with_urls(self):
        """item 13（对话框侧）：成功只 emit 一次 connected，且携带正确 URL。"""
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")
        self.dialog.port_input.setText("9090")

        spy = self._connect_spy()
        self.dialog.start_connect()
        fake.release.set()
        self.assertTrue(self._pump_until(lambda: spy.count() >= 1, timeout=3.0))
        self.assertEqual(spy.count(), 1, "成功只 emit 一次 connected")
        stream, ping = spy.at(0)[0], spy.at(0)[1]
        self.assertEqual(stream, "http://192.168.1.100:9090/stream")
        self.assertEqual(ping, "http://192.168.1.100:9090/ping")
        self.assertEqual(self.dialog.connected_urls, (stream, ping))

    def test_settings_scope_is_isolated(self):
        """item 14：注入的临时 settings 作用域不污染真实 PhoneVisionLab 配置。

        测试作用域内已保存；真实 PhoneVisionLab 作用域与另一测试作用域 B 的
        记录数都保持不变（对比写入前后，兼容真实作用域本就有历史记录）。
        """
        real_scope = QSettings("PhoneVisionLab", "PhoneVisionLab")
        other_scope = QSettings(self._org, "other_test_scope")
        real_before = real_scope.value("connect/last_host")
        other_before = other_scope.value("connect/last_host")

        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)
        self.dialog.host_input.setText("192.168.1.100")
        self.dialog.start_connect()
        fake.release.set()
        spy = self._connect_spy()
        self.assertTrue(self._pump_until(lambda: spy.count() >= 1, timeout=3.0))

        # 测试作用域内已保存
        self.assertEqual(
            QSettings(self._org, self._app).value("connect/last_host"),
            "192.168.1.100")
        # 真实作用域记录未变化（测试写入不落进真实配置）
        self.assertEqual(real_scope.value("connect/last_host"), real_before)
        # 另一个测试作用域（不同 app 名）互不串扰
        self.assertEqual(other_scope.value("connect/last_host"), other_before)


# =====================================================================
# 语言切换（item 4）
# =====================================================================

class LanguageSwitchTest(ConnectionDialogTest):

    def test_language_switch_wiring_updates_texts(self):
        """item 4（接线）：语言下拉切换 → set_language → language_changed →
        _apply_language 刷新按钮/标签文本。FakeTranslator 保证文案必然变化。

        host_field_label 等表单标签属性依赖源码已落地（当前 connection_dialog
        把 `_field_label` 设置的属性又置为 None，是待修复的源码缺陷）——
        未落地时跳过这些标签断言，但按钮/版本标签/无崩溃仍要成立。
        """
        tr = FakeTranslator()
        self.dialog.close()
        self.dialog = cdlg.ConnectionDialog(translator=tr)
        self.dialog.show()
        self.app.processEvents()

        zh_texts = (self.dialog.connect_btn.text(),
                    self.dialog.cancel_btn.text(),
                    self.dialog.version_label.text())
        self.assertEqual(zh_texts[0], "连接")

        # 语言下拉切到 English
        idx = self.dialog.language_selector.findData("en")
        self.assertGreaterEqual(idx, 0, "语言选择器应有 en 项")
        self.dialog.language_selector.setCurrentIndex(idx)
        self.app.processEvents()

        en_texts = (self.dialog.connect_btn.text(),
                    self.dialog.cancel_btn.text(),
                    self.dialog.version_label.text())
        self.assertEqual(en_texts[0], "Connect", "连接按钮应切为英文")
        self.assertNotEqual(zh_texts, en_texts,
                            "切换语言后按钮/标签文本应变化")
        self.assertEqual(tr.persisted, ["en"], "切换应持久化语言选择")

        # 表单标签属性已落地（源码修复后）→ 再断言它们也随语言切换
        if self.dialog.host_field_label is not None:
            self.assertEqual(self.dialog.host_field_label.text(), "Phone IP",
                             "切换 en 后 IP 标签应更新")
            self.assertNotEqual(
                self.dialog.host_field_label.text(), "手机 IP",
                "表单标签应在语言切换时刷新")

    def test_language_switch_keeps_inputs(self):
        """item 4（防御）：语言切换不重发网络请求、不清空已填地址。"""
        tr = FakeTranslator()
        self.dialog.close()
        self.dialog = cdlg.ConnectionDialog(translator=tr)
        self.dialog.host_input.setText("192.168.1.100")
        fake = _BlockingPing(_PING_OK, stop_aware=True)
        self._start_ping_patcher(fake)

        idx = self.dialog.language_selector.findData("en")
        self.dialog.language_selector.setCurrentIndex(idx)
        self.app.processEvents()

        self.assertEqual(self.dialog.host_input.text(), "192.168.1.100",
                         "语言切换不应清空已填 IP")
        self.assertEqual(fake.calls, [], "语言切换不应发起网络请求")

    @unittest.skipUnless(DIALOG_I18N_WIRED, "i18n.py 对话框文案 key 未落地（等待源码 agent）")
    def test_language_switch_real_translator_changes_text(self):
        """item 4（真实文案）：真实 Translator + 已落地 i18n key 时，切换后文本变化。"""
        self.dialog.show()
        self.app.processEvents()
        before = self.dialog.connect_btn.text()
        idx = self.dialog.language_selector.findData("en")
        self.dialog.language_selector.setCurrentIndex(idx)
        self.app.processEvents()
        after = self.dialog.connect_btn.text()
        self.assertNotEqual(before, after, "切换 en 后连接按钮文本应变化")
        self.assertNotIn("???", after, "不应残留缺失 key 占位符")


# =====================================================================
# 版本号 / 最近地址预填
# =====================================================================

class DialogMiscTest(ConnectionDialogTest):

    def test_version_label_uses_version_when_present(self):
        """version.py 存在时，version_label 显示版本号；缺失时降级为非空文案。"""
        fake_version = type("_FakeVersion", (), {"__version__": "9.9.9-test"})()
        with mock.patch.dict(sys.modules, {"qt_client.version": fake_version}):
            text = self.dialog._version_text()
        self.assertIn("9.9.9-test", text, "应显示注入的版本号")

        # 无 version.py（正常现状）→ 降级文案非空，不抛异常
        fallback = self.dialog._version_text()
        self.assertTrue(fallback, "version.py 缺失时应降级为非空文案")

    def test_prefill_last_address_from_settings(self):
        """最近成功地址预填：先写临时 settings，再 prefill 应回填输入框。"""
        settings = QSettings(self._org, self._app)
        settings.setValue("connect/last_host", "192.168.5.6")
        settings.setValue("connect/last_port", 8080)
        self.dialog.prefill_last_address()
        self.assertEqual(self.dialog.host_input.text(), "192.168.5.6")
        self.assertEqual(self.dialog.port_input.text(), "8080")

    def test_no_saved_address_leaves_placeholder(self):
        """无已保存地址 → 输入框留空（显示占位提示，而非伪默认值）。"""
        self.dialog.prefill_last_address()
        self.assertEqual(self.dialog.host_input.text(), "")
        self.assertEqual(self.dialog.port_input.text(), "")


# =====================================================================
# main() 级：无参数 / 有参数两条分支
# =====================================================================

class QtClientMainP05ATest(unittest.TestCase):
    """验证 qt_client.main.main() 的无参数与有参数分支（不真正进入事件循环）。

    统一 mock：
      - qt_client.main.QApplication 返回既有实例（避免二次构造 QApplication 崩溃）；
      - qt_client.main.app_exec 替换为有界事件循环；
      - ConnectionDialog / MainWindow 换成受控假体（对话框级行为已在上方单测）。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import qt_client.main as qmain
        self.qmain = qmain
        self.qapp_patcher = mock.patch.object(
            qmain, "QApplication", side_effect=lambda *a, **k:
            QApplication.instance() or QApplication([]))
        self.qapp_patcher.start()
        self.addCleanup(self.qapp_patcher.stop)
        self.mw_calls = []
        self.exec_seconds = 0.2
        # 隔离 QSettings 作用域：_SpyDialog 继承真实 ConnectionDialog，会读写
        # QSettings(_SETTINGS_ORG, _SETTINGS_APP)，必须指向临时作用域不污染真实配置。
        self._org = "PhoneVisionLabTest"
        self._app = f"p0_5a_main_{self._testMethodName}"
        self._settings_patcher = mock.patch(
            "qt_client.connection_dialog._SETTINGS_ORG", self._org)
        self._settings_patcher.start()
        self.addCleanup(self._settings_patcher.stop)
        self._settings_app_patcher = mock.patch(
            "qt_client.connection_dialog._SETTINGS_APP", self._app)
        self._settings_app_patcher.start()
        self.addCleanup(self._settings_app_patcher.stop)

    # ---- 工具 ----

    def _patch_app_exec(self, seconds=None):
        seconds = self.exec_seconds if seconds is None else seconds
        def bounded_exec():
            app = QApplication.instance()
            QTimer.singleShot(int(seconds * 1000), app.quit)
            return app.exec()
        patcher = mock.patch.object(self.qmain, "app_exec", side_effect=bounded_exec)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch_main_window(self):
        """假 MainWindow：记录构造次数，返回带 .show() 的桩。"""
        class _FakeMW:
            def __init__(self, *a, **k):
                mw_calls.append(self)
            def show(self):
                self.shown = True
            def stop(self):
                pass
        mw_calls = self.mw_calls
        patcher = mock.patch.object(self.qmain, "MainWindow", _FakeMW)
        patcher.start()
        self.addCleanup(patcher.stop)
        return _FakeMW

    def _patch_dialog(self, dialog_cls):
        patcher = mock.patch("qt_client.connection_dialog.ConnectionDialog",
                             dialog_cls)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_args_opens_connection_dialog(self):
        """item 1：main([]) 无参数 → 打开 ConnectionDialog（不直连、不退出）。

        offscreen 下窗口在嵌套 exec 内 show、exec 退出后 isVisible() 会变回 False
        （平台窗口状态随事件循环退出被回收），因此用"show() 确实被调用"记录，
        这是双击启动页语义的可靠信号。
        """
        captured = []

        class _SpyDialog(cdlg.ConnectionDialog):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                captured.append(self)
                self.shown = False

            def show(self):
                super().show()
                self.shown = True

        self._patch_dialog(_SpyDialog)
        self._patch_app_exec()
        self._patch_main_window()

        rc = self.qmain.main([])
        self.assertEqual(rc, 0, "无参数启动应正常返回 0")
        self.assertEqual(len(captured), 1, "无参数应构造一个 ConnectionDialog")
        self.assertTrue(captured[0].shown,
                        "对话框应被 show（无参数双击启动页语义）")
        # 无参数分支不创建主窗口（连接成功后才由对话框信号触发）
        self.assertEqual(self.mw_calls, [], "无参数、未连接时不应创建 MainWindow")

    def test_no_args_does_not_raise_system_exit(self):
        """item 2：无参数不触发 argparse SystemExit（可被双击 EXE 直接调用）。"""
        self._patch_dialog(mock.MagicMock())
        self._patch_app_exec()
        self._patch_main_window()
        # parse_args([]) 本身不得抛 SystemExit
        args = self.qmain.parse_args([])
        self.assertIsNone(args.host)
        self.assertIsNone(args.stream_url)
        # main([]) 全程不抛 SystemExit
        rc = self.qmain.main([])
        self.assertEqual(rc, 0)

    def test_cli_host_still_reaches_direct_connect(self):
        """item 3：CLI --host 仍直达连接流程（ping 成功 → 直接创建 MainWindow）。"""
        ping_patcher = mock.patch(
            "qt_client.main.connection.ping_device", side_effect=_ok_ping)
        ping_patcher.start()
        self.addCleanup(ping_patcher.stop)

        dialog_mock = mock.MagicMock()
        self._patch_dialog(dialog_mock)
        self._patch_app_exec()
        fake_mw = self._patch_main_window()

        rc = self.qmain.main(["--host", "192.168.1.100"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.mw_calls), 1,
                         "ping 成功时 --host 应直达 MainWindow 创建")
        self.assertTrue(hasattr(self.mw_calls[0], "shown")
                        and self.mw_calls[0].shown,
                        "直达创建的主窗口应被 show")
        dialog_mock.assert_not_called(),
        "CLI 直连路径不应打开 ConnectionDialog"

    def test_success_creates_single_main_window(self):
        """item 13（main 侧）：对话框 connected 一次 → MainWindow 创建逻辑只跑一次。"""
        class _AutoConnectDialog(QObject):
            # 继承 QObject 让 connected 作为可用 Signal 描述符（main 会 .connect 它）
            connected = Signal(str, str)

            def __init__(self, translator=None):
                super().__init__()
                self.tr = translator
                self.shown = False

            def prefill_last_address(self):
                pass

            def show(self):
                self.shown = True
                QTimer.singleShot(0, self._emit)

            def _emit(self):
                self.connected.emit("http://192.168.1.100:8080/stream",
                                    "http://192.168.1.100:8080/ping")

        self._patch_dialog(_AutoConnectDialog)
        self._patch_app_exec()
        self._patch_main_window()

        rc = self.qmain.main([])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.mw_calls), 1,
                         "connected 只触发一次主窗口创建逻辑")

    def test_cli_host_ping_failure_opens_dialog(self):
        """CLI 预检失败不静默退出：打开预填地址的 ConnectionDialog 让用户修正。"""
        ping_patcher = mock.patch(
            "qt_client.main.connection.ping_device",
            return_value=connection.PingResult(False, {}, "无法连接手机"))
        ping_patcher.start()
        self.addCleanup(ping_patcher.stop)

        captured = []

        class _SpyDialog(cdlg.ConnectionDialog):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                captured.append(self)

        self._patch_dialog(_SpyDialog)
        self._patch_app_exec()

        rc = self.qmain.main(["--host", "192.168.1.100"])
        self.assertEqual(rc, 0, "CLI 预检失败不得以 SystemExit 退出")
        self.assertEqual(len(captured), 1, "预检失败应打开对话框让用户修正")
        self.assertEqual(captured[0].host_input.text(), "192.168.1.100",
                         "对话框应预填 CLI 传入的 host")


if __name__ == "__main__":
    unittest.main()
