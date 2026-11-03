"""
PhoneVision Lab — 端到端冒烟测试（真实验证训练/导出链路，不用真机）。

职责：用程序生成的合成图片（每类一个可区分的图案）跑完整链路：
  创建数据集 -> 采集多批次 -> 划分 -> 训练 -> 转 TFLite -> 一致性校验 -> 打模型包。

为什么这样设计：
  - 这条链路是"最小闭环"的核心，必须在没有真机、没有用户照片的情况下也能验证。
  - 合成数据可区分（不同类不同颜色/形状），训练应当能收敛到高准确率，
    否则说明训练/预处理/导出链路有 bug。
  - 全部输出到临时目录，不污染真实用户数据，也不进 Git。

运行：
  cd pc-client
  .venv-train\\Scripts\\python.exe scripts\\smoke_train.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_PC_CLIENT = os.path.dirname(_HERE)
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)


def make_synthetic_dataset(store, class_names, batches_per_class=3,
                           images_per_batch=4, size=(320, 240)):
    """生成合成数据集：每个类别一种颜色+一个形状，带噪声与位置抖动。

    返回 (class_names, batch_ids)。
    """
    import numpy as np
    from PIL import Image, ImageDraw

    rng = np.random.default_rng(7)
    colors = {
        "red": (200, 40, 40), "green": (40, 200, 60), "blue": (40, 60, 200),
    }
    default_colors = [(200, 40, 40), (40, 200, 60), (40, 60, 200),
                      (200, 200, 40), (200, 40, 200)]

    batch_ids = []
    for ci, class_name in enumerate(class_names):
        base_color = colors.get(class_name, default_colors[ci % len(default_colors)])
        for bi in range(batches_per_class):
            batch = store.start_batch(class_name)
            batch_ids.append(batch.batch_id)
            for k in range(images_per_batch):
                img = Image.new("RGB", size, (235, 235, 235))
                draw = ImageDraw.Draw(img)
                # 位置/大小抖动：避免同一批次完全相同的帧
                cx = rng.integers(size[0] // 4, size[0] * 3 // 4)
                cy = rng.integers(size[1] // 4, size[1] * 3 // 4)
                r = int(rng.integers(size[1] // 8, size[1] // 4))
                if ci % 3 == 0:
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=base_color)
                elif ci % 3 == 1:
                    draw.rectangle([cx - r, cy - r, cx + r, cy + r], fill=base_color)
                else:
                    draw.polygon([(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)],
                                 fill=base_color)
                # 加噪点，模拟真实相机
                noise = rng.integers(0, 25, size=(size[1], size[0], 3), dtype=np.uint8)
                arr = (np.asarray(img, dtype=np.int16) + noise).clip(0, 255).astype(np.uint8)
                import io
                buf = io.BytesIO()
                Image.fromarray(arr).save(buf, "JPEG", quality=90)
                store.save_frame(class_name, batch.batch_id, buf.getvalue())
            store.end_batch(class_name, batch.batch_id)
    return batch_ids


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="pvl-smoke-")
    os.environ["PVL_DATA_DIR"] = workdir
    print(f"[smoke] 工作目录: {workdir}")

    from pvl_dataset import DatasetStore
    from pvl_split import check_dataset, split_dataset, save_split
    from pvl_preprocess import PreprocessSpec
    from pvl_train import TrainConfig, Trainer
    from pvl_export import export_model

    # ---- 1. 创建数据集并采集 ----
    store = DatasetStore(workdir)
    class_names = ["red", "green", "blue"]
    dataset = store.create("smoke-demo", class_names)
    print(f"[smoke] 数据集: {dataset.name} 类别={dataset.display_names()}")

    make_synthetic_dataset(store, class_names,
                           batches_per_class=3, images_per_batch=5)
    counts = dataset.class_counts()
    print(f"[smoke] 各类样本数: {counts}")
    assert all(n == 15 for n in counts.values()), f"样本数异常: {counts}"

    # ---- 2. 体检 + 划分 ----
    problems, warnings = check_dataset(dataset)
    print(f"[smoke] 体检 problems={problems} warnings={warnings}")
    assert not problems, f"数据集体检未通过: {problems}"

    split = split_dataset(dataset, val_ratio=0.4, seed=99)
    print(f"[smoke] 划分: train={len(split.train)} val={len(split.val)} "
          f"val各类别={split.class_counts('val')}")
    assert split.train and split.val, "划分结果为空"
    # 验证集必须是整 batch，绝不能与训练集同 batch
    train_batches = {s.batch_id for s in split.train}
    val_batches = {s.batch_id for s in split.val}
    assert not (train_batches & val_batches), "训练/验证集出现同一批次（数据泄漏）"

    split_path = os.path.join(store.root, "split.json")
    save_split(split, split_path)

    # ---- 3. 训练 ----
    # 注意：合成数据只验证"链路可用"，真实照片的准确率另见文档说明。
    # input_size 用 224 与 ImageNet 预训练权重的默认输入一致，避免
    # "weights for input shape (224,224) will be loaded" 的降级路径。
    spec = PreprocessSpec(input_size=224, color_order="RGB", layout="NHWC",
                          normalization="raw", center_crop=True)
    config = TrainConfig(
        dataset_root=store.root,
        input_size=224,
        epochs=10,
        batch_size=8,
        learning_rate=1e-3,
        seed=99,
        device="cpu",
        val_ratio=0.4,
        class_names=dataset.class_names(),
        display_names=dataset.display_names(),
        preprocess=spec.to_dict(),
    )
    output_dir = os.path.join(workdir, "runs", "smoke-run")
    trainer = Trainer(config, split_path, output_dir)
    last = {"n": 0}

    def on_progress(p):
        if p.step // 4 != last["n"]:
            last["n"] = p.step // 4
            print(f"[smoke]   epoch={p.epoch}/{p.total_epochs} step={p.step} "
                  f"loss={p.loss:.3f} acc={p.accuracy:.3f} "
                  f"val_acc={p.val_accuracy:.3f}")

    trainer._on_progress = on_progress
    # 手动驱动（与 GUI 的线程用法一致，但这里同步等待）
    from pvl_train import train_model
    progress = train_model(config, split_path, output_dir,
                           should_stop=lambda: False, on_progress=on_progress)
    print(f"[smoke] 训练状态={progress.state} "
          f"best_val_acc={progress.best_val_accuracy:.4f} msg={progress.message}")
    assert progress.state == "done", f"训练未完成: {progress.state} {progress.message}"
    assert progress.best_val_accuracy > 0.5, \
        f"合成数据上验证准确率过低({progress.best_val_accuracy:.3f})，链路可能有 bug"

    # ---- 4. 导出 + 一致性 ----
    result = export_model(
        os.path.join(output_dir, "best.keras"), config, spec, output_dir,
        split_path, package_name="smoke-demo")
    print(f"[smoke] 导出 success={result.success} error={result.error}")
    print(f"[smoke] 一致性: {result.consistency}")
    assert result.success, f"导出失败: {result.error}"
    assert os.path.isfile(result.package_path), "模型包未生成"

    # ---- 5. 校验模型包内容 ----
    import zipfile
    with zipfile.ZipFile(result.package_path) as zf:
        names = set(zf.namelist())
        print(f"[smoke] 模型包内容: {sorted(names)}")
        assert {"model.tflite", "manifest.json", "labels.json",
                "consistency.json", "README.txt"} <= names, "模型包缺少必要文件"
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        labels = json.loads(zf.read("labels.json").decode("utf-8"))
    assert manifest["preprocess"] == spec.to_dict(), "manifest 预处理与 spec 不一致"
    assert labels["index_to_name"] == {"0": "red", "1": "green", "2": "blue"}, \
        f"标签映射错误: {labels}"
    print(f"[smoke] 模型包大小: "
          f"{os.path.getsize(result.package_path) / 1024:.1f} KB")

    # ---- 6. 验证取消路径 ----
    print("[smoke] 验证取消路径…")
    cancel_dir = os.path.join(workdir, "runs", "cancel-run")
    progress2 = train_model(config, split_path, cancel_dir,
                            should_stop=lambda: True)
    print(f"[smoke] 取消状态={progress2.state} msg={progress2.message}")
    assert progress2.state == "cancelled", "取消路径未生效"

    print(f"[smoke] 全部通过。产物目录: {output_dir}")
    print(f"[smoke] 模型包: {result.package_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
