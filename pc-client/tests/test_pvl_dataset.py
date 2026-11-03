"""
PhoneVision Lab — 数据集与划分测试（不依赖真机、不依赖 TensorFlow）。

覆盖：
  1. 数据集创建/打开/保存（含原子写入与 batch 结构）。
  2. 类别新增/重命名/删除与路径安全（拒绝 ../ 越界）。
  3. 采集写入：同名文件不覆盖、批次计数正确。
  4. 按采集批次划分：同一 batch 绝不跨训练/验证集（数据泄漏防线）。
  5. 数据体检：类别缺失、样本不足、无 batch 时给出问题而不是伪造指标。
  6. 预处理契约：spec 序列化往返、非法配置被拒绝。
"""
import os
import shutil
import sys
import tempfile
import unittest

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

# 隔离用户数据目录：所有测试写临时目录，绝不碰真实数据。
_TMP_ROOT = tempfile.mkdtemp(prefix="pvl-test-dataset-")
os.environ["PVL_DATA_DIR"] = _TMP_ROOT

from pvl_dataset import DatasetStore, normalize_class_name  # noqa: E402
from pvl_split import (  # noqa: E402
    MIN_BATCHES_PER_CLASS, MIN_SAMPLES_PER_CLASS, check_dataset,
    collect_samples, save_split, split_dataset,
)
from pvl_preprocess import (  # noqa: E402
    COLOR_BGR, LAYOUT_NCHW, PreprocessSpec, preprocess, softmax, top_k,
)


def _real_jpeg_bytes(color: tuple = (10, 200, 30)) -> bytes:
    """返回真实可解码的 JPEG 字节。

    必须用 Pillow 写真图：数据集体检会抽查图片能否解码，
    写假 JPEG 字节会被正确判定为"损坏图片"（这正是要测试的行为）。
    """
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "JPEG", quality=85)
    return buf.getvalue()


