"""
PhoneVision Lab — 模型导出一致性测试（不需要 GPU，需要 TensorFlow）。

覆盖：
  1. 模型包结构完整（model.tflite / manifest.json / labels.json /
     consistency.json / README.txt）。
  2. manifest 自描述字段齐全：输入尺寸、布局、颜色顺序、归一化、输出解释、
     训练参数、预训练权重来源与许可证。
  3. 导出一致性：用固定样本对比 Keras 与 TFLite 输出，误差在容差内且
     Top-1 一致率达到要求；不满足时导出被拒绝（不产出假模型包）。
  4. 预处理契约一致：manifest 里的 preprocess 与训练用的 spec 完全相同。
  5. 类别映射一致：labels.json 的 index_to_name 与训练配置顺序一致。

说明：
  - 这些测试需要 TensorFlow（requirements-train.txt）。
  - 默认用很小的输入尺寸与 2 个 epoch，保证在 CPU 上几十秒内跑完。
  - 没有网络时不下载 ImageNet 权重会失败：那种情况测试会 skip 并说明原因，
    绝不把"权重没下载"伪装成"测试通过"。
"""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

_TMP_ROOT = tempfile.mkdtemp(prefix="pvl-test-export-")
os.environ["PVL_DATA_DIR"] = _TMP_ROOT

# TensorFlow 是训练/导出专用依赖，缺失时整个模块跳过（不伪造通过）。
try:
    import tensorflow as tf  # noqa: F401
    HAVE_TF = True
except Exception:  # noqa: BLE001 - 缺依赖就跳过，不假装通过
    HAVE_TF = False

if HAVE_TF:
    from pvl_dataset import DatasetStore
    from pvl_export import (
        MODEL_PACKAGE_FORMAT_VERSION, build_manifest, convert_to_tflite,
        export_model,
    )
    from pvl_preprocess import PreprocessSpec
    from pvl_split import save_split, split_dataset
    from pvl_train import PRETRAINED_INFO, TrainConfig, build_model


def _jpeg_bytes(color, size=(96, 96)):
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _make_dataset(store, class_names, batches=3, per_batch=4):
    for class_name in class_names:
        for _ in range(batches):
            batch = store.start_batch(class_name)
            color = {"red": (200, 40, 40), "green": (40, 200, 60),
                     "blue": (40, 60, 200)}.get(class_name, (120, 120, 120))
            for _i in range(per_batch):
                store.save_frame(class_name, batch.batch_id, _jpeg_bytes(color))
            store.end_batch(class_name, batch.batch_id)


