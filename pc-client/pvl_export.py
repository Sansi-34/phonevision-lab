"""
PhoneVision Lab — 模型导出（TFLite）+ 导出前后一致性校验。

职责：把训练好的 Keras 模型转换成 TFLite，打成"模型包"（zip），
并用固定样本对比导出前后的输出，记录数值误差。

为什么这样设计：
  - 模型包必须自描述：模型文件、类别标签、输入尺寸、张量布局、颜色顺序、
    缩放/裁剪/归一化规则、输出解释方式、版本与兼容信息全部写进 manifest.json。
    手机端导入时逐项校验，不匹配就明确拒绝，而不是"猜一套预处理"。
  - 一致性校验是硬要求：导出前后用同一批固定样本跑推理，记录最大绝对误差
    与 Top-1 一致率。误差过大说明转换/量化出了问题，绝不当成成功导出。
  - float16 量化是默认：旧手机 CPU 上比 float32 快、体积减半，且分类任务的
    精度损失通常可忽略（用上面的误差指标量化说明）。未经验证不声称帧率收益。

模型包结构（zip）：
  model.tflite          转换后的模型
  manifest.json         全部自描述元数据（见 build_manifest）
  labels.json           类别标签（索引 -> 显示名）
  consistency.json      固定样本一致性校验结果
  README.txt            人类可读说明（来源、许可、复现命令）
"""
from __future__ import annotations

import io
import json
import os
import time
import zipfile
from dataclasses import dataclass, field

# 模型包格式版本：升级结构时递增，旧包在手机上会被明确拒绝。
MODEL_PACKAGE_FORMAT_VERSION = 1

# 一致性校验允许的最大绝对误差（float16 量化后通常 < 0.02）。
MAX_ABS_ERROR_TOLERANCE = 0.05

# 一致性校验允许的最小 Top-1 一致率。
MIN_TOP1_AGREEMENT = 0.98

# 固定样本数量（用于导出前后对比；从验证集均匀取样）。
CONSISTENCY_SAMPLES = 8


@dataclass
class ExportResult:
    """一次导出的结果。"""

    success: bool = False
    package_path: str = ""
    tflite_path: str = ""
    manifest: dict = field(default_factory=dict)
    consistency: dict = field(default_factory=dict)
    error: str = ""
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "package_path": self.package_path,
            "tflite_path": self.tflite_path,
            "manifest": self.manifest,
            "consistency": self.consistency,
            "error": self.error,
            "warnings": self.warnings,
        }


def build_manifest(config, spec, class_names, display_names,
                   tflite_bytes: int, extra: dict | None = None) -> dict:
    """构造模型包的 manifest（自描述元数据）。"""
    from pvl_train import PRETRAINED_INFO

    manifest = {
        "format_version": MODEL_PACKAGE_FORMAT_VERSION,
        "app": "PhoneVisionLab",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": {
            "file": "model.tflite",
            "format": "tflite",
            "bytes": int(tflite_bytes),
            "architecture": PRETRAINED_INFO["architecture"],
            "quantization": "float16",
            "input": {
                "shape": [1, spec.input_size, spec.input_size, 3]
                if spec.layout == "NHWC" else [1, 3, spec.input_size, spec.input_size],
                "layout": spec.layout,
                "dtype": "float32",
                "color_order": spec.color_order,
            },
            "output": {
                "shape": [1, len(class_names)],
                "dtype": "float32",
                "interpretation": "softmax 概率分布，索引对应 labels.json 的顺序",
            },
        },
        "labels": {
            "file": "labels.json",
            "count": len(class_names),
            "index_to_name": {str(i): name for i, name in enumerate(class_names)},
            "index_to_display": {str(i): d for i, d in enumerate(display_names)},
        },
        "preprocess": spec.to_dict(),
        "training": {
            "dataset_root": config.dataset_root,
            "epochs": config.epochs,
            "batch_size": config.batch_size,
            "learning_rate": config.learning_rate,
            "seed": config.seed,
            "device": config.device,
            "val_ratio": config.val_ratio,
            "fine_tune_last_n": config.fine_tune_last_n,
        },
        "pretrained": PRETRAINED_INFO,
        "runtime": {
            "android_min_sdk": 21,
            "abis": ["arm64-v8a", "armeabi-v7a", "x86", "x86_64"],
            "accelerator": "cpu",
            "accelerator_note": (
                "默认仅使用 CPU；NNAPI/GPU 委派需真机验证后才可启用，"
                "未验证前不声称支持。"),
        },
    }
    if extra:
        manifest.update(extra)
    return manifest


def convert_to_tflite(model, spec, representative_dataset=None,
                      float16: bool = True):
    """把 Keras 模型转成 TFLite 字节。

    float16=True 时启用 float16 量化（默认，权衡速度/体积/精度）。
    不做 int8 全量化：那需要代表性数据集校准，且分类任务上更容易掉点，
    首版保持可解释性。
    """
    import tensorflow as tf

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    if float16:
        converter.target_spec.supported_types = [tf.float16]
    if representative_dataset is not None:
        converter.representative_dataset = representative_dataset
    return converter.convert()


