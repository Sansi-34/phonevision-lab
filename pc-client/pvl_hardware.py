"""
PhoneVision Lab — 硬件交互（PC 侧）：规则引擎 + 设备适配器 + 模拟设备。

职责：把"视觉结果 -> 是否产生动作 -> 发命令 -> 收反馈"这条链路在 PC 端
完整实现一遍，与 Android 端 [RuleEngine / DeviceAdapter / ControlProtocol]
语义一致。用于：
  - 没有真机时验证规则与协议逻辑（模拟验证，不等于真机验收）；
  - 电脑侧调试控制器（首阶段若只能电脑中转，这里就是中转端）。

为什么这样设计：
  - 规则引擎是纯逻辑，无网络、无 GUI：可离线单测，也可被 Android 端
    逐行对照（两边参数名与默认值一致，避免"电脑上调好的参数手机上不一样"）。
  - 模拟设备明确标注：它只验证软件链路，绝不等于真实硬件验收通过。
  - 协议与 Android 端 ControlProtocol 完全一致（同一个 JSON 结构）。

初学者调试观察点：
  - 自动控制开了但没动作：先确认 device 已连接、目标类别与模型标签一致。
  - 动作重复：确认用了 requestId 去重。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# 协议版本：必须与 Android ControlProtocol.VERSION 一致。
PROTOCOL_VERSION = 1

DEFAULT_PORT = 8081

# 动作类型（与 Android 端一致）。
ACTION_LED_ON = "led_on"
ACTION_LED_OFF = "led_off"
ACTION_SET_LED = "set_led"
ACTION_SERVO_SET = "servo_set"
ACTION_STOP = "stop"
ACTION_STATUS = "status"

# 允许自动重试的幂等动作（与 Android 端一致）。
RETRYABLE_ACTIONS = {ACTION_LED_ON, ACTION_LED_OFF, ACTION_SET_LED}

ALL_ACTIONS = [
    ACTION_LED_ON, ACTION_LED_OFF, ACTION_SET_LED,
    ACTION_SERVO_SET, ACTION_STOP, ACTION_STATUS,
]

# 命令状态。
STATUS_SENT = "sent"
STATUS_RECEIVED = "received"
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class Command:
    """一条控制命令（与 Android ControlProtocol.Command 同构）。"""

    request_id: str
    target: str
    action: str
    params: dict = field(default_factory=dict)
    protocol_version: int = PROTOCOL_VERSION

    def to_json(self) -> str:
        payload = {
            "v": self.protocol_version,
            "requestId": self.request_id,
            "target": self.target,
            "action": self.action,
        }
        if self.params:
            payload["params"] = self.params
        return json.dumps(payload, ensure_ascii=False)


@dataclass(frozen=True)
class Feedback:
    """控制器反馈（与 Android ControlProtocol.Feedback 同构）。"""

    request_id: str
    status: str
    executed_at_ms: int | None = None
    message: str = ""

    @classmethod
    def from_json(cls, text: str) -> "Feedback | None":
        try:
            data = json.loads(text)
        except ValueError:
            return None
        status = str(data.get("status", "")).lower()
        # "error" 是 Android ControlProtocol 已接受的别名（见 ControlProtocol.kt），
        # 这里必须同样归一，否则同一份控制器反馈在两端会被判成不同状态。
        if status == "error":
            status = STATUS_FAILED
        if status not in (STATUS_RECEIVED, STATUS_EXECUTED, STATUS_FAILED):
            # 未知状态一律拒绝：不能把看不懂的回执当成"已确认"，
            # 否则规则引擎会据此误触发硬件动作。
            return None
        return cls(
            request_id=str(data.get("requestId", "")),
            status=status,
            executed_at_ms=(int(data["executedAtMs"])
                            if data.get("executedAtMs") is not None else None),
            message=str(data.get("message", "")),
        )


@dataclass(frozen=True)
class CommandEvent:
    """一条命令的完整生命周期事件（PC 侧记录/导出用）。"""

    command: Command
    status: str
    sent_at_ms: int                 # 单调时钟（time.monotonic 转毫秒）
    confirmed_at_ms: int | None = None
    device_executed_at_ms: int | None = None
    message: str = ""


def _now_ms() -> int:
    """本机单调时钟毫秒。绝不与手机时间戳相减。"""
    return int(time.monotonic() * 1000)


class DeviceAdapter:
    """局域网 HTTP 设备适配器（与 Android 端语义一致）。"""

    def __init__(self, host: str, port: int = DEFAULT_PORT,
                 timeout_ms: int = 2000, max_retries: int = 2):
        self.host = host
        self.port = port
        self.timeout = max(0.1, timeout_ms / 1000.0)
        self.max_retries = max_retries
        self._counter = 0
        self._lock = threading.Lock()
        self._sent: dict = {}

    def next_request_id(self) -> str:
        with self._lock:
            self._counter += 1
            n = self._counter
        return f"req-{int(time.time() * 1000):x}-{n:x}"

    def send(self, action: str, target: str, params: dict | None = None,
             request_id: str | None = None) -> CommandEvent:
        """同步发送一条命令（在后台线程调用）。"""
        rid = request_id or self.next_request_id()
        command = Command(request_id=rid, target=target, action=action,
                          params=params or {})
        with self._lock:
            if rid in self._sent:
                return CommandEvent(
                    command=command, status=STATUS_SENT,
                    sent_at_ms=_now_ms(), message="重复请求（已去重）")
            self._sent[rid] = command

        retryable = action in RETRYABLE_ACTIONS
        attempts = 0
        last_error = ""
        sent_at = _now_ms()

        while attempts <= self.max_retries:
            attempts += 1
            try:
                feedback = self._post(command)
                if feedback is not None and feedback.request_id == rid:
                    return CommandEvent(
                        command=command, status=feedback.status,
                        sent_at_ms=sent_at, confirmed_at_ms=_now_ms(),
                        device_executed_at_ms=feedback.executed_at_ms,
                        message=feedback.message)
                last_error = "控制器未返回有效反馈"
            except Exception as e:  # noqa: BLE001 - 统一转成失败事件
                last_error = str(e)
            if not retryable or attempts > self.max_retries:
                break

        return CommandEvent(command=command, status=STATUS_FAILED,
                            sent_at_ms=sent_at,
                            message=f"命令失败: {last_error or '未知原因'}")

    def _post(self, command: Command) -> Feedback | None:
        url = f"http://{self.host}:{self.port}/control"
        body = command.to_json().encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        return Feedback.from_json(text)

    def query_status(self) -> Feedback | None:
        """GET /status（只读，用于连接前验证链路）。"""
        try:
            url = f"http://{self.host}:{self.port}/status"
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return Feedback.from_json(
                    resp.read().decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 - 查询失败按"未连接"处理
            return None

    def disconnect(self) -> None:
        """断开：清理去重缓存。不缓存待发送命令，因此断连期间不会重放。"""
        with self._lock:
            self._sent.clear()


class RuleEngine:
    """规则引擎（与 Android RuleEngine 完全同构）。

    三重稳定机制：连续确认 + 触发/退出滞回 + 动作冷却。
    只在状态变化时产生动作。
    """

    @dataclass(frozen=True)
    class RuleConfig:
        target_class: str
        trigger_confidence: float = 0.75
        confirm_count: int = 3
        exit_confidence: float = 0.45
        release_frames: int = 5
        cooldown_ms: int = 2000
        on_action: str = ACTION_LED_ON
        off_action: str = ACTION_LED_OFF
        target: str = "led0"

        def validate(self) -> list:
            problems = []
            if not self.target_class:
                problems.append("目标类别不能为空")
            if not (0.0 < self.trigger_confidence <= 1.0):
                problems.append("触发置信度必须在 (0, 1] 内")
            if not (0.0 <= self.exit_confidence < self.trigger_confidence):
                problems.append("退出置信度必须小于触发置信度（否则没有滞回效果）")
            if self.confirm_count < 1:
                problems.append("连续确认次数至少为 1")
            if self.release_frames < 1:
                problems.append("退出帧数至少为 1")
            if self.cooldown_ms < 0:
                problems.append("冷却时间不能为负")
            return problems

    @dataclass(frozen=True)
    class RuleOutput:
        state: bool
        should_turn_on: bool = False
        should_turn_off: bool = False
        confirm_streak: int = 0
        since_last_action_ms: int = 0

    def __init__(self, config: RuleConfig):
        self.config = config
        self._state = False
        self._confirm = 0
        self._release = 0
        self._last_action_ms: int | None = None   # None = 从未动作过
        self._last_output = self.RuleOutput(state=False)

    def _cooled_down(self, now_ms: int) -> bool:
        """是否已过冷却期。

        从未动作过（_last_action_ms is None）时视为"已冷却"：
        冷却是用来防止"动作后立刻反复动作"的，不该拦住第一次触发。
        """
        if self._last_action_ms is None:
            return True
        return (now_ms - self._last_action_ms) >= self.config.cooldown_ms

    def current_state(self) -> bool:
        return self._state

    def last_output(self) -> "RuleEngine.RuleOutput":
        return self._last_output

    def update(self, label: str, confidence: float,
               now_ms: int | None = None) -> RuleOutput:
        """喂入一次推理结果（类别名 + 置信度），返回判定。"""
        now = _now_ms() if now_ms is None else int(now_ms)
        cfg = self.config
        is_target = label == cfg.target_class
        above = is_target and confidence >= cfg.trigger_confidence
        still = is_target and confidence >= cfg.exit_confidence

        if not self._state:
            self._confirm = self._confirm + 1 if above else 0
            self._release = 0
            ready = self._confirm >= cfg.confirm_count
            cooled = self._cooled_down(now)
            turn_on = ready and cooled
            if turn_on:
                self._state = True
                self._last_action_ms = now
                self._confirm = 0
            last = self._last_action_ms
            self._last_output = self.RuleOutput(
                state=self._state, should_turn_on=turn_on,
                confirm_streak=self._confirm,
                since_last_action_ms=(0 if last is None
                                      else max(0, now - last)))
        else:
            self._release = self._release + 1 if not still else 0
            self._confirm = 0
            should = self._release >= cfg.release_frames
            cooled = self._cooled_down(now)
            turn_off = should and cooled
            if turn_off:
                self._state = False
                self._last_action_ms = now
                self._release = 0
            last = self._last_action_ms
            self._last_output = self.RuleOutput(
                state=self._state, should_turn_off=turn_off, confirm_streak=0,
                since_last_action_ms=(0 if last is None
                                      else max(0, now - last)))
        return self._last_output

    def reset(self) -> None:
        self._state = False
        self._confirm = 0
        self._release = 0
        self._last_action_ms = None
        self._last_output = self.RuleOutput(state=False)


class SimulatedDevice:
    """模拟设备（明确标注：仅验证软件链路，不等于真实硬件验收）。

    行为：
      - 记录收到的命令与最终状态；
      - 对每个命令都回 "executed"（模拟一个"能确认动作完成"的设备）；
      - 可注入延迟/失败，用于测试超时与重试路径。
    """

    def __init__(self, latency_ms: int = 0, fail_rate: float = 0.0):
        self.latency_ms = latency_ms
        self.fail_rate = fail_rate
        self.led_on = False
        self.commands: list = []
        self._seen: set = set()

    def handle(self, command: Command) -> Feedback:
        import random
        self.commands.append(command)
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)
        if command.request_id in self._seen:
            return Feedback(command.request_id, STATUS_RECEIVED,
                            message="duplicate ignored")
        self._seen.add(command.request_id)

        if self.fail_rate and random.random() < self.fail_rate:
            return Feedback(command.request_id, STATUS_FAILED,
                            message="simulated failure")

        if command.action == ACTION_LED_ON:
            self.led_on = True
        elif command.action == ACTION_LED_OFF:
            self.led_on = False
        elif command.action == ACTION_SET_LED:
            brightness = int((command.params or {}).get("brightness", 255))
            self.led_on = brightness > 0
        elif command.action == ACTION_STOP:
            self.led_on = False
        elif command.action == ACTION_STATUS:
            return Feedback(command.request_id, STATUS_RECEIVED)
        return Feedback(command.request_id, STATUS_EXECUTED,
                        executed_at_ms=_now_ms())


class HardwareController:
    """把规则引擎与设备适配器编排起来的门面（PC 侧与手机侧对应）。

    sender 可注入：默认走 DeviceAdapter（局域网 HTTP）；测试可注入
    SimulatedDevice，从而在不联网的情况下验证完整编排逻辑。
    """

    def __init__(self, adapter: DeviceAdapter, config: RuleEngine.RuleConfig,
                 sender=None):
        self.adapter = adapter
        self.config = config
        self.engine = RuleEngine(config)
        self.events: list = []
        self.auto_enabled = False
        # sender(action, target) -> Feedback；缺省用 adapter.send
        self._sender = sender

    def _send(self, action: str, target: str):
        if self._sender is not None:
            return self._sender(action, target)
        event = self.adapter.send(action, target)
        self.events.append(event)
        return event

    def set_auto(self, enabled: bool) -> None:
        """开启/关闭自动控制。关闭时复位规则状态，不再产生新自动动作。"""
        self.auto_enabled = bool(enabled)
        self.engine.reset()

    def on_prediction(self, label: str, confidence: float,
                      now_ms: int | None = None) -> RuleEngine.RuleOutput:
        """喂一次推理结果；仅在状态变化时发命令。"""
        output = self.engine.update(label, confidence, now_ms=now_ms)
        if not self.auto_enabled:
            return output
        if output.should_turn_on:
            self._send(self.config.on_action, self.config.target)
        elif output.should_turn_off:
            self._send(self.config.off_action, self.config.target)
        return output

    def manual(self, action: str) -> CommandEvent:
        """手动动作（用于先验证设备再开自动控制）。"""
        event = self.adapter.send(action, self.config.target)
        self.events.append(event)
        return event
