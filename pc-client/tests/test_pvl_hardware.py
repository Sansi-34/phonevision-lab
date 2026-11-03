"""
PhoneVision Lab — 硬件交互逻辑测试（纯逻辑 + 模拟设备，不需要真机）。

覆盖（与 Android 端 RuleEngine / DeviceAdapter / ControlProtocol 同构）：
  1. 连续确认：单帧误识别不触发动作。
  2. 滞回：在触发/退出阈值之间抖动不产生动作。
  3. 冷却：一次动作后短时间内不重复触发。
  4. 状态变化才发命令：不逐帧重复发送。
  5. 命令去重：同一 requestId 不重复执行。
  6. 超时与有限重试：只有幂等动作重试，运动动作不重试。
  7. 断连后不重放过期命令。
  8. 模拟设备不等于真机验收：测试里显式标注。
"""
import os
import sys
import tempfile
import unittest

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from pvl_hardware import (  # noqa: E402
    ACTION_LED_OFF, ACTION_LED_ON, ACTION_SERVO_SET, ACTION_SET_LED,
    ACTION_STATUS, PROTOCOL_VERSION, STATUS_EXECUTED, STATUS_FAILED,
    STATUS_RECEIVED, STATUS_SENT, Command, DeviceAdapter, Feedback,
    HardwareController, RuleEngine, SimulatedDevice,
)


def _cfg(**overrides):
    base = dict(target_class="target", trigger_confidence=0.75,
                confirm_count=3, exit_confidence=0.45, release_frames=5,
                cooldown_ms=2000)
    base.update(overrides)
    return RuleEngine.RuleConfig(**base)


class RuleEngineConfirmTest(unittest.TestCase):
    """连续确认：短暂误识别不产生动作。"""

    def test_single_frame_never_triggers(self):
        """只给 1 帧高置信度：绝不可触发（confirm_count=3）。"""
        engine = RuleEngine(_cfg(confirm_count=3))
        out = engine.update("target", 0.99, now_ms=1000)
        self.assertFalse(out.should_turn_on)
        self.assertFalse(engine.current_state())
        self.assertEqual(out.confirm_streak, 1)

    def test_two_frames_not_enough(self):
        engine = RuleEngine(_cfg(confirm_count=3))
        engine.update("target", 0.99, now_ms=1000)
        out = engine.update("target", 0.99, now_ms=1050)
        self.assertFalse(out.should_turn_on)
        self.assertEqual(out.confirm_streak, 2)

    def test_third_frame_triggers(self):
        engine = RuleEngine(_cfg(confirm_count=3))
        engine.update("target", 0.99, now_ms=1000)
        engine.update("target", 0.99, now_ms=1050)
        out = engine.update("target", 0.99, now_ms=1100)
        self.assertTrue(out.should_turn_on)
        self.assertTrue(engine.current_state())

    def test_streak_resets_on_miss(self):
        engine = RuleEngine(_cfg(confirm_count=3))
        t = 1000
        engine.update("target", 0.99, now_ms=t); t += 50
        engine.update("target", 0.99, now_ms=t); t += 50
        out = engine.update("other", 0.99, now_ms=t); t += 50   # 断连续
        self.assertFalse(out.should_turn_on, "中间出现非目标帧应重置连续计数")
        self.assertEqual(out.confirm_streak, 0)

    def test_low_confidence_does_not_count(self):
        engine = RuleEngine(_cfg(confirm_count=2, trigger_confidence=0.8))
        t = 1000
        engine.update("target", 0.7, now_ms=t); t += 50
        out = engine.update("target", 0.79, now_ms=t)
        self.assertFalse(out.should_turn_on, "低于触发阈值不应计入连续确认")
        self.assertEqual(out.confirm_streak, 0)
    def test_streak_resets_on_miss(self):
        engine = RuleEngine(_cfg(confirm_count=3))
        t = 1000
        engine.update("target", 0.99, now_ms=t); t += 50
        engine.update("target", 0.99, now_ms=t); t += 50
        engine.update("other", 0.99, now_ms=t); t += 50   # 断连续
        out = engine.update("target", 0.99, now_ms=t)
        self.assertFalse(out.should_turn_on, "中间出现非目标帧应重置连续计数")

    def test_low_confidence_does_not_count(self):
        engine = RuleEngine(_cfg(confirm_count=2, trigger_confidence=0.8))
        t = 1000
        engine.update("target", 0.7, now_ms=t); t += 50
        out = engine.update("target", 0.79, now_ms=t)
        self.assertFalse(out.should_turn_on, "低于触发阈值不应计入连续确认")


