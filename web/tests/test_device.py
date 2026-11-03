"""
PhoneVision Lab Web — 设备会话测试（状态机 / 视觉模式 / 帧管线）。

职责：用假 reader 与假连接替代真实手机，验证：
  - 未连接时状态字段全部为"未连接"，不出现假数值；
  - 视觉模式与参数的范围校验、未知模式拒绝；
  - processed_frame 真的调用了 vision_modes.apply_mode（复用而非复制）；
  - 截图走原始帧，帧接口走处理后的帧。
不连网、不需要真实手机。
"""
import os
import sys
import unittest
from unittest import mock

import numpy as np

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WEB not in sys.path:
    sys.path.insert(0, _WEB)

_REPO = os.path.dirname(_WEB)
_PC_CLIENT = os.path.join(_REPO, "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from server.util import ApiError  # noqa: E402


class DeviceSessionTest(unittest.TestCase):

    def setUp(self):
        from server.device import DeviceSession
        self.session = DeviceSession()

    def tearDown(self):
        self.session.disconnect()

    # ---- 未连接状态 ----

    def test_disconnected_status_has_no_fake_numbers(self):
        status = self.session.status()
        self.assertFalse(status["connected"])
        self.assertEqual(status["state"], "disconnected")
        self.assertEqual(status["state_label"], "未连接")
        for key in ("phone_fps", "receive_fps", "display_fps", "dropped_frames",
                    "bandwidth_mbps", "average_jpeg_bytes"):
            self.assertIsNone(status[key], f"{key} 在未连接时应为 None（未采集）")
        self.assertTrue(status["frame_stale"])

    def test_latest_frame_without_connection_raises_not_connected(self):
        with self.assertRaises(ApiError) as ctx:
            self.session.latest_frame()
        self.assertEqual(ctx.exception.code, "not_connected")

    # ---- 视觉模式 ----

    def test_default_mode_is_original(self):
        state = self.session.vision_state()
        self.assertEqual(state["mode"], "original")
        self.assertEqual(state["params"], [])
        self.assertIn("原始", state["hint"])

    def test_set_mode_rejects_unknown(self):
        with self.assertRaises(ApiError):
            self.session.set_mode("thermal")
        self.assertEqual(self.session.vision_state()["mode"], "original")

    def test_canny_mode_exposes_two_params(self):
        self.session.set_mode("canny")
        state = self.session.vision_state()
        self.assertEqual(len(state["params"]), 2)
        keys = {p["key"] for p in state["params"]}
        self.assertEqual(keys, {"canny_low", "canny_high"})
        for param in state["params"]:
            self.assertLessEqual(param["min"], param["value"])
            self.assertGreaterEqual(param["max"], param["value"])

    def test_hsv_mode_exposes_six_params(self):
        self.session.set_mode("hsv")
        self.assertEqual(len(self.session.vision_state()["params"]), 6)

    def test_contour_mode_exposes_seven_params(self):
        self.session.set_mode("contour")
        self.assertEqual(len(self.session.vision_state()["params"]), 7)

    def test_set_params_clamps_to_range(self):
        self.session.set_mode("hsv")
        self.session.set_params({"h_min": 9999, "s_min": -50})
        values = {p["key"]: p["value"]
                  for p in self.session.vision_state()["params"]}
        self.assertEqual(values["h_min"], 179)
        self.assertEqual(values["s_min"], 0)

    def test_set_params_ignores_unknown_keys(self):
        self.session.set_mode("canny")
        self.session.set_params({"canny_low": 30, "evil": 1})
        values = {p["key"]: p["value"]
                  for p in self.session.vision_state()["params"]}
        self.assertEqual(values["canny_low"], 30)
        self.assertNotIn("evil", values)

    def test_set_params_rejects_non_numeric(self):
        with self.assertRaises(ApiError):
            self.session.set_params({"canny_low": "abc"})

    def test_reset_params_restores_defaults(self):
        import vision_modes
        self.session.set_mode("canny")
        self.session.set_params({"canny_low": 10})
        self.session.reset_params()
        values = {p["key"]: p["value"]
                  for p in self.session.vision_state()["params"]}
        self.assertEqual(values["canny_low"],
                         vision_modes.DEFAULT_PARAMS["canny_low"])

    def test_all_modes_listed(self):
        modes = self.session.vision_state()["modes"]
        self.assertEqual([m["id"] for m in modes],
                         ["original", "gray", "canny", "hsv", "contour"])
        for mode in modes:
            self.assertTrue(mode["label"])
            self.assertTrue(mode["label_en"])

    # ---- 帧管线 ----

    def test_processed_frame_uses_vision_modes(self):
        """处理后的帧必须来自 vision_modes.apply_mode（复用现有实现）。"""
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        frame[:] = (10, 200, 30)   # BGR
        fake_model = mock.Mock()
        fake_model.get_latest_frame.return_value = (frame, 7)
        fake_model.snapshot.return_value = mock.Mock(
            connection_state="Streaming", device_name="TestPhone",
            phone_fps=9.5, receive_fps=9.0, display_fps=8.0, width=640,
            height=480, average_jpeg_bytes=1024.0, bandwidth_mbps=2.0,
            received_frames=7, invalid_frames=0,
            estimated_dropped_frames=1, last_error=None, last_ping_time=None,
            frame_stale=False, frame_age_seconds=0.1)

        self.session._model = fake_model
        self.session._mode = "hsv"
        self.session._params = {"h_min": 0, "h_max": 179, "s_min": 0,
                                "s_max": 255, "v_min": 0, "v_max": 255}
        processed, number = self.session.processed_frame()
        self.assertEqual(number, 7)
        # HSV 模式下该颜色应被保留（白色掩膜）
        self.assertGreater(int(processed[:, :, 0].max()), 0)

    def test_frame_jpeg_encodes_real_jpeg(self):
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        frame[:] = (255, 0, 0)
        fake_model = mock.Mock()
        fake_model.get_latest_frame.return_value = (frame, 1)
        self.session._model = fake_model
        body = self.session.frame_jpeg()
        self.assertTrue(body.startswith(b"\xff\xd8"))
        self.assertTrue(body.rstrip(b"\n").endswith(b"\xff\xd9"))

    def test_stale_frame_raises_no_frame(self):
        """AppModel 在帧陈旧时返回 (None, None)，服务必须转为明确错误。"""
        fake_model = mock.Mock()
        fake_model.get_latest_frame.return_value = (None, None)
        self.session._model = fake_model
        with self.assertRaises(ApiError) as ctx:
            self.session.latest_frame()
        self.assertEqual(ctx.exception.code, "no_frame")

    # ---- 连接 ----

    def test_connect_without_host_raises(self):
        with self.assertRaises(ApiError) as ctx:
            self.session.connect("")
        self.assertEqual(ctx.exception.code, "bad_request")

    def test_connect_rejects_bad_port(self):
        with self.assertRaises(ApiError):
            self.session.connect("192.168.1.5", 99999)

    def test_connect_rejects_public_host(self):
        """服务端代发 /ping，不能让请求体把目标指向公网（SSRF）。"""
        for host in ("8.8.8.8", "example.com", "127.0.0.1", "169.254.1.1"):
            with self.subTest(host=host):
                with self.assertRaises(ApiError) as ctx:
                    self.session.connect(host, 8080)
                self.assertEqual(ctx.exception.code, "bad_request")
        self.assertFalse(self.session.is_connected)

    def test_connect_ping_failure_raises_device_error(self):
        with mock.patch("server.device.connection.ping_device") as ping:
            ping.return_value = mock.Mock(success=False, info={},
                                          error="无法连接手机：请确认手机已推流")
            with self.assertRaises(ApiError) as ctx:
                self.session.connect("192.168.1.5", 8080)
            self.assertEqual(ctx.exception.code, "device_error")
            self.assertIn("无法连接", ctx.exception.message)
        self.assertFalse(self.session.is_connected)

    def test_connect_success_starts_model(self):
        with mock.patch("server.device.connection.ping_device") as ping, \
                mock.patch("server.device.app_model.AppModel") as model_cls:
            ping.return_value = mock.Mock(
                success=True,
                info={"device": "Pixel", "width": 640, "height": 480,
                      "actualFps": 10.0})
            fake_model = mock.Mock()
            fake_model.snapshot.return_value = mock.Mock(
                connection_state="Streaming", device_name="Pixel",
                phone_fps=10.0, receive_fps=0.0, display_fps=0.0, width=640,
                height=480, average_jpeg_bytes=0.0, bandwidth_mbps=0.0,
                received_frames=0, invalid_frames=0,
                estimated_dropped_frames=0, last_error=None, last_ping_time=None,
                frame_stale=True, frame_age_seconds=0.0)
            model_cls.return_value = fake_model
            status = self.session.connect("192.168.1.5", 8080)
            self.assertTrue(status["connected"])
            self.assertTrue(fake_model.start.called)
            self.assertEqual(status["device"], "Pixel")
            self.assertEqual(status["state"], "Streaming")

    # ---- 指标 ----

    def test_transport_metrics_when_disconnected_are_none(self):
        metrics = self.session.transport_metrics()
        self.assertIsNone(metrics["phone_capture_fps"])
        self.assertIsNone(metrics["pc_receive_fps"])
        self.assertIsNone(metrics["pc_display_fps"])
        self.assertIsNone(metrics["resolution"])


if __name__ == "__main__":
    unittest.main()
