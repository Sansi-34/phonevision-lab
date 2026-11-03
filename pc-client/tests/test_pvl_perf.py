"""
PhoneVision Lab — 性能测量与导出测试（不依赖真机、不依赖 TensorFlow）。

覆盖：
  1. 分位数计算（P50/P95）正确性。
  2. 单调时钟：记录里不出现手机/电脑时间戳相减的字段。
  3. 导出 CSV / 摘要 / JSON 均可读回。
  4. 功耗字段：不支持的来源显示"不支持"，不把电量当成功率。
  5. 硬件联动指标区分"命令确认耗时"与"机械动作完成耗时"。
  6. 阶段分离：预处理/模型/后处理各自统计，不混算。
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from pvl_perf import (  # noqa: E402
    PerfRecord, PerfSampler, StageStats, _percentile, export_csv,
    export_json, export_summary, new_record,
)


class PercentileTest(unittest.TestCase):
    """分位数计算。"""

    def test_known_values(self):
        values = list(range(1, 101))     # 1..100
        self.assertAlmostEqual(_percentile(values, 50), 50.5, places=3)
        self.assertAlmostEqual(_percentile(values, 95), 95.05, places=3)

    def test_single_and_empty(self):
        self.assertEqual(_percentile([], 95), 0.0)
        self.assertEqual(_percentile([7.0], 95), 7.0)

    def test_p95_gte_p50_gte_mean_ordering(self):
        stats = StageStats()
        for v in [1, 2, 3, 4, 5, 100]:
            stats.add(v)
        self.assertLessEqual(stats.p50, stats.p95)
        self.assertLessEqual(stats.mean, stats.max)
        self.assertEqual(stats.count, 6)

    def test_negative_and_none_ignored(self):
        stats = StageStats()
        stats.add(None)
        stats.add(-5.0)
        stats.add(10.0)
        self.assertEqual(stats.count, 1, "None 与负值不应计入统计")


class PerfRecordTest(unittest.TestCase):
    """记录结构与导出。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pvl-perf-")
        self.record = new_record(
            model_name="mobilenetv3-demo", input_size=224,
            color_order="RGB", layout="NHWC", normalization="imagenet",
            num_classes=3, client_version="test")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_environment_captured(self):
        self.assertTrue(self.record.device_model)
        self.assertTrue(self.record.os_version)

    def test_no_cross_clock_subtraction_field(self):
        """绝不出现拿手机与电脑时间戳相减的字段。"""
        d = self.record.to_dict()
        blob = json.dumps(d)
        for forbidden in ("e2e_latency_ms", "end_to_end_ms",
                          "phone_pc_delta_ms"):
            self.assertNotIn(forbidden, blob,
                             f"不应存在跨设备时间戳相减字段 {forbidden}")
        # 本机间隔必须标明是单调时钟口径
        self.assertIn("mean_ms", json.dumps(d["inference"]["model"]))

    def test_power_unsupported_by_default(self):
        self.assertEqual(self.record.power_source, "unsupported")
        self.assertEqual(self.record.power_value, "")
        self.assertIn("不测量手机功耗", self.record.power_note)

    def test_stages_separated(self):
        sampler = PerfSampler(self.record)
        sampler.begin(warmup_seconds=2.0)
        for i in range(10):
            sampler.add_inference(3.0 + i * 0.1, 20.0 + i * 0.2, 1.0)
        sampler.add_skipped(4)
        sampler.end(duration_seconds=30.0)

        self.assertEqual(self.record.preprocess.count, 10)
        self.assertEqual(self.record.model.count, 10)
        self.assertEqual(self.record.postprocess.count, 10)
        self.assertEqual(self.record.inference_completed, 10)
        self.assertEqual(self.record.inference_skipped, 4)
        # 三段耗时互不相等：证明没有混算
        self.assertNotEqual(self.record.preprocess.mean,
                            self.record.model.mean)
        self.assertEqual(self.record.warmup_seconds, 2.0)
        self.assertEqual(self.record.duration_seconds, 30.0)

    def test_hardware_metrics_distinguish_ack_from_completion(self):
        sampler = PerfSampler(self.record)
        sampler.add_command("sent", rtt_ms=None)        # 发出未确认
        sampler.add_command("received", rtt_ms=12.5)    # 只确认接收
        sampler.add_command("executed", rtt_ms=40.0)    # 确认执行
        sampler.add_command("failed", rtt_ms=None)      # 失败
        sampler.add_command("failed", rtt_ms=None)      # 失败

        self.assertEqual(self.record.commands_sent, 5)
        self.assertEqual(self.record.commands_received, 1)
        self.assertEqual(self.record.commands_executed, 1)
        self.assertEqual(self.record.commands_failed, 2)
        self.assertEqual(self.record.command_rtt_ms.count, 2)
        d = self.record.to_dict()
        # 指标名必须是"确认耗时"，不能冒充机械动作完成耗时
        self.assertIn("command_ack_latency", d["hardware"])
        note = d["hardware"]["note"]
        self.assertIn("机械动作完成耗时", note)
        self.assertIn("只确认接收", note)

    def test_export_csv(self):
        sampler = PerfSampler(self.record)
        sampler.add_inference(1.0, 10.0, 0.5)
        path = os.path.join(self.tmp, "perf.csv")
        export_csv(self.record, path)
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["metric", "value"])
        keys = {r[0] for r in rows[1:]}
        self.assertIn("inference.model.mean_ms", keys)
        self.assertIn("power.source", keys)

    def test_export_summary_and_json(self):
        sampler = PerfSampler(self.record)
        sampler.add_inference(1.0, 10.0, 0.5)
        txt = os.path.join(self.tmp, "summary.txt")
        js = os.path.join(self.tmp, "perf.json")
        export_summary(self.record, txt)
        export_json(self.record, js)
        with open(txt, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("PhoneVision Lab 性能测试摘要", text)
        self.assertIn("p95_ms", text)          # 分位数（摘要里是小写键名）
        self.assertIn("P95", text)             # 摘要说明文字里的大写
        self.assertIn("不支持", text)     # 功耗不支持的显式标注
        with open(js, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["model"]["input_size"], 224)


if __name__ == "__main__":
    unittest.main(verbosity=2)