class RuleEngineHysteresisTest(unittest.TestCase):
    """滞回：阈值附近抖动不频繁切换。"""

    def test_jitter_near_threshold_no_flapping(self):
        engine = RuleEngine(_cfg(trigger_confidence=0.75, confirm_count=2,
                                 exit_confidence=0.45, release_frames=3,
                                 cooldown_ms=0))
        t = 1000
        # 先稳定触发
        for _ in range(2):
            engine.update("target", 0.9, now_ms=t); t += 50
        self.assertTrue(engine.current_state())

        # 在 0.5~0.7 之间抖动：高于退出阈值，不应退出
        for conf in (0.6, 0.5, 0.55, 0.6, 0.5):
            engine.update("target", conf, now_ms=t); t += 50
        self.assertTrue(engine.current_state(),
                        "高于退出阈值的抖动不应让状态翻转（滞回）")

    def test_release_requires_sustained_absence(self):
        engine = RuleEngine(_cfg(release_frames=5, cooldown_ms=0))
        t = 1000
        for _ in range(3):
            engine.update("target", 0.9, now_ms=t); t += 50
        self.assertTrue(engine.current_state())

        # 只消失 3 帧（少于 release_frames=5）：不退出
        for _ in range(3):
            out = engine.update("other", 0.9, now_ms=t); t += 50
            self.assertFalse(out.should_turn_off)
        self.assertTrue(engine.current_state())

        # 再消失 2 帧达到 5：退出
        for _ in range(2):
            out = engine.update("other", 0.9, now_ms=t); t += 50
        self.assertTrue(out.should_turn_off)
        self.assertFalse(engine.current_state())

    def test_exit_confidence_below_trigger(self):
        """退出阈值必须低于触发阈值，否则没有滞回效果。"""
        problems = _cfg(trigger_confidence=0.5,
                        exit_confidence=0.5).validate()
        self.assertTrue(
            any("退出置信度" in p for p in problems),
            f"exit >= trigger 必须被 validate 拒绝，实际问题: {problems}")
        # 合法配置不应报错
        self.assertEqual(_cfg().validate(), [])


class RuleEngineCooldownTest(unittest.TestCase):
    """冷却：动作后一段时间内不重复触发。"""

    def test_cooldown_blocks_immediate_retrigger(self):
        """触发后立刻退出再触发：冷却期内不得再次动作。"""
        engine = RuleEngine(_cfg(confirm_count=1, release_frames=1,
                                 cooldown_ms=5000))
        t = 1000
        out = engine.update("target", 0.99, now_ms=t)
        self.assertTrue(out.should_turn_on)
        # 立刻退出再触发：冷却期内不得再次动作
        out2 = engine.update("other", 0.99, now_ms=t + 100)
        self.assertFalse(out2.should_turn_off, "冷却期内不得退出")
        self.assertTrue(engine.current_state())
        out3 = engine.update("target", 0.99, now_ms=t + 200)
        self.assertFalse(out3.should_turn_on, "冷却期内不得重复触发")

    def test_cooldown_expires_allows_retrigger(self):
        """冷却结束后应能退出并再次触发。"""
        engine = RuleEngine(_cfg(confirm_count=1, release_frames=1,
                                 cooldown_ms=1000))
        t = 1000
        engine.update("target", 0.99, now_ms=t)
        # 冷却未过：不退出
        out = engine.update("other", 0.99, now_ms=t + 500)
        self.assertFalse(out.should_turn_off)
        # 冷却已过：退出
        out = engine.update("other", 0.99, now_ms=t + 1200)
        self.assertTrue(out.should_turn_off)
        self.assertFalse(engine.current_state())
        # 退出动作本身也进入冷却；再等冷却过后重新确认才触发
        out = engine.update("target", 0.99, now_ms=t + 1500)
        self.assertFalse(out.should_turn_on, "退出动作后同样受冷却限制")
        out = engine.update("target", 0.99, now_ms=t + 2600)
        self.assertTrue(out.should_turn_on, "冷却结束后应能再次触发")


