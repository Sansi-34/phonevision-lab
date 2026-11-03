"""
PhoneVision Lab — 硬件联动面板（PySide6）。

职责：连接外部控制器、手动动作测试、配置规则、开关自动控制、查看事件记录。

为什么这样设计：
  - 硬件通信完全走 pvl_hardware（与 Android 端同构的规则引擎 + 设备适配器），
    本面板只做展示与用户输入，绝不自己发 HTTP。
  - 自动控制默认关闭；必须"已连接 + 完成手动验证"后才允许开启。
  - 命令状态四态分明：已发送 / 已接收 / 已执行 / 失败。
    设备只确认接收时只显示"已接收"，绝不显示"执行成功"。
  - 模拟设备入口明确标注"仅验证软件链路，不等于真机验收"。

初学者调试观察点：
  - 连不上：确认控制器 IP、端口 8081、与电脑同一局域网。
  - LED 不动但显示"已发送"：控制器没回 ack，看事件记录里的 message。
"""
from __future__ import annotations
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox,
    QVBoxLayout,
)

from pvl_hardware import (
    ACTION_LED_OFF, ACTION_LED_ON, ACTION_STATUS, DeviceAdapter,
    HardwareController, RuleEngine, STATUS_EXECUTED, STATUS_FAILED,
    STATUS_RECEIVED,
)

DEFAULT_PORT = 8081


