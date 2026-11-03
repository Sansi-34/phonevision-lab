"""
PhoneVision Lab Web — 性能采样服务测试（未采集 / 真实值 / 导出）。

职责：验证
  - 未连接设备时拒绝开始测试（不用假数据填充）；
  - 采样窗口内写入真实指标，窗口外不写入；
  - 没有真实数据时所有字段保持 None（"— 未采集"），绝不为 0；
  - 推理/硬件/功耗明确标为未采集或暂不支持；
  - 导出 CSV / 摘要 / JSON 真的落盘。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WEB not in sys.path:
    sys.path.insert(0, _WEB)

_REPO = os.path.dirname(_WEB)
_PC_CLIENT = os.path.join(_REPO, "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from server.util import ApiError  # noqa: E402


class FakeDevice:
    def __init__(self, connected=True, fps=None):
        self._connected = connected
        self._fps = fps

    @property
    def is_connected(self):
        return self._connected

    def transport_metrics(self):
        if self._fps is None:
            return {"phone_capture_fps": None, "pc_receive_fps": None,
                    "pc_display_fps": None, "dropped_frames": None,
                    "received_frames": 0, "invalid_frames": 0,
                    "bandwidth_mbps": None, "average_jpeg_bytes": None,
                    "resolution": None}
        return {"phone_capture_fps": self._fps[0], "pc_receive_fps": self._fps[1],
                "pc_display_fps": self._fps[2], "dropped_frames": 3,
                "received_frames": 100, "invalid_frames": 1,
                "bandwidth_mbps": 8.5, "average_jpeg_bytes": 40000,
                "resolution": "640x480"}


class PerformanceServiceTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pvl-web-perf-")
        os.environ["PVL_DATA_DIR"] = self.tmp
        from server.performance import PerformanceService
        self.service = PerformanceService()

    def tearDown(self):
        os.environ.pop("PVL_DATA_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 未连接 ----

    def test_start_requires_connection(self):
        with self.assertRaises(ApiError) as ctx:
            self.service.start(3, 60, FakeDevice(connected=False))
        self.assertEqual(ctx.exception.code, "not_connected")
        self.assertIn("连接", ctx.exception.message)

    def test_start_rejects_bad_duration(self):
        with self.assertRaises(ApiError):
            self.service.start(3, 0, FakeDevice())
        with self.assertRaises(ApiError):
            self.service.start(-1, 60, FakeDevice())

    def test_snapshot_before_any_test(self):
        snap = self.service.snapshot()
        self.assertFalse(snap["running"])
        self.assertFalse(snap["has_record"])
        self.assertIsNone(snap["metrics"])

    def test_stop_without_test_rejected(self):
        with self.assertRaises(ApiError):
            self.service.stop()

    # ---- 采样 ----

    def test_start_then_warmup_phase(self):
        snap = self.service.start(5, 30, FakeDevice(fps=(10.0, 9.5, 9.0)))
        self.assertTrue(snap["running"])
        self.assertEqual(snap["phase"], "warmup")
        self.assertTrue(snap["has_record"])
        self.assertIsNone(snap["metrics"]["capture_and_transport"]["phone_capture_fps"],
                          "预热期内不应写入任何指标")

    def test_no_real_data_keeps_fields_none(self):
        """没有真实数据时指标必须保持 None（未采集），绝不能变成 0。"""
        self.service.start(0, 30, FakeDevice(fps=None))
        self.service.tick(FakeDevice(fps=None))
        metrics = self.service.snapshot()["metrics"]
        transport = metrics["capture_and_transport"]
        self.assertIsNone(transport["phone_capture_fps"])
        self.assertIsNone(transport["pc_receive_fps"])
        self.assertIsNone(transport["pc_display_fps"])
        self.assertIsNone(transport["dropped_frames"])

    def test_sampling_window_writes_real_values(self):
        device = FakeDevice(fps=(10.0, 9.5, 9.0))
        self.service.start(0, 30, device)
        # warmup=0 → sample_at 即 start 时刻，此刻已在采样窗口内
        self.service.tick(device)
        self.service.tick(device)
        metrics = self.service.snapshot()["metrics"]
        transport = metrics["capture_and_transport"]
        self.assertAlmostEqual(transport["phone_capture_fps"], 10.0, places=1)
        self.assertAlmostEqual(transport["pc_receive_fps"], 9.5, places=1)
        self.assertAlmostEqual(transport["pc_display_fps"], 9.0, places=1)
        self.assertEqual(transport["sample_count"], 2)
        # 丢帧按增量累计：两次 tick 的 dropped 都是 3 → 净增 0
        self.assertEqual(transport["dropped_frames"], 0)

    def test_ticks_outside_window_are_ignored(self):
        device = FakeDevice(fps=(10.0, 9.5, 9.0))
        self.service.start(5, 30, device)      # warmup=5 → 尚未进入采样窗口
        self.service.tick(device)
        metrics = self.service.snapshot()["metrics"]
        self.assertIsNone(metrics["capture_and_transport"]["phone_capture_fps"])
        self.assertEqual(metrics["capture_and_transport"]["sample_count"], 0)

    def test_uncollected_sections_are_none_or_unsupported(self):
        device = FakeDevice(fps=(10.0, 9.5, 9.0))
        self.service.start(0, 30, device)
        self.service.tick(device)
        metrics = self.service.snapshot()["metrics"]
        inference = metrics["inference"]
        self.assertIsNone(inference["phone_inference_fps"])
        self.assertIsNone(inference["completed"])
        self.assertIsNone(inference["preprocess"])
        self.assertIsNone(inference["model"])
        hardware = metrics["hardware"]
        self.assertIsNone(hardware["commands_sent"])
        self.assertIsNone(hardware["command_ack"])
        power = metrics["power"]
        self.assertEqual(power["source"], "unsupported")
        self.assertEqual(power["value"], "")

    def test_stop_finishes_and_marks_duration(self):
        device = FakeDevice(fps=(10.0, 9.5, 9.0))
        self.service.start(0, 30, device)
        self.service.stop()
        snap = self.service.snapshot()
        self.assertFalse(snap["running"])
        self.assertEqual(snap["phase"], "finished")
        self.assertTrue(snap["has_record"])

    def test_concurrent_start_rejected(self):
        self.service.start(0, 30, FakeDevice())
        with self.assertRaises(ApiError) as ctx:
            self.service.start(0, 30, FakeDevice())
        self.assertEqual(ctx.exception.code, "busy")

    # ---- 导出 ----

    def test_export_requires_record(self):
        with self.assertRaises(ApiError):
            self.service.export("csv")

    def test_export_csv_json_summary_written(self):
        device = FakeDevice(fps=(10.0, 9.5, 9.0))
        self.service.start(0, 30, device)
        self.service.tick(device)
        self.service.stop()
        for kind, suffix in (("csv", ".csv"), ("json", ".json"), ("txt", ".txt")):
            path = self.service.export(kind)
            self.assertTrue(os.path.isfile(path), f"{kind} 导出应落盘")
            self.assertTrue(path.endswith(suffix))
        # JSON 内容可解析，未采集字段为 null
        path = self.service.export("json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("capture_and_transport", data)
        self.assertIn("power", data)
        self.assertEqual(data["power"]["source"], "unsupported")

    def test_export_rejects_unknown_format(self):
        device = FakeDevice()
        self.service.start(0, 5, device)
        self.service.stop()
        with self.assertRaises(ApiError):
            self.service.export("xlsx")


if __name__ == "__main__":
    unittest.main()
