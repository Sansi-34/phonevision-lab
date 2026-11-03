"""
PhoneVision Lab Web — 硬件联动服务测试（命令四态 / 模拟设备 / 边界）。

职责：验证
  - 未连接时发送命令被拒绝（不产生"假执行"）；
  - 模拟设备路径下命令四态可见，且明确标注"模拟"；
  - 网页端拒绝未验证动作（舵机等），不暴露成可用按钮；
  - 断开连接后不再发送命令。
不连接真实 ESP32。
"""
import os
import shutil
import sys
import tempfile
import unittest

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WEB not in sys.path:
    sys.path.insert(0, _WEB)

_REPO = os.path.dirname(_WEB)
_PC_CLIENT = os.path.join(_REPO, "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from server.util import ApiError  # noqa: E402


class HardwareServiceTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pvl-web-hw-")
        os.environ["PVL_DATA_DIR"] = self.tmp
        from server.hardware import HardwareService
        self.service = HardwareService()

    def tearDown(self):
        self.service.disconnect()
        os.environ.pop("PVL_DATA_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 初始状态 ----

    def test_initial_status_is_disconnected(self):
        status = self.service.status()
        self.assertFalse(status["connected"])
        self.assertFalse(status["simulated"])
        self.assertIsNone(status["led_on"])
        self.assertFalse(status["led_state_known"])
        self.assertEqual(status["verified_at"], "")
        self.assertEqual(status["auto_control"], "phone_only")

    def test_connect_rejects_public_or_loopback_host(self):
        """控制器连接会代发 HTTP 请求：只允许私网 IP，拒绝公网/回环。"""
        for host in ("8.8.8.8", "example.com", "127.0.0.1", "0.0.0.0"):
            with self.subTest(host=host):
                with self.assertRaises(ApiError) as ctx:
                    self.service.connect(host, 8081)
                self.assertEqual(ctx.exception.code, "bad_request")
        self.assertFalse(self.service.status()["connected"])

    def test_connect_rejects_invalid_port(self):
        with self.assertRaises(ApiError):
            self.service.connect("192.168.1.50", 70000)

    def test_send_without_connection_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            self.service.send("led_on")
        self.assertEqual(ctx.exception.code, "not_connected")
        self.assertIn("尚未连接", ctx.exception.message)

    def test_events_initially_empty(self):
        self.assertEqual(self.service.events(), [])

    # ---- 模拟设备 ----

    def test_simulated_device_marks_events_as_simulated(self):
        status = self.service.connect("", simulated=True)
        self.assertTrue(status["connected"])
        self.assertTrue(status["simulated"])
        record = self.service.send("led_on")
        self.assertTrue(record["simulated"])
        self.assertEqual(record["action"], "led_on")
        self.assertEqual(record["status_label"], "已执行")
        events = self.service.events()
        self.assertTrue(events[0]["simulated"])

    def test_simulated_led_state_tracked(self):
        self.service.connect("", simulated=True)
        self.service.send("led_on")
        status = self.service.status()
        self.assertTrue(status["led_on"])
        self.assertTrue(status["led_state_known"])
        self.service.send("led_off")
        self.assertFalse(self.service.status()["led_on"])

    def test_simulated_brightness_zero_means_off(self):
        self.service.connect("", simulated=True)
        self.service.send("set_led", {"brightness": 0})
        self.assertFalse(self.service.status()["led_on"])
        self.service.send("set_led", {"brightness": 128})
        self.assertTrue(self.service.status()["led_on"])

    def test_brightness_must_be_numeric_in_range(self):
        self.service.connect("", simulated=True)
        for value in ("abc", -1, 256):
            with self.subTest(value=value):
                with self.assertRaises(ApiError) as ctx:
                    self.service.send("set_led", {"brightness": value})
                self.assertEqual(ctx.exception.code, "bad_request")

    def test_verified_at_recorded_only_on_executed(self):
        self.service.connect("", simulated=True)
        self.assertEqual(self.service.status()["verified_at"], "")
        self.service.send("led_on")
        self.assertTrue(self.service.status()["verified_at"])

    def test_status_action_does_not_mark_verified(self):
        self.service.connect("", simulated=True)
        self.service.send("status")
        self.assertEqual(self.service.status()["verified_at"], "")

    # ---- 动作边界 ----

    def test_web_rejects_servo_action(self):
        """舵机等未验证动作：网页端必须拒绝，不能出现可用按钮。"""
        self.service.connect("", simulated=True)
        with self.assertRaises(ApiError) as ctx:
            self.service.send("servo_set", {"angle": 90})
        self.assertEqual(ctx.exception.code, "bad_request")
        self.assertIn("尚未验证", ctx.exception.message)

    def test_web_rejects_unknown_action(self):
        self.service.connect("", simulated=True)
        with self.assertRaises(ApiError):
            self.service.send("motor_run")

    def test_only_led_actions_advertised(self):
        status = self.service.status()
        action_ids = {a["id"] for a in status["actions"]}
        self.assertEqual(action_ids, {"led_on", "led_off", "set_led", "stop",
                                      "status"})
        for action in status["actions"]:
            self.assertTrue(action["label"])

    # ---- 断开 ----

    def test_disconnect_stops_sending(self):
        self.service.connect("", simulated=True)
        self.service.disconnect()
        with self.assertRaises(ApiError):
            self.service.send("led_on")

    def test_disconnect_clears_state(self):
        self.service.connect("", simulated=True)
        self.service.send("led_on")
        self.service.disconnect()
        status = self.service.status()
        self.assertFalse(status["connected"])
        self.assertFalse(status["simulated"])
        # 断开后不清空历史 LED 记录（那是已发生的事实），但不再声称已知当前状态
        self.assertFalse(status["led_state_known"])

    # ---- 事件记录 ----

    def test_events_are_newest_first_and_capped(self):
        self.service.connect("", simulated=True)
        for _ in range(20):
            self.service.send("led_on")
        events = self.service.events()
        # 20 条命令 + 1 条"模拟设备已就绪" = 21 条，界面只显示最近 100 条
        self.assertEqual(len(events), 21)
        for event in events:
            self.assertTrue(event["time"])
            self.assertTrue(event["status_label"])

    def test_event_records_rtt_field(self):
        self.service.connect("", simulated=True)
        record = self.service.send("led_on")
        # 模拟设备不上报真实往返耗时（本地执行），字段存在且为 None
        self.assertIn("rtt_ms", record)
        self.assertIsNone(record["rtt_ms"])
        self.assertIn("message", record)
        self.assertIn("模拟设备", record["message"])


if __name__ == "__main__":
    unittest.main()