class HardwarePanel(QFrame):
    """硬件联动面板。"""

    # 自动控制状态变化信号
    auto_state_changed = Signal(bool)
    _connection_result = Signal(object, object)
    _manual_result = Signal(object, object)

    def __init__(self, translator, class_provider=None,
                 prediction_provider=None, parent=None):
        super().__init__(parent)
        self.tr = translator
        # class_provider: 可调用对象，返回当前模型的类别名列表（用于目标类别下拉）
        self.class_provider = class_provider
        # prediction_provider: 可调用对象，返回 (label, confidence) 或 None。
        # PC 客户端默认只做传统视觉模式（无分类器），因此默认没有预测来源；
        # 只有显式注入了来源，"开启自动控制"才会真正产生动作。
        self.prediction_provider = prediction_provider
        self.setObjectName("hardwarePanel")

        self.adapter: DeviceAdapter | None = None
        self.controller: HardwareController | None = None
        self._events: list = []
        self._connection_result.connect(self._on_connection_result)
        self._manual_result.connect(self._on_manual_result)

        self._build_ui()
        self._apply_language()
        self.tr.language_changed.connect(self._apply_language)

    # =====================================================================
    # 界面
    # =====================================================================

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        # ---- 连接 ----
        conn = QHBoxLayout()
        self.host_label = QLabel()
        conn.addWidget(self.host_label)
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("192.168.x.x")
        conn.addWidget(self.host_input, 2)
        self.port_label = QLabel()
        conn.addWidget(self.port_label)
        self.port_input = QLineEdit(str(DEFAULT_PORT))
        self.port_input.setMaximumWidth(70)
        conn.addWidget(self.port_input)
        self.connect_button = QPushButton()
        self.connect_button.clicked.connect(self.on_connect)
        conn.addWidget(self.connect_button)
        self.disconnect_button = QPushButton()
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.clicked.connect(self.on_disconnect)
        conn.addWidget(self.disconnect_button)
        outer.addLayout(conn)

        self.link_label = QLabel()
        self.link_label.setProperty("textRole", "caption")
        outer.addWidget(self.link_label)

        # ---- 手动测试 ----
        manual = QHBoxLayout()
        self.manual_label = QLabel()
        self.manual_label.setProperty("textRole", "groupTitle")
        manual.addWidget(self.manual_label)
        self.led_on_button = QPushButton()
        self.led_on_button.setEnabled(False)
        self.led_on_button.clicked.connect(lambda: self.on_manual(ACTION_LED_ON))
        manual.addWidget(self.led_on_button)
        self.led_off_button = QPushButton()
        self.led_off_button.setEnabled(False)
        self.led_off_button.clicked.connect(lambda: self.on_manual(ACTION_LED_OFF))
        manual.addWidget(self.led_off_button)
        outer.addLayout(manual)

        self.manual_hint = QLabel()
        self.manual_hint.setProperty("textRole", "hint")
        self.manual_hint.setWordWrap(True)
        outer.addWidget(self.manual_hint)

        # ---- 规则配置 ----
        rules = QHBoxLayout()
        self.target_label = QLabel()
        rules.addWidget(self.target_label)
        self.target_combo = QComboBox()
        self.target_combo.setMinimumWidth(120)
        rules.addWidget(self.target_combo, 1)

        self.trigger_label = QLabel()
        rules.addWidget(self.trigger_label)
        self.trigger_spin = QDoubleSpinBox()
        self.trigger_spin.setRange(0.1, 1.0)
        self.trigger_spin.setSingleStep(0.05)
        self.trigger_spin.setValue(0.75)
        rules.addWidget(self.trigger_spin)

        self.confirm_label = QLabel()
        rules.addWidget(self.confirm_label)
        self.confirm_spin = QSpinBox()
        self.confirm_spin.setRange(1, 20)
        self.confirm_spin.setValue(3)
        rules.addWidget(self.confirm_spin)

        self.exit_label = QLabel()
        rules.addWidget(self.exit_label)
        self.exit_spin = QDoubleSpinBox()
        self.exit_spin.setRange(0.0, 0.99)
        self.exit_spin.setSingleStep(0.05)
        self.exit_spin.setValue(0.45)
        rules.addWidget(self.exit_spin)

        self.release_label = QLabel()
        rules.addWidget(self.release_label)
        self.release_spin = QSpinBox()
        self.release_spin.setRange(1, 60)
        self.release_spin.setValue(5)
        rules.addWidget(self.release_spin)

        self.cooldown_label = QLabel()
        rules.addWidget(self.cooldown_label)
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(0, 60000)
        self.cooldown_spin.setSingleStep(500)
        self.cooldown_spin.setValue(2000)
        rules.addWidget(self.cooldown_spin)
        outer.addLayout(rules)

        self.rule_hint = QLabel()
        self.rule_hint.setProperty("textRole", "hint")
        self.rule_hint.setWordWrap(True)
        outer.addWidget(self.rule_hint)

        # ---- 自动控制 ----
        auto = QHBoxLayout()
        self.auto_check = QCheckBox()
        self.auto_check.setChecked(False)
        self.auto_check.toggled.connect(self.on_auto_toggled)
        auto.addWidget(self.auto_check)
        self.stop_button = QPushButton()
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.on_stop_control)
        auto.addWidget(self.stop_button)
        auto.addStretch(1)
        outer.addLayout(auto)

        self.sim_check = QCheckBox()
        self.sim_check.setToolTip(self.tr.text("hw_simulated"))
        outer.addWidget(self.sim_check)

        # ---- 模式说明：PC 端能否驱动自动控制 ----
        self.mode_note = QLabel()
        self.mode_note.setProperty("textRole", "hint")
        self.mode_note.setWordWrap(True)
        outer.addWidget(self.mode_note)
        self._refresh_mode_note()

        # ---- 事件记录 ----
        self.event_label = QLabel()
        self.event_label.setProperty("textRole", "groupTitle")
        outer.addWidget(self.event_label)

        self.event_list = QListWidget()
        self.event_list.setMinimumHeight(140)
        outer.addWidget(self.event_list, 1)

        self._refresh_target_classes()

    def _refresh_target_classes(self):
        self.target_combo.clear()
        if self.class_provider is None:
            return
        try:
            classes = self.class_provider() or []
        except Exception:  # noqa: BLE001
            classes = []
        for name in classes:
            self.target_combo.addItem(str(name), str(name))

    def refresh_classes(self):
        """外部（模型加载后）调用：刷新目标类别下拉。"""
        self._refresh_target_classes()

    def _refresh_mode_note(self):
        """说明当前 PC 端能否驱动自动控制（不冒充可用）。"""
        if not hasattr(self, "mode_note"):
            return
        if self.prediction_provider is None:
            self.mode_note.setText(self.tr.text("hw_pc_no_classifier"))
        else:
            self.mode_note.setText(self.tr.text("hw_pc_has_classifier"))

    # =====================================================================
    # 语言
    # =====================================================================

    def _apply_language(self):
        t = self.tr.text
        self.host_label.setText(t("hw_device_ip"))
        self.port_label.setText(t("hw_port"))
        self.connect_button.setText(t("hw_connect"))
        self.disconnect_button.setText(t("hw_disconnect"))
        self.manual_label.setText(t("hw_manual"))
        self.led_on_button.setText(t("hw_led_on"))
        self.led_off_button.setText(t("hw_led_off"))
        self.manual_hint.setText(t("hw_ack_note"))
        self.target_label.setText(t("hw_target_class"))
        self.trigger_label.setText(t("hw_trigger_conf"))
        self.confirm_label.setText(t("hw_confirm_count"))
        self.exit_label.setText(t("hw_exit_conf"))
        self.release_label.setText(t("hw_release_frames"))
        self.cooldown_label.setText(t("hw_cooldown"))
        self.rule_hint.setText(t("hw_ack_note"))
        self.auto_check.setText(t("hw_auto"))
        self.stop_button.setText(t("hw_stop"))
        self.sim_check.setText(t("hw_simulated"))
        self.event_label.setText(t("hw_event_log"))
        self._refresh_mode_note()
        self._refresh_link_label()

    # =====================================================================
    # 连接
    # =====================================================================

    def _config(self) -> RuleEngine.RuleConfig:
        return RuleEngine.RuleConfig(
            target_class=str(self.target_combo.currentData() or ""),
            trigger_confidence=float(self.trigger_spin.value()),
            confirm_count=int(self.confirm_spin.value()),
            exit_confidence=float(self.exit_spin.value()),
            release_frames=int(self.release_spin.value()),
            cooldown_ms=int(self.cooldown_spin.value()),
        )

    def on_connect(self):
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.information(self, self.tr.text("hw_title"),
                                    self.tr.text("hw_device_ip"))
            return
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            QMessageBox.information(self, self.tr.text("hw_title"),
                                    self.tr.text("error_port_invalid"))
            return

        if self.sim_check.isChecked():
            # 模拟设备：不联网，仅验证软件链路
            from pvl_hardware import SimulatedDevice
            sim = SimulatedDevice()
            self._sim = sim
            counter = {"n": 0}

            def sender(action, target):
                counter["n"] += 1
                return sim.handle(_cmd(counter["n"], action, target))

            self.adapter = None
            self.controller = HardwareController(
                _NullAdapter(host, port), self._config(), sender=sender)
            self._append_event("模拟设备已就绪（仅软件链路）")
            self._set_connected(True, simulated=True)
            return

        adapter = DeviceAdapter(host=host, port=port)
        self.adapter = adapter
        self.controller = HardwareController(adapter, self._config())
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        def query():
            event = adapter.send(ACTION_STATUS, "led0")
            self._connection_result.emit(adapter, event)
        threading.Thread(target=query, daemon=True).start()

    def _on_connection_result(self, adapter, event):
        if adapter is self.adapter:
            self._on_status(event)

    def _on_status(self, event):
        if event.status == STATUS_FAILED:
            self._append_event(
                self.tr.text("hw_error", error=event.message))
            self._set_connected(False)
            return
        self._set_connected(True)

    def on_disconnect(self):
        if self.adapter is not None:
            self.adapter.disconnect()
        self.adapter = None
        self.controller = None
        self._set_connected(False)
        self._append_event(self.tr.text("hw_disconnected"))

    def _set_connected(self, connected: bool, simulated: bool = False):
        self.led_on_button.setEnabled(connected)
        self.led_off_button.setEnabled(connected)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self._connected = connected
        self._simulated = simulated
        self._refresh_link_label()
        if not connected:
            self.auto_check.setChecked(False)
            self.auto_check.setEnabled(False)
            self.stop_button.setEnabled(False)
        else:
            self.auto_check.setEnabled(True)

    def _refresh_link_label(self):
        connected = getattr(self, "_connected", False)
        simulated = getattr(self, "_simulated", False)
        if connected:
            text = self.tr.text("hw_connected")
            if simulated:
                text += f"（{self.tr.text('hw_simulated')}）"
        else:
            text = self.tr.text("hw_disconnected")
        self.link_label.setText(f"{self.tr.text('hw_status')}: {text}")

    # =====================================================================
    # 手动 / 自动
    # =====================================================================

    def on_manual(self, action: str):
        controller = self.controller
        if controller is None:
            QMessageBox.information(self, self.tr.text("hw_title"),
                                    self.tr.text("hw_not_connected"))
            return
        adapter = self.adapter
        if adapter is None:
            from pvl_hardware import Command, CommandEvent, _now_ms
            now = _now_ms()
            feedback = controller._send(action, controller.config.target)
            event = CommandEvent(
                command=Command(request_id=feedback.request_id, target=controller.config.target, action=action),
                status=feedback.status, sent_at_ms=now, confirmed_at_ms=_now_ms(),
                message=feedback.message)
            self._append_event(self._format_event(event))
            return
        def send():
            event = adapter.send(action, controller.config.target)
            self._manual_result.emit(adapter, event)
        threading.Thread(target=send, daemon=True).start()

    def _on_manual_result(self, adapter, event):
        if adapter is self.adapter:
            self._append_event(self._format_event(event))

    def on_auto_toggled(self, enabled: bool):
        controller = self.controller
        if enabled and controller is None:
            QMessageBox.information(self, self.tr.text("hw_title"),
                                    self.tr.text("hw_not_connected"))
            self.auto_check.setChecked(False)
            return
        if enabled and not getattr(self, "_connected", False):
            QMessageBox.information(self, self.tr.text("hw_title"),
                                    self.tr.text("hw_need_manual"))
            self.auto_check.setChecked(False)
            return
        if enabled and self.prediction_provider is None:
            # 没有视觉结果来源时，自动控制不可能触发。
            # 明确说明，而不是留一个看似可用、实际永不动作的开关。
            QMessageBox.information(self, self.tr.text("hw_title"),
                                    self.tr.text("hw_no_prediction_source"))
            self.auto_check.setChecked(False)
            return
        if controller is not None:
            controller.set_auto(enabled)
        self.stop_button.setEnabled(enabled)
        self.auto_check.setText(
            self.tr.text("hw_auto_on") if enabled else self.tr.text("hw_auto"))
        self.auto_state_changed.emit(enabled)

    def on_stop_control(self):
        if self.controller is not None:
            self.controller.set_auto(False)
        self.auto_check.setChecked(False)
        self.auto_check.setText(self.tr.text("hw_auto"))
        self.stop_button.setEnabled(False)
        self._append_event(self.tr.text("hw_stopped"))
        self.auto_state_changed.emit(False)

    # =====================================================================
    # 推理结果接入（由主窗口调用）
    # =====================================================================

    def on_prediction(self, label: str, confidence: float,
                      now_ms: int | None = None) -> None:
        """喂一次视觉结果；仅在状态变化时发命令。

        由主窗口在取到新帧时调用。没有 prediction_provider 时不会被调用。
        """
        controller = self.controller
        if controller is None or not controller.auto_enabled:
            return
        output = controller.on_prediction(label, confidence, now_ms=now_ms)
        # 只把"产生了动作"的事件记进界面，避免逐帧刷屏
        if output.should_turn_on or output.should_turn_off:
            action = "led_on" if output.should_turn_on else "led_off"
            state_text = (self.tr.text("hw_rule_triggered") if output.state
                          else self.tr.text("hw_rule_idle"))
            self._append_event(
                f"{self.tr.text('hw_rule_state')}: {state_text} -> {action}")

    def poll_prediction(self) -> None:
        """从 prediction_provider 取一次视觉结果并喂给规则引擎。

        PC 客户端默认没有分类器，因此默认不会产生任何自动动作；
        一旦注入了来源（例如后续接入 PC 侧推理），这里就是唯一的入口。
        """
        if self.prediction_provider is None:
            return
        if self.controller is None or not self.controller.auto_enabled:
            return
        try:
            result = self.prediction_provider()
        except Exception:  # noqa: BLE001 - 取预测失败不能拖垮 UI
            return
        if result is None:
            return
        label, confidence = result
        self.on_prediction(str(label), float(confidence))

    # =====================================================================
    # 事件
    # =====================================================================

    def _append_event(self, text: str):
        from datetime import datetime
        stamp = datetime.now().strftime("%H:%M:%S")
        self._events.append(f"[{stamp}] {text}")
        if len(self._events) > 200:
            self._events = self._events[-200:]
        self.event_list.clear()
        self.event_list.addItems(self._events[-40:])
        self.event_list.scrollToBottom()

    def _format_event(self, event) -> str:
        status = {
            "sent": self.tr.text("hw_cmd_sent"),
            "received": self.tr.text("hw_cmd_received"),
            "executed": self.tr.text("hw_cmd_executed"),
            "failed": self.tr.text("hw_cmd_failed"),
        }.get(event.status, event.status)
        rtt = ""
        if event.confirmed_at_ms is not None:
            rtt = f" ({(event.confirmed_at_ms - event.sent_at_ms)}ms)"
        msg = f" {event.message}" if event.message else ""
        return f"{event.command.action} {event.command.target} -> {status}{rtt}{msg}"

    def events(self) -> list:
        return list(self._events)

    def closeEvent(self, event):
        self.on_disconnect()
        super().closeEvent(event)


class _NullAdapter:
    """模拟设备模式下占位：不发网络请求，命令经 sender 直达 SimulatedDevice。"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def send(self, action, target, params=None, request_id=None):
        from pvl_hardware import Command, CommandEvent, STATUS_SENT, _now_ms
        command = Command(request_id=request_id or "sim", target=target,
                          action=action, params=params or {})
        return CommandEvent(command=command, status=STATUS_SENT,
                            sent_at_ms=_now_ms(),
                            message="模拟设备（未联网）")

    def disconnect(self):
        return None


def _cmd(n: int, action: str, target: str):
    from pvl_hardware import Command
    return Command(request_id=f"sim-{n}", target=target, action=action)
