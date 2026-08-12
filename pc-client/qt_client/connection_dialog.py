"""
PhoneVision Lab — 双击启动页（ConnectionDialog）。

职责：P0-5A 打包成 windowed EXE 后没有终端，双击运行时用户看不到 argparse
错误。本对话框是"无参数启动"的入口：让用户输入手机 IP/端口，点"连接"在
后台线程执行 /ping 预检，成功后由 main.py 创建 MainWindow；失败留在对话框
显示可行动错误，不退出到终端。

为什么这样设计：
  - 网络绝不进 GUI 主线程：/ping 只调 connection.ping_device()（共享连接层，
    不复制 HTTP 实现），在 QThread.run 里执行，结果经 Qt 队列信号回主线程。
  - 可测试：连接参数/结果都走信号与公开属性，测试可注入 fake ping（mock
    connection.ping_device）直接断言，不必真连网。
  - 防重：_connecting 标志保证连接中再次点击被忽略，不会叠加多个 worker。
  - 关闭安全：closeEvent 置停止标志 + wait(有界)；迟到 worker 即便成功也
    因 _closed 检查而不会在窗口关闭后创建 MainWindow（拒绝迟到 MainWindow）。
  - 最近地址：只在成功连接后写入 QSettings（PhoneVisionLab/PhoneVisionLab），
    预填进输入框，用户可自由编辑；示例 IP 绝不作为真实默认值。
  - 双语文案：复用 i18n.Translator，语言切换即时刷新，不重新发起网络请求。

注意：本模块不 import AppModel / MjpegReader / vision_modes，只依赖
connection 层做一次连接预检。
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

import connection
from qt_client.i18n import Translator

# QSettings 的组织/应用名（与 i18n.Translator 默认一致）。
_SETTINGS_ORG = "PhoneVisionLab"
_SETTINGS_APP = "PhoneVisionLab"

# QSettings 键。
_KEY_LAST_HOST = "connect/last_host"
_KEY_LAST_PORT = "connect/last_port"

# 端口输入框默认值（与 connection.build_urls 默认一致）。
DEFAULT_PORT = 8080

# 连接超时（秒）：只在 ping_device 自带 PING_TIMEOUT=5.0 之上再加一层兜底，
# 避免 QThread 因网络库问题无限卡住 closeEvent 的 wait()。
JOIN_TIMEOUT_SECONDS = 8.0

# 端口允许范围（合理 HTTP 服务端口，避免用户误填 0 或超范围值）。
PORT_MIN = 1
PORT_MAX = 65535

# 语言选择器：界面显示名 -> Translator 语言标识（与 main_window 保持一致）。
_LANGUAGE_OPTIONS = {
    "简体中文": "zh-CN",
    "English": "en",
}

# 首次使用时的输入框占位提示（仅当没有已保存地址时显示；不是真实默认值）。
_IP_PLACEHOLDER = "192.168.1.100"
_PORT_PLACEHOLDER = str(DEFAULT_PORT)

# 三步说明的行数（双语、可换行）。占位符 {port} 用于说明中嵌入默认端口。
_STEP_LINES = ("step_1", "step_2", "step_3")


class _PingWorker(QThread):
    """后台执行 /ping 的连接 worker（只做网络，不碰 GUI）。

    finished(result, error) 通过 Qt 队列连接回主线程（worker 与接收对象
    的 affinity 不同，emit 自动走队列，不跨线程直调 GUI 对象）。
    """
    finished = Signal(object, str)  # (PingResult, 用户原始输入)

    def __init__(self, ping_url: str, raw_input: str, parent=None):
        super().__init__(parent)
        self._ping_url = ping_url
        self._raw_input = raw_input
        self._stop = False  # 主线程置位，run 检查后提前退出

    def stop(self):
        """主线程调用：置停止标志，让 run 尽快退出。"""
        self._stop = True

    def run(self):
        if not self._stop:
            result = connection.ping_device(self._ping_url)
            if not self._stop:
                self.finished.emit(result, self._raw_input)


class ConnectionDialog(QDialog):
    """双击启动页：输入手机 IP/端口 → 后台 /ping → 成功即连接。

    信号：
      connected(str, str)  —— 预检成功，携带 (stream_url, ping_url)，
                              main.py 连接它创建 MainWindow。
    属性：
      connected_urls      —— 最近一次成功连接的 (stream_url, ping_url)，可断言。
      is_connecting       —— 是否正在连接（防重 / 测试断言）。
      tr                  —— 复用的 Translator 实例。
      error_label         —— 内联错误区（测试可读文本）。
    """

    connected = Signal(str, str)

    @property
    def is_connecting(self) -> bool:
        """是否正在连接（防重 / 测试断言）。"""
        return self._connecting

    def __init__(self, translator: Translator | None = None,
                 settings: QSettings | None = None, parent=None):
        super().__init__(parent)
        # QDialog 默认不绘制 QSS 背景，必须显式启用才能吃到深色主题。
        self.setAttribute(Qt.WA_StyledBackground, True)
        # 复用外部 Translator（main.py 传入全局实例，语言与主窗口一致）；
        # 未传时自建默认实例，保证独立可测。
        self.tr = translator if translator is not None else Translator()

        # ---- 状态 ----
        # 可注入 QSettings 用于测试隔离；不传则用真实用户配置（与 Translator 一致）。
        self._settings = settings if settings is not None else \
            QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._worker: _PingWorker | None = None
        self._connecting = False
        self._closed = False          # 关闭后置位：拒绝迟到 worker 创建主窗口
        self.connected_urls = None    # 最近成功连接 (stream_url, ping_url)
        self.host_input = None        # 占位属性，_build_ui 填充，便于测试定位

        self.setWindowTitle("PhoneVision Lab")
        self.setModal(True)

        self._build_ui()
        self._apply_language()
        self.tr.language_changed.connect(self._apply_language)

    # =====================================================================
    # 界面构建
    # =====================================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(10)

        # ---- 品牌标题 + 版本号 ----
        title = QLabel("PhoneVision Lab")
        title.setObjectName("connectionTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        self.version_label = QLabel()
        self.version_label.setObjectName("connectionVersion")
        self.version_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.version_label)

        # ---- 连接表单（IP / 端口 / 语言）----
        form = QFormLayout()
        form.setSpacing(8)

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText(_IP_PLACEHOLDER)
        self.host_input.setClearButtonEnabled(True)
        form.addRow(self._field_label("enter_ip_label"), self.host_input)

        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText(_PORT_PLACEHOLDER)
        self.port_input.setMaximumWidth(110)
        form.addRow(self._field_label("port_label"), self.port_input)

        self.language_selector = QComboBox()
        for label, lang in _LANGUAGE_OPTIONS.items():
            self.language_selector.addItem(label, lang)
        self.language_selector.setCurrentIndex(
            list(_LANGUAGE_OPTIONS.values()).index(self.tr.language()))
        self.language_selector.currentIndexChanged.connect(
            self._on_language_changed)
        form.addRow(self._field_label("language_label"), self.language_selector)

        root.addLayout(form)

        # 复用字段标签（语言切换时随 _apply_language 刷新）。
        self.host_field_label = None
        self.port_field_label = None
        self.language_field_label = None

        # ---- 三步说明 ----
        self.step_labels = []
        self._step_keys = list(_STEP_LINES)
        steps = QVBoxLayout()
        steps.setSpacing(2)
        for key in self._step_keys:
            lab = QLabel()
            lab.setProperty("textRole", "hint")
            lab.setWordWrap(True)
            steps.addWidget(lab)
            self.step_labels.append(lab)
        root.addLayout(steps)

        # ---- 内联错误区（多行、换行、红色）----
        self.error_label = QLabel()
        self.error_label.setObjectName("connectionError")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        # ---- 按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("cancelButton")
        self.cancel_btn.setProperty("buttonRole", "ghost")
        self.cancel_btn.setFixedHeight(34)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.connect_btn = QPushButton()
        self.connect_btn.setObjectName("connectButton")
        self.connect_btn.setProperty("buttonRole", "primary")
        self.connect_btn.setFixedHeight(34)
        self.connect_btn.clicked.connect(self.start_connect)
        self.connect_btn.setDefault(True)
        btn_row.addWidget(self.connect_btn)

        root.addLayout(btn_row)

        self.setMinimumWidth(420)

    def _field_label(self, key: str) -> QLabel:
        """表单字段左侧标签：统一存储，语言切换时刷新文本。"""
        lab = QLabel(self.tr.text(key))
        lab.setProperty("textRole", "caption")
        lab.setFixedWidth(72)
        if key == "enter_ip_label":
            self.host_field_label = lab
        elif key == "port_label":
            self.port_field_label = lab
        elif key == "language_label":
            self.language_field_label = lab
        return lab

    # =====================================================================
    # 语言切换
    # =====================================================================

    def _on_language_changed(self, index):
        """语言下拉切换：持久化并触发 language_changed → _apply_language。"""
        lang = self.language_selector.itemData(index)
        if lang and lang != self.tr.language():
            self.tr.set_language(lang, persist=True)

    def _apply_language(self):
        """按当前语言刷新全部可见文案（不重发网络请求）。"""
        self.version_label.setText(self._version_text())
        self.connect_btn.setText(self._connecting_text())
        self.cancel_btn.setText(self.tr.text("cancel_button"))

        if self.host_field_label is not None:
            self.host_field_label.setText(self.tr.text("enter_ip_label"))
        if self.port_field_label is not None:
            self.port_field_label.setText(self.tr.text("port_label"))
        if self.language_field_label is not None:
            self.language_field_label.setText(self.tr.text("language_label"))

        # 错误区 / 占位提示保留原文本（语言切换不重连、不清错误）。
        for lab, key in zip(self.step_labels, self._step_keys):
            lab.setText(self.tr.text(key))

        # step_3 嵌入端口，语言切换后重新格式化。
        self._refresh_step_3()

    def _refresh_step_3(self):
        """step_3 文案需要嵌入端口，语言切换后重取。"""
        if len(self.step_labels) >= 3:
            self.step_labels[2].setText(
                self.tr.text("step_3", port=self._current_port_str()))

    def _current_port_str(self) -> str:
        return self.port_input.text().strip() or str(DEFAULT_PORT)

    def _version_text(self) -> str:
        """取版本文案："v0.1.0-alpha.1"；version.py 缺失时降级为空说明。

        注意：i18n 尚无 version_label key，此处先用中性 "v{version}" 展示，
        避免界面出现 "???key???" 占位。i18n 补齐 key 后可改回 tr.text。
        """
        ver = None
        try:
            from qt_client.version import __version__ as ver  # 另一 agent 提供
        except Exception:  # noqa: BLE001 - version.py 尚不存在时降级，不阻塞对话框
            ver = None
        if ver:
            return f"v{ver}"
        return ""

    def _connecting_text(self) -> str:
        """连接中按钮文案；正在连接时优先显示"正在连接..."。"""
        if self._connecting:
            return self.tr.text("connecting_text")
        return self.tr.text("connect_button")

    # =====================================================================
    # 地址来源（最近成功地址预填）
    # =====================================================================

    @classmethod
    def _load_last_address(cls, settings) -> tuple[str | None, int | None]:
        """从 QSettings 读取最近成功连接的 host/port（无记录返回 (None, None)）。"""
        host = settings.value(_KEY_LAST_HOST)
        port = settings.value(_KEY_LAST_PORT)
        host = str(host).strip() if host else None
        port = int(port) if port is not None else None
        return (host or None), port

    def prefill_last_address(self):
        """用最近成功连接的地址预填输入框（无记录时留空，显示占位提示）。

        占位文本是示例，不是真实默认值：用户必须看到"我上次连过什么"，
        而不是被误导成真实地址。
        """
        host, port = self._load_last_address(self._settings)
        self.host_input.clear()
        self.port_input.clear()
        if host:
            self.host_input.setText(host)
        if port:
            self.port_input.setText(str(port))

    def _save_last_address(self, host: str, port: int):
        """成功连接后保存最近地址（只保存地址，不保存图片/日志/云数据）。"""
        self._settings.setValue(_KEY_LAST_HOST, host)
        self._settings.setValue(_KEY_LAST_PORT, port)

    # =====================================================================
    # 输入校验
    # =====================================================================

    def _host_value(self) -> str:
        return self.host_input.text().strip()

    def _port_value(self) -> int:
        raw = self.port_input.text().strip() or str(DEFAULT_PORT)
        try:
            port = int(raw)
        except ValueError:
            return None
        return port if PORT_MIN <= port <= PORT_MAX else None

    def _validate_inputs(self) -> tuple[str | None, str | None]:
        """校验输入。返回 (error_text, host)；host 有效时 error_text 为 None。

        host 为空 / 端口非法 → 内联错误 + 返回 (错误文案, None)。
        成功路径：返回 (None, host)。
        """
        host = self._host_value()
        if not host:
            return self.tr.text("error_host_required"), None
        port = self._port_value()
        if port is None:
            return self.tr.text("error_port_invalid"), None
        return None, host

    # =====================================================================
    # 连接动作
    # =====================================================================

    def start_connect(self):
        """用户点"连接"：校验 → 后台 /ping → 成功发信号 / 失败留对话框。

        防重：_connecting 期间再次点击直接忽略，不叠加多个 worker。
        """
        if self._connecting:
            return
        error, host = self._validate_inputs()
        if error is not None:
            self._show_error(error)
            return
        port = self._port_value()

        stream_url, ping_url = connection.build_urls(host=host, port=port)
        self._set_connecting(True)
        self._clear_error()

        worker = _PingWorker(ping_url, self.host_input.text().strip())
        worker.finished.connect(self._on_connect_finished)
        worker.destroyed.connect(self._on_worker_destroyed)
        self._worker = worker  # 保引用，防止被 GC
        worker.start()

    def _set_connecting(self, connecting: bool):
        self._connecting = connecting
        self.connect_btn.setText(self._connecting_text())
        self.connect_btn.setEnabled(not connecting)
        self.host_input.setEnabled(not connecting)
        self.port_input.setEnabled(not connecting)
        self.language_selector.setEnabled(not connecting)
        if connecting:
            self.connect_btn.setFocus()

    def _show_error(self, text: str):
        self.error_label.setText(text)
        self.error_label.setVisible(True)

    def _clear_error(self):
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _on_connect_finished(self, result, _raw_input):
        """主线程：worker 完成。已关闭则忽略（拒绝迟到 worker 创建主窗口）。"""
        if self._closed:
            self._cleanup_worker()
            return

        if result.success:
            host = self._host_value()
            port = self._port_value()
            stream_url, ping_url = connection.build_urls(host=host, port=port)
            self.connected_urls = (stream_url, ping_url)
            self._save_last_address(host, port)
            self._set_connecting(False)
            self._cleanup_worker()
            self.accept()
            self.connected.emit(stream_url, ping_url)
            return

        # 失败：留在对话框显示可行动错误。
        self._set_connecting(False)
        self._cleanup_worker()
        self._show_error(result.error or self.tr.text("error_unknown"))

    def _cleanup_worker(self):
        """清理 worker 引用与连接，便于 GC；不 join（已结束的线程无需等待）。"""
        if self._worker is not None:
            try:
                self._worker.finished.disconnect(self._on_connect_finished)
            except (RuntimeError, TypeError):
                pass
            self._worker.deleteLater()
            self._worker = None

    def _on_worker_destroyed(self):
        """worker 被销毁（正常结束或被 deleteLater）后清除引用。"""
        if self._worker is not None:
            self._worker = None

    # =====================================================================
    # 关闭安全
    # =====================================================================

    def closeEvent(self, event):
        """关闭窗口：置停止标志 + 有界等待，绝不在窗口关闭后创建 MainWindow。"""
        self._closed = True
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            # 有界等待：ping_device 自带 5s 超时，这里留足裕量。
            self._worker.wait(JOIN_TIMEOUT_SECONDS)
        self._cleanup_worker()
        super().closeEvent(event)
