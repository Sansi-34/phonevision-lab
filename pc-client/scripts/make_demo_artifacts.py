"""
PhoneVision Lab — 生成本地演示用的模型包与性能报告样例。

用途：把端到端跑通的产物落到仓库外的固定位置，便于演示时直接取用，
也便于人工核对模型包内容与性能报告格式。

产物（写到 pc-client/artifacts/，该目录已被 .gitignore 忽略）：
  - smoke-demo.pvlmodel.zip   模型包（含 manifest/labels/consistency）
  - perf-sample.txt           性能报告摘要（合成数据，仅演示格式）
  - perf-sample.csv           性能 CSV
  - perf-sample.json          性能 JSON

运行：
  cd pc-client
  .venv-train\\Scripts\\python.exe scripts\\make_demo_artifacts.py
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

ARTIFACTS = os.path.join(_PC_CLIENT, "artifacts")


def main() -> int:
    os.makedirs(ARTIFACTS, exist_ok=True)

    # ---- 1. 跑端到端训练与导出，拿真实模型包 ----
    # 注意：不调用 smoke.main()（它会用临时目录并在结束时清理），
    # 这里复用其合成数据生成函数，把产物落到 artifacts/ 下。
    from pvl_dataset import DatasetStore
    from pvl_export import export_model
    from pvl_preprocess import PreprocessSpec
    from pvl_split import save_split, split_dataset
    from pvl_train import TrainConfig, train_model

    workdir = tempfile.mkdtemp(prefix="pvl-artifacts-")
    os.environ["PVL_DATA_DIR"] = workdir
    store = DatasetStore(workdir)
    dataset = store.create("smoke-demo", ["red", "green", "blue"])

    # 复用 smoke_train 的合成数据生成（保持两处数据一致）
    from scripts.smoke_train import make_synthetic_dataset
    make_synthetic_dataset(store, ["red", "green", "blue"],
                           batches_per_class=3, images_per_batch=5)

    split = split_dataset(dataset, val_ratio=0.4, seed=99)
    split_path = os.path.join(store.root, "split.json")
    save_split(split, split_path)

    spec = PreprocessSpec(input_size=224, color_order="RGB", layout="NHWC",
                          normalization="imagenet", center_crop=True)
    config = TrainConfig(
        dataset_root=store.root, input_size=224, epochs=10, batch_size=8,
        learning_rate=1e-3, seed=99, device="cpu", val_ratio=0.4,
        class_names=dataset.class_names(),
        display_names=dataset.display_names(),
        preprocess=spec.to_dict())

    output_dir = os.path.join(ARTIFACTS, "smoke-run")
    progress = train_model(config, split_path, output_dir,
                           should_stop=lambda: False)
    print(f"[artifacts] 训练状态={progress.state} "
          f"best_val_acc={progress.best_val_accuracy:.4f}")

    result = export_model(os.path.join(output_dir, "best.keras"), config,
                          spec, output_dir, split_path,
                          package_name="smoke-demo")
    print(f"[artifacts] 导出 success={result.success} error={result.error}")
    if result.success:
        print(f"[artifacts] 模型包: {result.package_path}")

    # ---- 2. 生成性能报告样例（格式演示，非真机数据） ----
    from pvl_perf import (PerfSampler, export_csv, export_json,
                          export_summary, new_record)

    record = new_record(
        model_name="smoke-demo", input_size=224, color_order="RGB",
        layout="NHWC", normalization="imagenet", num_classes=3,
        client_version="pc-client (sample)")
    record.power_source = "unsupported"
    record.power_value = ""
    record.power_note = (
        "本样例为格式演示，非真机实测。真机功耗需要设备提供真实电流/电压数据源；"
        "PC 客户端不测量手机功耗。")
    sampler = PerfSampler(record)
    sampler.begin(warmup_seconds=3.0)
    # 合成样本：仅用于展示统计口径与分位数格式
    import random
    rng = random.Random(7)
    for _ in range(120):
        sampler.add_inference(
            2.0 + rng.random() * 1.5,
            45.0 + rng.random() * 20.0,
            0.8 + rng.random() * 0.6)
    sampler.add_skipped(15)
    sampler.add_command("sent", None)
    sampler.add_command("received", rtt_ms=11.0 + rng.random() * 6.0)
    sampler.add_command("executed", rtt_ms=38.0 + rng.random() * 12.0)
    sampler.add_command("failed", None)
    sampler.end(duration_seconds=60.0)
    record.phone_capture_fps = 9.8
    record.pc_receive_fps = 9.5
    record.pc_display_fps = 9.4
    record.phone_inference_fps = 8.6
    record.dropped_frames = 12

    export_csv(record, os.path.join(ARTIFACTS, "perf-sample.csv"))
    export_summary(record, os.path.join(ARTIFACTS, "perf-sample.txt"))
    export_json(record, os.path.join(ARTIFACTS, "perf-sample.json"))

    # ---- 3. 汇总清单 ----
    print("\n[artifacts] 产物清单:")
    for base, _dirs, files in os.walk(ARTIFACTS):
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, ARTIFACTS)
            print(f"  {rel}  ({os.path.getsize(path) / 1024:.1f} KB)")

    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
