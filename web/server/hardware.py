"""
PhoneVision Lab Web — 硬件联动服务（真实控制器 + 模拟设备，命令四态）。

职责：连接 ESP32 控制器、发送手动命令、记录事件，并明确区分
"设备已接收"与"设备已执行"。

为什么这样设计：
  - 直接复用 pvl_hardware：DeviceAdapter（HTTP /control）、
    RuleEngine（连续确认 + 滞回 + 冷却）、SimulatedDevice（软件链路演练）。
    与桌面客户端、Android 端同一套协议实现，不在网页里另写一套。
  - 自动控制在网页端不提供开关：网页没有分类结果来源（PC 侧不跑模型），
    自动联动规则在手机端执行。这里只做"手动命令 + 事件记录 + 模拟演练"，
    避免制造一个永远不会动作的假开关。
  - 命令状态严格按回执分级：sent / received / executed / failed。
    没有收到 executed 回执时，界面只能显示"已接收"，绝不显示"已执行"。
  - 舵机、电机等动作协议里预留了（ACTION_SERVO_SET）但未验证，
    服务端直接拒绝，不暴露成可用按钮。
"""
from __future__ import annotations

import os
import sys
import threading
import time

_PC_CLIENT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from .util import ApiError, safe_int, validate_private_host  # noqa: E402

# 网页端允许的动作：LED 开/关/亮度/停止/查询状态。
# 舵机（servo_set）等未验证动作不在这里出现。
WEB_ACTIONS = ["led_on", "led_off", "set_led", "stop", "status"]

ACTION_LABELS = {
    "led_on": "LED 开",
    "led_off": "LED 关",
    "set_led": "LED 亮度",
    "stop": "停止",
    "status": "查询状态",
}

STATUS_LABELS = {
    "sent": "已发送",
    "received": "已接收",
    "executed": "已执行",
    "failed": "失败",
}