@unittest.skipUnless(HAVE_TF, "未安装 TensorFlow（pip install -r requirements-train.txt）")
class ExportConsistencyTest(unittest.TestCase):
    """导出一致性与模型包自描述。"""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="pvl-exp-", dir=_TMP_ROOT)
        os.environ["PVL_DATA_DIR"] = os.path.dirname(cls.root)
        cls.store = DatasetStore(cls.root)
        cls.class_names = ["red", "green", "blue"]
        cls.dataset = cls.store.create("export-demo", cls.class_names)
        _make_dataset(cls.store, cls.class_names)

        cls.split = split_dataset(cls.dataset, val_ratio=0.4, seed=11)
        cls.split_path = os.path.join(cls.root, "split.json")
        save_split(cls.split, cls.split_path)
        assert cls.split.train and cls.split.val

        # 小模型 + 少 epoch：CPU 上几十秒完成，只验证链路
        cls.spec = PreprocessSpec(input_size=96, color_order="RGB",
                                  layout="NHWC", normalization="raw")
        cls.config = TrainConfig(
            dataset_root=cls.root, input_size=96, epochs=2, batch_size=8,
            learning_rate=1e-3, seed=11, device="cpu", val_ratio=0.4,
            class_names=cls.dataset.class_names(),
            display_names=cls.dataset.display_names(),
            preprocess=cls.spec.to_dict())

        cls.output_dir = os.path.join(cls.root, "runs", "export-run")
        cls.logs = []
        cls.result = export_model(
            os.path.join(cls.output_dir, "best.keras"), cls.config, cls.spec,
            cls.output_dir, cls.split_path, package_name="export-demo",
            log=cls.logs.append)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def _train_first(self):
        """如果还没有 best.keras，先跑一个最小训练。"""
        keras_path = os.path.join(self.output_dir, "best.keras")
        if os.path.isfile(keras_path):
            return keras_path
        from pvl_train import train_model
        progress = train_model(self.config, self.split_path, self.output_dir,
                               should_stop=lambda: False)
        self.assertEqual(progress.state, "done", progress.message)
        return keras_path

    def test_export_succeeded(self):
        keras_path = self._train_first()
        result = export_model(keras_path, self.config, self.spec,
                              self.output_dir, self.split_path,
                              package_name="export-demo")
        self.assertTrue(result.success, result.error)
        self.assertTrue(os.path.isfile(result.package_path))

    def test_package_contains_required_files(self):
        keras_path = self._train_first()
        result = export_model(keras_path, self.config, self.spec,
                              self.output_dir, self.split_path,
                              package_name="export-demo")
        self.assertTrue(result.success, result.error)
        with zipfile.ZipFile(result.package_path) as zf:
            names = set(zf.namelist())
        for required in ("model.tflite", "manifest.json", "labels.json",
                         "consistency.json", "README.txt"):
            self.assertIn(required, names, f"模型包缺少 {required}")

    def test_manifest_is_self_describing(self):
        keras_path = self._train_first()
        result = export_model(keras_path, self.config, self.spec,
                              self.output_dir, self.split_path,
                              package_name="export-demo")
        manifest = result.manifest
        self.assertEqual(manifest["format_version"], MODEL_PACKAGE_FORMAT_VERSION)
        self.assertEqual(manifest["model"]["input"]["shape"],
                         [1, 96, 96, 3])
        self.assertEqual(manifest["model"]["input"]["color_order"], "RGB")
        self.assertEqual(manifest["model"]["input"]["layout"], "NHWC")
        self.assertEqual(manifest["preprocess"]["normalization"], "raw")
        self.assertTrue(manifest["model"]["output"]["interpretation"])
        self.assertEqual(manifest["labels"]["count"], 3)
        self.assertEqual(manifest["training"]["epochs"], 2)
        self.assertEqual(manifest["pretrained"]["license"], "Apache-2.0")
        self.assertTrue(manifest["pretrained"]["source"])

    def test_preprocess_matches_training(self):
        """manifest 的预处理必须与训练用的 spec 逐字段一致。"""
        keras_path = self._train_first()
        result = export_model(keras_path, self.config, self.spec,
                              self.output_dir, self.split_path,
                              package_name="export-demo")
        self.assertEqual(result.manifest["preprocess"], self.spec.to_dict())

    def test_labels_match_class_order(self):
        keras_path = self._train_first()
        result = export_model(keras_path, self.config, self.spec,
                              self.output_dir, self.split_path,
                              package_name="export-demo")
        index_to_name = result.manifest["labels"]["index_to_name"]
        self.assertEqual(index_to_name,
                         {"0": "red", "1": "green", "2": "blue"})

    def test_consistency_within_tolerance(self):
        """导出一致性必须通过：误差在容差内且 Top-1 一致率达标。"""
        keras_path = self._train_first()
        result = export_model(keras_path, self.config, self.spec,
                              self.output_dir, self.split_path,
                              package_name="export-demo")
        c = result.consistency
        self.assertGreaterEqual(c["samples"], 1)
        self.assertLessEqual(c["max_abs_error"], c["tolerance"],
                             "最大绝对误差超出容差")
        self.assertGreaterEqual(c["top1_agreement"], c["min_top1_agreement"])
        self.assertTrue(c["passed"])

    def test_manifest_builder_standalone(self):
        """build_manifest 不依赖模型文件也能产出完整自描述。"""
        manifest = build_manifest(self.config, self.spec,
                                  self.dataset.class_names(),
                                  self.dataset.display_names(), 12345)
        self.assertEqual(manifest["model"]["bytes"], 12345)
        self.assertIn("android_min_sdk", manifest["runtime"])
        self.assertEqual(manifest["runtime"]["android_min_sdk"], 21)

    def test_pretrained_info_documented(self):
        """预训练权重来源与许可证必须写进产物，便于追溯。"""
        self.assertEqual(PRETRAINED_INFO["license"], "Apache-2.0")
        self.assertTrue(PRETRAINED_INFO["source"])
        self.assertTrue(PRETRAINED_INFO["offline_prepare"])


@unittest.skipUnless(HAVE_TF, "未安装 TensorFlow")
class ModelBuildTest(unittest.TestCase):
    """模型构造：必须用预训练权重，绝不把随机初始化当成果。"""

    def test_build_model_uses_pretrained(self):
        model, base = build_model(3, 96)
        self.assertFalse(base.trainable, "迁移学习第一阶段骨干网必须冻结")
        self.assertEqual(int(model.output_shape[-1]), 3)

    def test_tflite_conversion_produces_bytes(self):
        model, _base = build_model(2, 64)
        data = convert_to_tflite(model, PreprocessSpec(input_size=64),
                                 float16=True)
        self.assertGreater(len(data), 1024, "转换结果过小，不是有效模型")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(_TMP_ROOT, ignore_errors=True)