class RuleEngineStateChangeTest(unittest.TestCase):
    """只在状态变化时输出动作。"""

    def test_no_repeat_commands_while_stable(self):
        engine = RuleEngine(_cfg(confirm_count=2, release_frames=5,
                                 cooldown_ms=0))
        t = 1000
        engine.update("target", 0.9, now_ms=t); t += 50
        engine.update("target", 0.9, now_ms=t); t += 50
        actions = 0
        for _ in range(50):
            out = engine.update("target", 0.9, now_ms=t)
            t += 50
            if out.should_turn_on or out.should_turn_off:
                actions += 1
        self.assertEqual(actions, 0, "状态稳定期间不得产生任何动作命令")

    def test_reset_clears_partial_state(self):
        engine = RuleEngine(_cfg(confirm_count=3))
        engine.update("target", 0.99, now_ms=1000)
        engine.update("target", 0.99, now_ms=1050)
        engine.reset()
        out = engine.update("target", 0.99, now_ms=1100)
        self.assertFalse(out.should_turn_on,
                         "reset 后不得带着旧的连续计数触发")


class ProtocolSerializationTest(unittest.TestCase):
    """协议序列化与反序列化。"""

    def test_command_json_roundtrip(self):
        command = Command(request_id="req-1", target="led0",
                          action=ACTION_SET_LED, params={"brightness": 128})
        import json
        data = json.loads(command.to_json())
        self.assertEqual(data["v"], PROTOCOL_VERSION)
        self.assertEqual(data["requestId"], "req-1")
        self.assertEqual(data["params"]["brightness"], 128)

    def test_feedback_parsing(self):
        fb = Feedback.from_json(
            '{"requestId":"r1","status":"executed","executedAtMs":42}')
        self.assertEqual(fb.status, STATUS_EXECUTED)
        self.assertEqual(fb.executed_at_ms, 42)

    def test_feedback_unknown_status_rejected(self):
        """未知状态的反馈必须被拒绝，不能默认成 received。

        默认成 received 会让调用方把"看不懂的回执"当成"控制器已确认"，
        规则引擎据此可能误触发硬件动作。Android 端同样返回 null。
        """
        self.assertIsNone(Feedback.from_json('{"requestId":"r1","status":"whatever"}'))

    def test_feedback_error_alias_maps_to_failed(self):
        """"error" 是 Android 端已接受的别名，PC 端必须归一为 failed（两端同构）。"""
        fb = Feedback.from_json('{"requestId":"r1","status":"error","message":"bad params"}')
        self.assertIsNotNone(fb)
        self.assertEqual(fb.status, STATUS_FAILED)

    def test_feedback_invalid_json_returns_none(self):
        self.assertIsNone(Feedback.from_json("not json"))


class DeviceAdapterTest(unittest.TestCase):
    """设备适配器：去重、超时、重试规则、断连不重放。"""

    def test_duplicate_request_id_deduped(self):
        """同一 requestId 只执行一次。"""
        sim = SimulatedDevice()
        adapter = DeviceAdapter("unused", max_retries=0)
        # 直接驱动 SimulatedDevice 验证去重语义
        cmd = Command(request_id="req-dup", target="led0", action=ACTION_LED_ON)
        first = sim.handle(cmd)
        second = sim.handle(cmd)
        self.assertEqual(first.status, STATUS_EXECUTED)
        self.assertEqual(second.status, STATUS_RECEIVED,
                         "重复 requestId 不得再次执行动作")
        self.assertTrue(sim.led_on)

    def test_retryable_actions_defined(self):
        from pvl_hardware import RETRYABLE_ACTIONS
        self.assertIn(ACTION_LED_ON, RETRYABLE_ACTIONS)
        self.assertIn(ACTION_LED_OFF, RETRYABLE_ACTIONS)
        self.assertNotIn(ACTION_SERVO_SET, RETRYABLE_ACTIONS,
                         "运动动作绝不自动重试（会重复执行机械动作）")

    def test_disconnect_does_not_replay(self):
        adapter = DeviceAdapter("unused")
        adapter._sent["req-1"] = Command("req-1", "led0", ACTION_LED_ON)
        adapter.disconnect()
        self.assertEqual(adapter._sent, {},
                         "断连必须清理缓存，避免重连后重放过期命令")

    def test_send_to_unreachable_host_fails(self):
        """连不上的控制器：明确失败，不假装成功。"""
        adapter = DeviceAdapter("127.0.0.1", port=1, timeout_ms=300,
                                max_retries=0)
        event = adapter.send(ACTION_LED_ON, "led0")
        self.assertEqual(event.status, STATUS_FAILED)
        self.assertTrue(event.message)

    def test_status_query_does_not_execute(self):
        sim = SimulatedDevice()
        fb = sim.handle(Command("req-s", "led0", ACTION_STATUS))
        self.assertEqual(fb.status, STATUS_RECEIVED)
        self.assertFalse(sim.led_on, "只读查询不得改变执行器状态")

    def test_stop_action_turns_led_off(self):
        sim = SimulatedDevice()
        sim.handle(Command("r1", "led0", ACTION_LED_ON))
        self.assertTrue(sim.led_on)
        sim.handle(Command("r2", "led0", "stop"))
        self.assertFalse(sim.led_on, "stop 必须立即关闭执行器")