class HardwareService:
    """控制器连接 + 命令发送 + 事件记录。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._adapter = None
        self._simulated = None
        self._connected = False
        self._host = ""
        self._port = 8081
        self._target = "led0"
        self._events: list[dict] = []
        self._counter = 0
        self._verified_at = ""     # 最近一次手动验证时间（灯开/关均确认）
        self._led_state_known = False
        self._led_on = None

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    def connect(self, host: str, port: int = 8081, simulated: bool = False) -> dict:
        """连接控制器：host 只允许局域网私网 IP，端口 1-65535。

        服务端会代发 HTTP /control，不能让请求体指定任意目标（SSRF）。
        """
        port = safe_int(port, 8081, minimum=1, maximum=65535)
        host = "" if simulated else validate_private_host(host, "控制器 IP 地址")

        if simulated:
            from pvl_hardware import SimulatedDevice
            with self._lock:
                self._simulated = SimulatedDevice()
                self._adapter = None
                self._connected = True
                self._host = "simulated"
                self._port = 0
                self._counter = 0
            self._append_event("模拟设备已就绪（仅验证软件链路，不驱动真实硬件）",
                               "info")
            return self.status()

        from pvl_hardware import DeviceAdapter
        adapter = DeviceAdapter(host=host, port=int(port))
        # 只读查询：只验证链路，不动执行器
        event = adapter.send("status", self._target)
        if event.status == "failed":
            raise ApiError("device_error",
                           f"无法连接控制器: {event.message}")
        with self._lock:
            self._adapter = adapter
            self._simulated = None
            self._connected = True
            self._host = host
            self._port = int(port)
            self._counter = 0
        self._append_event(
            f"已连接控制器 {host}:{int(port)}（查询状态回执: "
            f"{STATUS_LABELS.get(event.status, event.status)}）", "info")
        return self.status()

    def disconnect(self) -> dict:
        with self._lock:
            adapter = self._adapter
            self._adapter = None
            self._simulated = None
            self._connected = False
            self._host = ""
            self._port = 0
            # 断开后不再声称知道 LED 当前状态（无法再查询）
            self._led_state_known = False
        if adapter is not None:
            adapter.disconnect()
        self._append_event("已断开控制器连接", "info")
        return self.status()

    def status(self) -> dict:
        with self._lock:
            return {
                "connected": self._connected,
                "simulated": self._simulated is not None,
                "host": self._host,
                "port": self._port,
                "target": self._target,
                "verified_at": self._verified_at,
                "led_state_known": self._led_state_known,
                "led_on": self._led_on,
                "auto_control": "phone_only",
                "actions": [
                    {"id": a, "label": ACTION_LABELS[a]} for a in WEB_ACTIONS
                ],
            }

    # ------------------------------------------------------------------
    # 命令
    # ------------------------------------------------------------------

    def send(self, action: str, params: dict | None = None) -> dict:
        if action not in WEB_ACTIONS:
            raise ApiError("bad_request",
                           f"网页端不支持该动作: {action}（舵机/电机等尚未验证）")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ApiError("bad_request", "params 必须是对象")
        params = dict(params)
        if action == "set_led":
            # 亮度来自请求体：非法值给 400，而不是在 LED 状态计算时抛 500。
            params["brightness"] = safe_int(params.get("brightness", 0), 0,
                                            minimum=0, maximum=255)
        with self._lock:
            if not self._connected:
                raise ApiError("not_connected",
                               "尚未连接控制器：请先填写 ESP32 地址并连接，或使用模拟设备演练")
            adapter = self._adapter
            simulated = self._simulated
            self._counter += 1
            counter = self._counter

        if simulated is not None:
            from pvl_hardware import Command
            command = Command(request_id=f"sim-{counter}", target=self._target,
                              action=action, params=params or {})
            feedback = simulated.handle(command)
            rtt = None
            if feedback.executed_at_ms is not None:
                rtt = None  # 模拟设备不上报真实往返耗时
            record = {
                "time": time.strftime("%H:%M:%S"),
                "action": action,
                "action_label": ACTION_LABELS.get(action, action),
                "target": self._target,
                "status": feedback.status,
                "status_label": STATUS_LABELS.get(feedback.status, feedback.status),
                "rtt_ms": rtt,
                "message": feedback.message or "模拟设备（未联网）",
                "simulated": True,
            }
            self._append_event_record(record)
            if action in ("led_on", "led_off", "set_led") and feedback.status == "executed":
                self._mark_verified()
                self._led_state_known = True
                self._led_on = (action == "led_on"
                                or (action == "set_led"
                                    and params.get("brightness", 0) > 0))
            return record

        event = adapter.send(action, self._target, params=params or {})
        rtt = None
        if event.confirmed_at_ms is not None:
            rtt = event.confirmed_at_ms - event.sent_at_ms
        record = {
            "time": time.strftime("%H:%M:%S"),
            "action": action,
            "action_label": ACTION_LABELS.get(action, action),
            "target": self._target,
            "status": event.status,
            "status_label": STATUS_LABELS.get(event.status, event.status),
            "rtt_ms": rtt,
            "message": event.message,
            "simulated": False,
        }
        self._append_event_record(record)
        if action in ("led_on", "led_off", "set_led"):
            if event.status == "executed":
                self._mark_verified()
                self._led_state_known = True
                self._led_on = (action == "led_on"
                                or (action == "set_led"
                                    and params.get("brightness", 0) > 0))
            elif event.status == "received":
                # 设备只确认接收：不更新 LED 状态，界面提示需目视确认
                self._led_state_known = False
        return record

    def _mark_verified(self) -> None:
        self._verified_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def _append_event_record(self, record: dict) -> None:
        with self._lock:
            self._events.append(record)
            if len(self._events) > 300:
                self._events = self._events[-300:]

    def _append_event(self, text: str, kind: str = "info") -> None:
        with self._lock:
            self._events.append({
                "time": time.strftime("%H:%M:%S"),
                "action": "",
                "action_label": text,
                "target": "",
                "status": kind,
                "status_label": {"info": "信息", "warning": "注意",
                                 "error": "错误"}.get(kind, kind),
                "rtt_ms": None,
                "message": "",
                "simulated": self._simulated is not None,
            })

    def events(self) -> list:
        with self._lock:
            return list(reversed(self._events[-100:]))