def compare_outputs(keras_model, tflite_bytes: bytes, spec, samples,
                    dataset_root: str, class_names: list,
                    log=None) -> dict:
    """用固定样本对比导出前后的输出，返回误差报告。

    - 每张样本都走同一条预处理（pvl_preprocess.preprocess），保证"同一输入"。
    - 记录每张的 max_abs_error，以及 Top-1 是否一致。
    - 汇总 max_abs_error（全样本最大）与 top1_agreement（一致率）。
    """
    import numpy as np
    import tensorflow as tf
    from PIL import Image

    from pvl_preprocess import preprocess, softmax, top_k

    def _log(text):
        if log is not None:
            log(text)

    # 固定样本：从传入 samples 均匀取样，保证可复现。
    picked = _pick_evenly(samples, CONSISTENCY_SAMPLES)

    interpreter = tf.lite.Interpreter(model_content=tflite_bytes)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    # 校验 TFLite 实际输入形状与 spec 一致，不一致就报错而不是硬跑。
    actual_shape = list(input_details[0]["shape"])
    expected_shape = [1, spec.input_size, spec.input_size, 3] \
        if spec.layout == "NHWC" else [1, 3, spec.input_size, spec.input_size]
    if actual_shape != expected_shape:
        raise ValueError(
            f"TFLite 输入形状 {actual_shape} 与 spec 声明的 {expected_shape} 不一致")

    per_sample = []
    max_abs_error = 0.0
    top1_agree = 0

    for s in picked:
        full = os.path.join(dataset_root, s.relative_path)
        with Image.open(full) as img:
            rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)
        bgr = rgb[:, :, ::-1]
        tensor = preprocess(bgr, spec)

        keras_out = np.asarray(keras_model(tensor, training=False))[0]
        interpreter.set_tensor(input_details[0]["index"], tensor)
        interpreter.invoke()
        tfl_out = np.asarray(interpreter.get_tensor(output_details[0]["index"]))[0]

        # TFLite 输出可能是 logits 或概率；统一按"概率分布"解释前先 softmax 化，
        # 保证两边可比（Keras 模型最后一层是 softmax，输出已是概率）。
        if float(np.sum(tfl_out)) <= 0 or abs(float(np.sum(tfl_out)) - 1.0) > 0.05:
            tfl_prob = softmax(tfl_out)
        else:
            tfl_prob = tfl_out.astype(np.float32)
        keras_prob = keras_out.astype(np.float32)

        err = float(np.max(np.abs(keras_prob - tfl_prob)))
        max_abs_error = max(max_abs_error, err)
        k_top = top_k(keras_prob, 1)[0][0]
        t_top = top_k(tfl_prob, 1)[0][0]
        if k_top == t_top:
            top1_agree += 1
        per_sample.append({
            "sample": s.relative_path,
            "class": s.class_name,
            "keras_top1": class_names[k_top] if k_top < len(class_names) else str(k_top),
            "tflite_top1": class_names[t_top] if t_top < len(class_names) else str(t_top),
            "max_abs_error": round(err, 6),
            "top1_agree": k_top == t_top,
        })

    agreement = top1_agree / max(1, len(per_sample))
    report = {
        "samples": len(per_sample),
        "max_abs_error": round(max_abs_error, 6),
        "top1_agreement": round(agreement, 4),
        "tolerance": MAX_ABS_ERROR_TOLERANCE,
        "min_top1_agreement": MIN_TOP1_AGREEMENT,
        "passed": (max_abs_error <= MAX_ABS_ERROR_TOLERANCE
                   and agreement >= MIN_TOP1_AGREEMENT),
        "per_sample": per_sample,
    }
    _log(f"一致性校验: {len(per_sample)} 个样本, "
         f"最大绝对误差 {report['max_abs_error']:.6f}, "
         f"Top-1 一致率 {report['top1_agreement']:.2%} -> "
         f"{'通过' if report['passed'] else '未通过'}")
    return report


def _pick_evenly(samples, count: int) -> list:
    """从样本列表均匀取 count 个（不足则全取），保持确定性。"""
    if len(samples) <= count:
        return list(samples)
    step = len(samples) / float(count)
    return [samples[int(i * step)] for i in range(count)]


def write_package(package_path: str, tflite_bytes: bytes, manifest: dict,
                  labels: list, display_labels: list, consistency: dict,
                  readme: str = "") -> str:
    """把模型包写成 zip 文件。"""
    os.makedirs(os.path.dirname(os.path.abspath(package_path)), exist_ok=True)
    tmp = package_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("model.tflite", tflite_bytes)
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("labels.json", json.dumps(
            {"index_to_name": {str(i): n for i, n in enumerate(labels)},
             "index_to_display": {str(i): d for i, d in enumerate(display_labels)}},
            ensure_ascii=False, indent=2))
        zf.writestr("consistency.json",
                    json.dumps(consistency, ensure_ascii=False, indent=2))
        zf.writestr("README.txt", readme or _default_readme(manifest))
    os.replace(tmp, package_path)
    return package_path


