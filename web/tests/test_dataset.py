"""
PhoneVision Lab Web — 数据集服务测试（真实数据集目录 + 假设备帧）。

职责：用真实 pvl_dataset.DatasetStore + 临时数据目录，验证：
  - 创建/打开数据集复用现有存储格式（dataset.json）；
  - 采集真的把 JPEG 写进 images/<class>/<batch>/；
  - 体检与划分结论来自 pvl_split（与桌面客户端一致）；
  - 删除样本有路径校验，拒绝越界。
"""
import io
import os
import shutil
import sys
import tempfile
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


class FakeFrameDevice:
    """提供可控"最新帧"的假设备（帧号可递增，模拟真实推流）。

    exhausted_error=True  模拟"没有新帧"：抛 ApiError(no_frame)；
    exhausted_error=False 模拟"帧已陈旧"：返回 (None, None)（AppModel 的行为）。
    """

    def __init__(self, frame=None, numbers=None, exhausted_error=True):
        self.frame = frame if frame is not None else np.zeros((24, 32, 3),
                                                              dtype=np.uint8)
        # numbers=None 表示"无限帧"（用默认序列）；numbers=[] 表示"没有帧"
        self.numbers = (list(numbers) if numbers is not None
                        else [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.index = 0
        self.exhausted_error = exhausted_error

    def latest_frame(self):
        if self.index >= len(self.numbers):
            if self.exhausted_error:
                raise ApiError("no_frame", "摄像头还没有送出新的画面，请稍候再试")
            return None, None
        number = self.numbers[self.index]
        self.index += 1
        return self.frame, number


class DatasetServiceTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pvl-web-ds-")
        os.environ["PVL_DATA_DIR"] = self.tmp
        from server.dataset import DatasetService
        self.service = DatasetService()

    def tearDown(self):
        os.environ.pop("PVL_DATA_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 创建 / 打开 ----

    def test_list_datasets_initially_empty(self):
        self.assertEqual(self.service.list_datasets(), [])

    def test_create_dataset_writes_dataset_json(self):
        result = self.service.create("我的数据集", ["apple", "banana"])
        self.assertTrue(result["opened"])
        self.assertEqual(result["name"], "我的数据集")
        self.assertEqual([c["name"] for c in result["classes"]],
                         ["apple", "banana"])
        config = os.path.join(result["root"], "dataset.json")
        self.assertTrue(os.path.isfile(config), "必须复用现有 dataset.json 格式")

    def test_create_dataset_rejects_empty_name(self):
        with self.assertRaises(ApiError) as ctx:
            self.service.create("   ")
        self.assertEqual(ctx.exception.code, "bad_request")

    def test_create_dataset_sanitizes_illegal_name(self):
        with self.assertRaises(ApiError):
            self.service.create("..")

    def test_open_existing_dataset(self):
        created = self.service.create("ds-open", ["a", "b"])
        self.service._store = None
        reopened = self.service.open(created["root"])
        self.assertTrue(reopened["opened"])
        self.assertEqual(reopened["name"], "ds-open")

    def test_current_without_dataset_raises(self):
        with self.assertRaises(ApiError) as ctx:
            self.service.current()
        self.assertEqual(ctx.exception.code, "no_dataset")

    # ---- 类别 ----

    def test_add_and_remove_class(self):
        self.service.create("ds-class", ["a"])
        result = self.service.add_class("b")
        self.assertEqual(len(result["classes"]), 2)
        result = self.service.remove_class("b")
        self.assertEqual(len(result["classes"]), 1)

    def test_remove_last_class_rejected(self):
        self.service.create("ds-one", ["a"])
        with self.assertRaises(ApiError) as ctx:
            self.service.remove_class("a")
        self.assertEqual(ctx.exception.code, "bad_request")
        self.assertIn("至少需要保留一个类别", ctx.exception.message)

    def test_add_class_rejects_illegal_name(self):
        self.service.create("ds-bad", ["a"])
        with self.assertRaises(ApiError):
            self.service.add_class("../evil")

    # ---- 采集 ----

    def test_capture_one_writes_jpeg_into_batch_dir(self):
        self.service.create("ds-cap", ["a", "b"])
        device = FakeFrameDevice()
        result = self.service.capture_one(device)
        self.assertEqual(result["captured"], 1)
        dataset = self.service.describe()
        self.assertEqual(dataset["total_samples"], 1)
        root = dataset["root"]
        found = []
        for base, _dirs, files in os.walk(os.path.join(root, "images")):
            found.extend(f for f in files if f.endswith(".jpg"))
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].endswith(".jpg"))

    def test_capture_requires_class_when_dataset_has_none(self):
        self.service.create("ds-noclass", [])
        device = FakeFrameDevice()
        with self.assertRaises(ApiError) as ctx:
            self.service.capture_one(device)
        self.assertIn("类别", ctx.exception.message)

    def test_capture_rejects_duplicate_frame_number(self):
        self.service.create("ds-dup", ["a"])
        device = FakeFrameDevice(numbers=[5, 5])
        self.service.capture_one(device)
        with self.assertRaises(ApiError) as ctx:
            self.service.capture_one(device)
        self.assertEqual(ctx.exception.code, "no_frame")

    def test_capture_multiple_frames_accumulate(self):
        self.service.create("ds-multi", ["a", "b"])
        device = FakeFrameDevice(numbers=list(range(1, 6)))
        for _ in range(5):
            self.service.capture_one(device)
        self.assertEqual(self.service.describe()["total_samples"], 5)

    def test_start_capture_verifies_frame_available(self):
        """没有可用画面时，连续采集必须拒绝启动（不能进入假采集状态）。"""
        self.service.create("ds-start", ["a"])
        # 帧陈旧：AppModel 的 get_latest_frame 返回 (None, None)
        device = FakeFrameDevice(numbers=[], exhausted_error=False)
        with self.assertRaises(ApiError) as ctx:
            self.service.start_capture(device)
        self.assertEqual(ctx.exception.code, "no_frame")
        self.assertFalse(self.service.describe()["capturing"])

    def test_start_capture_rejects_when_not_connected(self):
        self.service.create("ds-start2", ["a"])

        class RaisingDevice:
            def latest_frame(self):
                from server.util import ApiError
                raise ApiError("not_connected", "尚未连接手机，请先连接设备")

        with self.assertRaises(ApiError) as ctx:
            self.service.start_capture(RaisingDevice())
        self.assertEqual(ctx.exception.code, "not_connected")
        self.assertFalse(self.service.describe()["capturing"])

    def test_capture_one_stale_frame_rejected(self):
        self.service.create("ds-stale", ["a"])
        device = FakeFrameDevice(numbers=[], exhausted_error=False)
        with self.assertRaises(ApiError) as ctx:
            self.service.capture_one(device)
        self.assertEqual(ctx.exception.code, "no_frame")
        self.assertEqual(self.service.describe()["total_samples"], 0)

    # ---- 样本浏览 / 删除 ----

    def test_samples_listed_with_class_and_batch(self):
        self.service.create("ds-samples", ["a", "b"])
        device = FakeFrameDevice(numbers=[1, 2, 3])
        self.service.capture_one(device)
        self.service.capture_one(device)
        samples = self.service.samples()
        self.assertEqual(len(samples), 2)
        for sample in samples:
            self.assertIn("class", sample)
            self.assertIn("batch", sample)
            self.assertTrue(sample["path"].startswith("images" + os.sep))

    def test_sample_image_returns_bytes(self):
        self.service.create("ds-img", ["a"])
        device = FakeFrameDevice(numbers=[1])
        self.service.capture_one(device)
        sample = self.service.samples()[0]
        body = self.service.sample_image(sample["path"])
        self.assertTrue(body.startswith(b"\xff\xd8"))

    def test_sample_image_rejects_traversal(self):
        self.service.create("ds-traversal", ["a"])
        with self.assertRaises(ApiError) as ctx:
            self.service.sample_image("../../etc/passwd")
        # 越界路径与"不是图片"统一按样本不存在处理，不泄露文件是否存在
        self.assertEqual(ctx.exception.code, "not_found")
        self.assertEqual(ctx.exception.status, 404)

    def test_sample_image_rejects_non_image_file(self):
        created = self.service.create("ds-non-image", ["a"])
        with open(os.path.join(created["root"], "secret.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("top secret")
        for path in ("secret.txt", "dataset.json", "images/secret.txt"):
            with self.subTest(path=path):
                with self.assertRaises(ApiError) as ctx:
                    self.service.sample_image(path)
                self.assertEqual(ctx.exception.code, "not_found")
                self.assertEqual(ctx.exception.status, 404)

    def test_sample_image_requires_images_subdir(self):
        self.service.create("ds-images-only", ["a"])
        # 数据集根目录下的图片文件也不行：必须位于 images/ 之下
        root = self.service.current()["root"]
        with open(os.path.join(root, "loose.jpg"), "wb") as fh:
            fh.write(b"\xff\xd8\xff\xd9")
        with self.assertRaises(ApiError) as ctx:
            self.service.sample_image("loose.jpg")
        self.assertEqual(ctx.exception.code, "not_found")

    def test_open_rejects_root_outside_datasets_dir(self):
        outside = tempfile.mkdtemp(prefix="pvl-web-outside-")
        try:
            with self.assertRaises(ApiError) as ctx:
                self.service.open(outside)
            self.assertEqual(ctx.exception.code, "bad_request")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_open_rejects_unc_path(self):
        with self.assertRaises(ApiError) as ctx:
            self.service.open(r"\\server\share\dataset")
        self.assertEqual(ctx.exception.code, "bad_request")

    def test_open_rejects_datasets_root_itself(self):
        from pvl_paths import datasets_dir
        with self.assertRaises(ApiError) as ctx:
            self.service.open(datasets_dir())
        self.assertEqual(ctx.exception.code, "bad_request")

    def test_delete_sample_updates_count(self):
        self.service.create("ds-del", ["a", "b"])
        device = FakeFrameDevice(numbers=[1, 2])
        self.service.capture_one(device)
        sample = self.service.samples()[0]
        self.service.delete_sample(sample["path"])
        self.assertEqual(self.service.describe()["total_samples"], 0)

    def test_delete_sample_rejects_non_image(self):
        created = self.service.create("ds-del-non-image", ["a"])
        config = os.path.join(created["root"], "dataset.json")
        with self.assertRaises(ApiError) as ctx:
            self.service.delete_sample("dataset.json")
        self.assertEqual(ctx.exception.code, "not_found")
        self.assertEqual(ctx.exception.status, 404)
        self.assertTrue(os.path.isfile(config), "非图片路径不得被删除")

    # ---- 体检 / 划分 ----

    def test_check_reports_problems_for_insufficient_data(self):
        self.service.create("ds-thin", ["a", "b"])
        device = FakeFrameDevice(numbers=[1])
        self.service.capture_one(device)
        result = self.service.check()
        self.assertFalse(result["ready"])
        self.assertTrue(result["problems"])

    def test_split_with_single_batch_per_class_reports_no_validation(self):
        """每类只有 1 个批次：绝不能静默产出"可训练"的划分结果。

        pvl_split 的具体策略可能演进（当前实现：全部进训练 + 警告；
        旧实现：唯一批次进验证、训练集为空），但共同底线是训练集与验证集
        不可能同时非空——训练服务据此必须以 no_split 拒绝。
        """
        self.service.create("ds-split", ["a", "b"])
        device = FakeFrameDevice(numbers=[1, 2])
        self.service.capture_one(device, "a")
        self.service.capture_one(device, "b")
        result = self.service.split()
        self.assertFalse(result["train"] and result["val"],
                         "单批次类别不能切出同时非空的训练/验证集")
        if not result["val"]:
            self.assertTrue(result["warnings"],
                            "无法切验证集时必须给出明确警告，而不是静默成功")

    def test_split_with_two_batches_per_class_produces_val(self):
        self.service.create("ds-ok", ["a", "b"])
        device = FakeFrameDevice(numbers=list(range(1, 13)))
        # 交替采集 + 切类，形成每类 2 个独立批次
        for class_name in ("a", "b"):
            self.service.capture_one(device, class_name)
            self.service.capture_one(device, "a" if class_name == "b" else "b")
            self.service.capture_one(device, class_name)
        result = self.service.split()
        self.assertGreater(result["train"], 0)
        self.assertGreater(result["val"], 0)
        self.assertEqual(result["seed"], 1234)
        status = self.service.split_status()
        self.assertTrue(status["exists"])
        self.assertEqual(status["train"], result["train"])

    def test_split_status_missing_before_split(self):
        self.service.create("ds-nosplit", ["a", "b"])
        self.assertFalse(self.service.split_status()["exists"])


if __name__ == "__main__":
    unittest.main()
