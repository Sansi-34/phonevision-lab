"""
PhoneVision Lab Web — 训练服务测试（环境检测 / 前置检查 / 状态机）。

职责：验证
  - 环境检测返回真实结果（本机有 TensorFlow → ready=True，无 GPU → 说明回落 CPU）；
  - 未划分 / 空训练集 / 类别不足时，start() 明确拒绝并给出原因；
  - 训练未成功完成时 export() 被拒绝（不导出未训练的模型）；
  - snapshot() 在 idle 状态下不出现假进度数字。
不启动真实训练（耗时且需要数据），只验证门禁与状态。
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


class TrainingEnvironmentTest(unittest.TestCase):

    def test_environment_reports_tensorflow_status(self):
        from server.training import training_environment
        env = training_environment()
        self.assertIn("tensorflow", env)
        self.assertIn("ready", env)
        self.assertIn("fix_command", env)
        if env["tensorflow"]:
            self.assertTrue(env["ready"])
            self.assertTrue(env["tensorflow_version"])
            # 本机没有 GPU：必须说明使用 CPU，不承诺加速
            if not env["gpu"]:
                self.assertIn("CPU", env["reason"])
        else:
            self.assertFalse(env["ready"])
            self.assertIn("tensorflow", env["missing"])
            self.assertTrue(env["reason"])

    def test_fix_command_mentions_requirements(self):
        from server.training import training_environment
        env = training_environment()
        self.assertIn("requirements", env["fix_command"])


class TrainingJobGateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pvl-web-train-")
        os.environ["PVL_DATA_DIR"] = self.tmp
        from server.training import TrainingJob
        self.job = TrainingJob()

    def tearDown(self):
        os.environ.pop("PVL_DATA_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_dataset(self, name, classes, batches_per_class=2, per_batch=3):
        """用 pvl_dataset 直接造一个可划分的数据集（不走设备采集）。"""
        import numpy as np
        from PIL import Image
        from pvl_dataset import DatasetStore
        from pvl_paths import datasets_dir

        store = DatasetStore(os.path.join(datasets_dir(), name))
        store.create(name, classes)
        rng = np.random.default_rng(3)
        for class_name in classes:
            for _ in range(batches_per_class):
                batch = store.start_batch(class_name)
                for _k in range(per_batch):
                    arr = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
                    buffer = tempfile.SpooledTemporaryFile()
                    Image.fromarray(arr).save(buffer, format="JPEG")
                    buffer.seek(0)
                    store.save_frame(class_name, batch.batch_id, buffer.read())
                store.end_batch(class_name, batch.batch_id)
        return store

    def test_snapshot_idle_has_no_fake_progress(self):
        snap = self.job.snapshot()
        self.assertEqual(snap["state"], "idle")
        self.assertEqual(snap["step"], 0)
        self.assertIsNone(snap["loss"])
        self.assertIsNone(snap["val_accuracy"])
        self.assertEqual(snap["logs"], [])

    def test_export_before_training_rejected(self):
        with self.assertRaises(ApiError) as ctx:
            self.job.export()
        self.assertEqual(ctx.exception.code, "not_ready")
        self.assertIn("训练", ctx.exception.message)

    def test_cancel_when_idle_is_safe(self):
        snap = self.job.cancel()
        self.assertEqual(snap["state"], "idle")

    def test_start_requires_split(self):
        from server.dataset import DatasetService
        service = DatasetService()
        service.create("nosplit", ["a", "b"])
        with self.assertRaises(ApiError) as ctx:
            self.job.start(service.current()["root"], "nosplit", {})
        self.assertEqual(ctx.exception.code, "no_split")
        self.assertIn("划分", ctx.exception.message)

    def test_start_rejects_single_class(self):
        from server.dataset import DatasetService
        from server.training import training_environment
        if not training_environment()["ready"]:
            self.skipTest("训练环境不可用（未安装 TensorFlow）")
        service = DatasetService()
        # 单类别 + 2 个批次：能通过 split，但分类任务至少需要 2 类
        self._make_dataset("oneclass", ["only"], batches_per_class=2, per_batch=2)
        service.open(os.path.join(self.tmp, "datasets", "oneclass"))
        service.split()
        with self.assertRaises(ApiError) as ctx:
            self.job.start(service.current()["root"], "oneclass", {})
        self.assertEqual(ctx.exception.code, "bad_request")
        self.assertIn("2 个类别", ctx.exception.message)

    def test_start_rejects_empty_training_set(self):
        from server.dataset import DatasetService
        from server.training import training_environment
        if not training_environment()["ready"]:
            self.skipTest("训练环境不可用（未安装 TensorFlow）")
        # 每类 1 个批次 → 划分后训练集为空
        service = DatasetService()
        self._make_dataset("singlebatch", ["a", "b"],
                           batches_per_class=1, per_batch=2)
        service.open(os.path.join(self.tmp, "datasets", "singlebatch"))
        service.split()
        with self.assertRaises(ApiError) as ctx:
            self.job.start(service.current()["root"], "singlebatch", {})
        self.assertEqual(ctx.exception.code, "no_split")
        self.assertIn("训练集", ctx.exception.message)

    def test_last_run_initially_empty(self):
        info = self.job.last_run()
        self.assertEqual(info["state"], "idle")
        self.assertEqual(info["output_dir"], "")


if __name__ == "__main__":
    unittest.main()