class DatasetStoreTest(unittest.TestCase):
    """数据集创建/打开/保存。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pvl-ds-", dir=_TMP_ROOT)
        os.environ["PVL_DATA_DIR"] = os.path.dirname(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_and_reopen(self):
        store = DatasetStore(self.root)
        dataset = store.create("demo", ["apple", "pen"])
        self.assertEqual(sorted(dataset.class_names()), ["apple", "pen"])
        self.assertTrue(os.path.isfile(store.config_path()))

        reopened = DatasetStore(self.root).open(self.root)
        self.assertEqual(reopened.name, "demo")
        self.assertEqual(sorted(reopened.class_names()), ["apple", "pen"])

    def test_create_is_idempotent(self):
        store = DatasetStore(self.root)
        store.create("demo", ["apple"])
        store.create("demo", ["apple"])   # 不得覆盖既有数据
        again = store.dataset
        self.assertEqual(again.class_names(), ["apple"])

    def test_add_rename_remove_class(self):
        store = DatasetStore(self.root)
        dataset = store.create("demo", ["apple"])
        dataset.add_class("Banana Split")     # 含空格 -> 规范化为 Banana_Split
        self.assertIn("Banana_Split", dataset.class_names())
        self.assertEqual(dataset.get_class("Banana_Split").display_name,
                         "Banana Split")

        dataset.rename_class("Banana_Split", "Banana")
        self.assertIn("Banana", dataset.class_names())
        self.assertNotIn("Banana_Split", dataset.class_names())

        # 删到只剩一个类别时应被拒绝（没有类别的数据集无法训练）
        dataset.remove_class("Banana")
        self.assertEqual(dataset.class_names(), ["apple"])
        with self.assertRaises(ValueError):
            dataset.remove_class("apple")

    def test_class_name_rejects_traversal(self):
        store = DatasetStore(self.root)
        dataset = store.create("demo", ["apple"])
        # 这些必须直接拒绝
        for bad in ("..", "../evil", ".hidden", "", "   "):
            with self.assertRaises(ValueError, msg=bad):
                dataset.add_class(bad)
        # 含路径分隔符的：被规范化为下划线，绝不产生子目录穿越
        normalized = normalize_class_name("a/b")
        self.assertEqual(normalized, "a_b")
        self.assertNotIn("/", normalized)
        self.assertNotIn("\\", normalized)

    def test_save_frame_no_overwrite(self):
        store = DatasetStore(self.root)
        dataset = store.create("demo", ["apple"])
        batch = store.start_batch("apple")
        rel1 = store.save_frame("apple", batch.batch_id,
                                _real_jpeg_bytes((200, 30, 30)))
        rel2 = store.save_frame("apple", batch.batch_id,
                                _real_jpeg_bytes((30, 30, 200)))
        self.assertNotEqual(rel1, rel2, "同名文件必须加序号而不是覆盖")
        self.assertEqual(dataset.count_images("apple"), 2)
        # 空数据必须被拒绝，不能写出 0 字节文件
        with self.assertRaises(ValueError):
            store.save_frame("apple", batch.batch_id, b"")

    def test_delete_sample_rejects_escape(self):
        store = DatasetStore(self.root)
        dataset = store.create("demo", ["apple"])
        batch = store.start_batch("apple")
        rel = store.save_frame("apple", batch.batch_id,
                               _real_jpeg_bytes((10, 200, 30)))
        # 合法路径可以删
        dataset.delete_sample(rel)
        self.assertEqual(dataset.count_images("apple"), 0)
        for bad in ("../../etc/passwd", "images/apple/../evil.jpg",
                    "images/apple/..\\evil.jpg", "C:\\windows\\x.jpg",
                    "/etc/passwd"):
            with self.assertRaises(ValueError, msg=bad):
                dataset.delete_sample(bad)


class SplitTest(unittest.TestCase):
    """按采集批次划分：数据泄漏防线。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pvl-split-", dir=_TMP_ROOT)
        os.environ["PVL_DATA_DIR"] = os.path.dirname(self.root)
        self.store = DatasetStore(self.root)
        self.dataset = self.store.create("demo", ["red", "green", "blue"])
        # 每类 3 个 batch，每 batch 4 张（真 JPEG，保证体检查解码通过）
        for class_name in self.dataset.class_names():
            for _ in range(3):
                batch = self.store.start_batch(class_name)
                for _i in range(4):
                    self.store.save_frame(class_name, batch.batch_id,
                                          _real_jpeg_bytes((30, 200, 60)))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_split_never_mixes_batch(self):
        result = split_dataset(self.dataset, val_ratio=0.4, seed=42)
        self.assertTrue(result.train and result.val)
        train_batches = {s.batch_id for s in result.train}
        val_batches = {s.batch_id for s in result.val}
        self.assertEqual(
            train_batches & val_batches, set(),
            "同一采集批次不得同时出现在训练集与验证集（会导致指标虚高）")

    def test_split_is_reproducible(self):
        a = split_dataset(self.dataset, val_ratio=0.4, seed=42)
        b = split_dataset(self.dataset, val_ratio=0.4, seed=42)
        self.assertEqual([s.relative_path for s in a.train],
                         [s.relative_path for s in b.train])
        self.assertEqual([s.relative_path for s in a.val],
                         [s.relative_path for s in b.val])

    def test_split_covers_every_class(self):
        result = split_dataset(self.dataset, val_ratio=0.4, seed=7)
        for class_name in self.dataset.class_names():
            self.assertIn(class_name, result.class_counts("train"))
            self.assertIn(class_name, result.class_counts("val"),
                          f"类别 {class_name} 在验证集没有样本，无法评估")

    def test_split_ratio_is_reasonable(self):
        """3 个等大 batch 时，验证集不能变成 2/3（旧实现的 bug）。"""
        result = split_dataset(self.dataset, val_ratio=0.4, seed=1)
        total = len(result.train) + len(result.val)
        ratio = len(result.val) / total
        self.assertLess(ratio, 0.55, f"验证集占比 {ratio:.2f} 偏离目标过大")

    def test_check_passes_on_good_dataset(self):
        problems, warnings = check_dataset(self.dataset)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])

    def test_check_flags_missing_batches(self):
        store2_root = tempfile.mkdtemp(prefix="pvl-split-thin-", dir=_TMP_ROOT)
        os.environ["PVL_DATA_DIR"] = os.path.dirname(store2_root)
        store2 = DatasetStore(store2_root)
        ds2 = store2.create("thin", ["only"])
        # 只有一个 batch：无法在不泄漏的前提下切出验证集
        batch = store2.start_batch("only")
        for i in range(MIN_SAMPLES_PER_CLASS + 2):
            store2.save_frame("only", batch.batch_id,
                              _real_jpeg_bytes((200, 60, 60)))
        problems, _warnings = check_dataset(ds2)
        self.assertTrue(
            any("采集批次" in p for p in problems),
            f"单 batch 数据集应被判定无法划分，实际问题: {problems}")

    def test_split_single_batch_class_goes_to_train(self):
        """回归：单 batch 类别必须全进训练集，不能被判进验证集后留下空训练集。

        原缺陷：max(1, len-1)=1 把唯一 batch 判进 val，train 为空；
        界面显示"划分成功"，训练却在"训练集为空"处失败。
        """
        root = tempfile.mkdtemp(prefix="pvl-split-one-", dir=_TMP_ROOT)
        os.environ["PVL_DATA_DIR"] = os.path.dirname(root)
        store = DatasetStore(root)
        dataset = store.create("one-batch", ["only"])
        batch = store.start_batch("only")
        for _ in range(MIN_SAMPLES_PER_CLASS):
            store.save_frame("only", batch.batch_id,
                             _real_jpeg_bytes((70, 140, 200)))

        result = split_dataset(dataset, val_ratio=0.2, seed=3)
        self.assertTrue(result.train, "单 batch 类别必须留在训练集，train 不能为空")
        self.assertEqual(result.val, [], "唯一批次不得进验证集（会造成泄漏）")
        self.assertTrue(
            any("采集批次" in w for w in result.warnings),
            f"应明确告知该类别不参与验证，实际 warnings: {result.warnings}")

    def test_split_roundtrip_json(self):
        result = split_dataset(self.dataset, val_ratio=0.3, seed=5)
        path = os.path.join(self.root, "split.json")
        save_split(result, path)
        from pvl_split import load_split
        loaded = load_split(path)
        self.assertEqual(len(loaded.train), len(result.train))
        self.assertEqual(len(loaded.val), len(result.val))
        self.assertEqual(loaded.seed, 5)

    def test_collect_samples_infers_batch(self):
        samples = collect_samples(self.dataset)
        self.assertEqual(len(samples), 3 * 3 * 4)
        self.assertTrue(all(s.batch_id.startswith("batch-") for s in samples))