def _default_readme(manifest: dict) -> str:
    labels = manifest.get("labels", {}).get("index_to_name", {})
    return (
        "PhoneVision Lab 模型包\n"
        "========================\n\n"
        "包含内容：\n"
        "  model.tflite     转换后的 TFLite 模型（float16 量化）\n"
        "  manifest.json    完整自描述元数据（输入/输出/预处理/训练参数）\n"
        "  labels.json      类别标签（索引 -> 名称）\n"
        "  consistency.json 导出前后一致性校验记录\n\n"
        f"类别（{len(labels)} 个）: "
        + ", ".join(f"{k}={v}" for k, v in sorted(labels.items(), key=lambda kv: int(kv[0])))
        + "\n\n"
        "导入方法：在手机 App 的\"本机 AI 推理\"模式点\"导入模型\"，选择本文件。\n"
        "本模型在手机本机离线推理，不依赖网络与电脑。\n\n"
        f"预训练权重来源: {manifest.get('pretrained', {}).get('source', 'n/a')}\n"
        f"许可证: {manifest.get('pretrained', {}).get('license', 'n/a')}\n"
    )


def export_model(keras_path: str, config, spec, output_dir: str,
                 split_path: str, package_name: str = "",
                 log=None) -> ExportResult:
    """完整导出流程：加载模型 -> 转 TFLite -> 一致性校验 -> 打模型包。

    任一步骤不满足要求都返回 success=False 与明确原因，绝不产出
    "看似成功但实际不可用"的模型包。
    """
    result = ExportResult()

    def _log(text):
        if log is not None:
            log(text)

    try:
        # An interrupted/failed run may leave best.keras behind. Only a finished
        # run with the minimum number of training steps is eligible for export.
        from pvl_train import MIN_TRAIN_STEPS_FOR_EXPORT
        if not os.path.isfile(keras_path):
            result.error = f"找不到训练产物: {keras_path}"
            return result
        history_path = os.path.join(os.path.dirname(keras_path), "history.json")
        if not os.path.isfile(history_path):
            result.error = "训练未完成或缺少训练记录，不能导出"
            return result
        with open(history_path, encoding="utf-8") as fh:
            history = json.load(fh)
        if int(history.get("total_steps", 0)) < MIN_TRAIN_STEPS_FOR_EXPORT:
            result.error = "训练步数不足，不能导出"
            return result

        import tensorflow as tf
        from pvl_preprocess import PreprocessSpec
        from pvl_split import load_split

        spec = spec if isinstance(spec, PreprocessSpec) else \
            PreprocessSpec.from_dict(config.preprocess or {})
        problems = spec.validate()
        if problems:
            result.error = "预处理配置非法：" + "；".join(problems)
            return result

        _log(f"加载训练模型: {keras_path}")
        model = tf.keras.models.load_model(keras_path)

        # 校验模型输出类别数与配置一致（防止训练中途改过类别）。
        out_units = int(model.output_shape[-1])
        if out_units != len(config.class_names):
            result.error = (
                f"模型输出 {out_units} 与类别数 {len(config.class_names)} 不一致")
            return result

        _log("转换为 TFLite（float16 量化）…")
        tflite_bytes = convert_to_tflite(model, spec, float16=True)
        result.tflite_path = os.path.join(output_dir, "model.tflite")
        with open(result.tflite_path, "wb") as fh:
            fh.write(tflite_bytes)
        _log(f"TFLite 大小: {len(tflite_bytes) / 1024:.1f} KB")

        # ---- 一致性校验 ----
        split = load_split(split_path)
        if not split.val:
            result.warnings.append(
                "验证集为空，一致性校验改用训练集样本（指标仅供参考）")
            consistency_samples = split.train
        else:
            consistency_samples = split.val
        consistency = compare_outputs(
            model, tflite_bytes, spec, consistency_samples,
            config.dataset_root, config.class_names, log=_log)
        result.consistency = consistency
        if not consistency.get("passed"):
            result.error = (
                f"一致性校验未通过：最大绝对误差 {consistency.get('max_abs_error')}"
                f"（容差 {MAX_ABS_ERROR_TOLERANCE}）、"
                f"Top-1 一致率 {consistency.get('top1_agreement')}"
                f"（要求 >= {MIN_TOP1_AGREEMENT}）。"
                f"这通常意味着量化或转换出了问题，不导出。")
            return result

        # ---- 打模型包 ----
        manifest = build_manifest(
            config, spec, config.class_names, config.display_names,
            len(tflite_bytes))
        name = package_name or os.path.basename(output_dir)
        package_path = os.path.join(output_dir, f"{name}.pvlmodel.zip")
        write_package(
            package_path, tflite_bytes, manifest,
            config.class_names, config.display_names, consistency)
        result.package_path = package_path
        result.manifest = manifest
        result.success = True
        _log(f"模型包已生成: {package_path}")
        return result

    except Exception as e:  # noqa: BLE001 - 导出失败转为可展示状态
        import traceback
        result.error = f"导出失败: {e}"
        result.warnings.append(traceback.format_exc(limit=3))
        if log is not None:
            log(result.error)
            log(traceback.format_exc(limit=3))
        return result