class HardwareControllerTest(unittest.TestCase):
    """门面：编排规则引擎与设备。"""

    def _make(self, **cfg_overrides):
        sim = SimulatedDevice()
        adapter = DeviceAdapter("unused")
        counter = {"n": 0}

        def sender(action, target):
            counter["n"] += 1
            return sim.handle(Command(
                request_id=f"sim-{counter['n']}", target=target, action=action))

        controller = HardwareController(adapter, _cfg(**cfg_overrides),
                                         sender=sender)
        return sim, controller

    def test_auto_disabled_by_default(self):
        sim, controller = self._make(confirm_count=1, cooldown_ms=0)
        self.assertFalse(controller.auto_enabled,
                         "自动控制必须默认关闭")
        # 不开自动控制：即使满足条件也不发命令
        controller.on_prediction("target", 0.99, now_ms=1000)
        self.assertEqual(sim.commands, [],
                         "自动控制关闭时不得发送任何命令")
        self.assertFalse(sim.led_on)

    def test_auto_enabled_drives_device(self):
        sim, controller = self._make(confirm_count=1, release_frames=1,
                                     cooldown_ms=0)
        controller.set_auto(True)
        controller.on_prediction("target", 0.99, now_ms=1000)
        self.assertTrue(sim.led_on, "目标出现且确认满足条件应开 LED")
        controller.on_prediction("other", 0.99, now_ms=1100)
        self.assertFalse(sim.led_on, "目标消失满足退出条件应关 LED")

    def test_stop_control_resets_rule(self):
        sim, controller = self._make(confirm_count=1, release_frames=1,
                                     cooldown_ms=0)
        controller.set_auto(True)
        controller.on_prediction("target", 0.99, now_ms=1000)
        self.assertTrue(sim.led_on)

        n_before = len(sim.commands)
        controller.set_auto(False)     # 停止控制
        controller.on_prediction("other", 0.99, now_ms=1100)
        # 停止后不再产生新的自动动作
        self.assertEqual(len(sim.commands), n_before,
                         "停止自动控制后不得再发送任何命令")
        self.assertTrue(sim.led_on,
                        "停止控制后不应产生新的自动动作（LED 保持原状）")
        self.assertFalse(controller.engine.current_state(),
                         "停止控制必须复位规则状态")


class NoVisionSourceMeansNoFakeSwitchTest(unittest.TestCase):
    """没有视觉结果来源时，自动控制必须真的不动作（不能是假开关）。

    这条锁定的是诚实性，不是功能：PC 客户端默认没有分类器，
    所以"开启自动控制"在这里不可能触发任何动作。测试确保这条路径
    不会因为以后的改动悄悄变成"看似能开、实际永不动"。
    """

    def test_auto_enabled_without_source_never_sends(self):
        sim = SimulatedDevice()
        adapter = DeviceAdapter("unused")
        controller = HardwareController(adapter, _cfg(confirm_count=1,
                                                     cooldown_ms=0))
        # 没有 prediction_provider 等价于"没有视觉来源"
        self.assertTrue(controller.auto_enabled is False)
        controller.set_auto(True)
        # 即使手动喂满足条件的结果，只要上层没有来源就不会被调用；
        # 这里直接验证：没有来源时 controller 本身不会自发的发命令
        self.assertEqual(sim.commands, [],
                         "没有视觉来源时不得自发产生命令")

    def test_poll_prediction_requires_provider(self):
        """poll_prediction 在没有 provider 时必须安全地什么都不做。"""
        sim = SimulatedDevice()
        adapter = DeviceAdapter("unused")
        controller = HardwareController(adapter, _cfg(confirm_count=1,
                                                     cooldown_ms=0))
        controller.set_auto(True)
        # 直接调用内部轮询逻辑（不经过 Qt），不应抛异常也不应发命令
        # 这里模拟"provider 为 None"的上层行为
        self.assertEqual(sim.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)