class PreprocessContractTest(unittest.TestCase):
    """预处理契约：PC 端唯一实现，spec 可序列化。"""

    def test_spec_roundtrip(self):
        spec = PreprocessSpec(input_size=160, color_order=COLOR_BGR,
                              layout=LAYOUT_NCHW, normalization="imagenet")
        restored = PreprocessSpec.from_dict(spec.to_dict())
        self.assertEqual(restored, spec)

    def test_default_is_imagenet(self):
        """ImageNet 预训练权重必须配 imagenet 归一化（已实测验证）。"""
        self.assertEqual(PreprocessSpec().normalization, "imagenet")

    def test_invalid_spec_rejected(self):
        bad = [
            PreprocessSpec(input_size=0),
            PreprocessSpec(layout="NCHWX"),
            PreprocessSpec(color_order="RGBA"),
            PreprocessSpec(normalization="magic"),
            PreprocessSpec(contract_version=999),
        ]
        for spec in bad:
            self.assertTrue(spec.validate(), f"{spec} 应被判为非法")

    def test_preprocess_shape_and_range(self):
        import numpy as np
        spec = PreprocessSpec(input_size=96)
        frame = np.full((240, 320, 3), 128, dtype=np.uint8)
        tensor = preprocess(frame, spec)
        self.assertEqual(tensor.shape, (1, 96, 96, 3))
        self.assertEqual(tensor.dtype, np.float32)
        # imagenet 归一化后中值像素约为 (0.502-0.485)/0.229 ≈ 0.074
        self.assertAlmostEqual(float(tensor[0, 0, 0, 0]), 0.0742, places=2)

    def test_preprocess_center_crop_keeps_aspect(self):
        import numpy as np
        spec = PreprocessSpec(input_size=64, center_crop=True)
        # 宽图：中心列是纯色，裁到中心后应仍是纯色
        frame = np.zeros((32, 256, 3), dtype=np.uint8)
        frame[:, 120:136] = 255
        tensor = preprocess(frame, spec)
        # 取输出中心像素（应落在白色带内）
        center = tensor[0, 32, 32]
        self.assertTrue(all(c > 0 for c in center),
                        "中心裁剪应保留构图中央的内容")

    def test_bgr_swap_changes_values(self):
        import numpy as np
        spec_rgb = PreprocessSpec(input_size=32, color_order="RGB")
        spec_bgr = PreprocessSpec(input_size=32, color_order=COLOR_BGR)
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = 200   # B 通道高
        t_rgb = preprocess(frame, spec_rgb)
        t_bgr = preprocess(frame, spec_bgr)
        self.assertNotAlmostEqual(float(t_rgb[0, 0, 0, 0]),
                                  float(t_bgr[0, 0, 0, 0]))

    def test_softmax_and_topk(self):
        import numpy as np
        probs = softmax(np.array([2.0, 1.0, 0.1], dtype=np.float32))
        self.assertAlmostEqual(float(probs.sum()), 1.0, places=5)
        top = top_k(probs, 2)
        self.assertEqual(top[0][0], 0)
        self.assertGreaterEqual(top[0][1], top[1][1])


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(_TMP_ROOT, ignore_errors=True)
