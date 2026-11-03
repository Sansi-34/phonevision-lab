"""
PhoneVision Lab — 模型训练（轻量图像分类迁移学习）。

职责：用 MobileNetV3Small（ImageNet 预训练权重）做迁移学习，训练自定义类别
的图像分类模型，并保存最佳权重与训练配置。

为什么这样设计：
  - 选 MobileNetV3Small：ImageNet 预训练 + 参数量小（约 2.9M），
    转换 TFLite 后约 3-4 MB，适合旧手机 CPU 推理。
  - 训练依赖（TensorFlow）刻意放在独立模块：本文件只在真正训练时被 import，
    普通预览/采集/推理客户端不需要安装 TensorFlow。见 requirements-train.txt。
  - CPU 路径是默认：旧笔记本/台式机都能跑。检测到可用 GPU 时才允许启用
    （并在配置里记录实际使用的设备，绝不在未验证时承诺加速）。
  - 取消是协作式的：每步检查 should_stop，训练循环干净退出并落盘当前状态，
    不留下僵尸进程。GUI 关闭时 join 线程回收资源。

预训练权重来源与许可（写进模型包与文档，供追溯）：
  - MobileNetV3Small 的 ImageNet 权重由 Keras Applications 提供
    （tensorflow.keras.applications），权重文件托管在 Google 的
    storage.googleapis.com 下载源。
  - 权重遵循 Apache License 2.0（与 Keras/TensorFlow 相同）。
  - 首次训练会自动下载（约 8 MB）；离线准备方法见 docs/training.md：
    预先跑一次联网训练，权重会缓存在 ~/.keras/models/，之后离线可用。
  - 绝不把随机初始化的模型包装成"训练成果"：未达到最少步数或未加载
    预训练权重时，导出会被拒绝。

初学者调试观察点：
  - 准确率不动：先看学习率是否过大、样本是否足够、类别是否失衡。
  - 显存/内存爆掉：减小 batch_size 或输入尺寸。
  - 训练完模型很大：确认用的是 MobileNetV3Small 且做了 float16 量化选项。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field

# 默认训练参数（经验值，针对几十到几百张/类的小数据集）。
DEFAULT_EPOCHS = 15
DEFAULT_BATCH_SIZE = 16
DEFAULT_LEARNING_RATE = 1e-3
DEFAULT_INPUT_SIZE = 224
DEFAULT_FINE_TUNE_LAST_N = 20      # 解冻骨干网最后 N 层做微调

# 训练不足该步数时不允许导出（防止把未训练模型当成果）。
MIN_TRAIN_STEPS_FOR_EXPORT = 5

# 预训练权重来源信息（写进模型包与文档）。
PRETRAINED_INFO = {
    "architecture": "MobileNetV3Small",
    "source": "tensorflow.keras.applications.MobileNetV3Small",
    "weights": "imagenet",
    "license": "Apache-2.0",
    "download_host": "storage.googleapis.com",
    "approx_size_mb": 8.0,
    "offline_prepare": (
        "联网运行一次训练，权重缓存到 ~/.keras/models/ 后即可离线使用；"
        "或从 Keras Applications 官方源手动下载 weights h5 放到该目录。"
    ),
}


@dataclass
class TrainConfig:
    """训练配置（全部字段都会写进模型包，保证可复现）。"""

    dataset_root: str = ""
    input_size: int = DEFAULT_INPUT_SIZE
    epochs: int = DEFAULT_EPOCHS
    batch_size: int = DEFAULT_BATCH_SIZE
    learning_rate: float = DEFAULT_LEARNING_RATE
    fine_tune_last_n: int = DEFAULT_FINE_TUNE_LAST_N
    seed: int = 1234
    device: str = "cpu"                 # "cpu" 或 "gpu"
    val_ratio: float = 0.2
    class_names: list = field(default_factory=list)   # 规范化后的类别名（顺序=标签索引）
    display_names: list = field(default_factory=list)
    # 预处理契约（与 pvl_preprocess.PreprocessSpec 对应，避免训练端 import 依赖）
    preprocess: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrainConfig":
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in (data or {}).items() if k in known}
        return cls(**kwargs)


@dataclass
class TrainProgress:
    """训练进度快照（GUI 轮询显示，绝不阻塞）。"""

    state: str = "idle"        # idle/running/done/cancelled/error
    epoch: int = 0
    total_epochs: int = 0
    step: int = 0
    total_steps: int = 0
    loss: float = 0.0
    accuracy: float = 0.0
    val_loss: float = 0.0
    val_accuracy: float = 0.0
    best_val_accuracy: float = 0.0
    elapsed_seconds: float = 0.0
    message: str = ""
    log_lines: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _set_seeds(seed: int) -> None:
    """固定随机种子，保证训练可复现（CPU 路径完整；GPU 上仍可能有非确定性算子）。"""
    import numpy as np
    import tensorflow as tf

    np.random.seed(seed)
    tf.keras.utils.set_random_seed(seed)


def _detect_gpus() -> list:
    """返回可用 GPU 设备名列表（无 GPU 返回空列表）。"""
    try:
        import tensorflow as tf
        return [g.name for g in tf.config.list_physical_devices("GPU")]
    except Exception:  # noqa: BLE001 - 探测失败按"无 GPU"处理
        return []


def resolve_device(requested: str) -> tuple:
    """把请求的设备解析成 (实际设备, 说明)。

    - 请求 gpu 但无 GPU：回落到 cpu 并明确说明，绝不静默假装加速。
    - 请求 cpu：就用 cpu。
    """
    gpus = _detect_gpus()
    if requested == "gpu":
        if gpus:
            return "gpu", f"使用 GPU: {', '.join(gpus)}"
        return "cpu", "未检测到可用 GPU，已回落到 CPU（不承诺加速）"
    return "cpu", "使用 CPU 训练"


def _emit_log(log, text: str) -> None:
    """把一行日志转发给调用方（GUI 收集用）。异常绝不外溢。"""
    if log is None:
        return
    try:
        log(text)
    except Exception:  # noqa: BLE001 - 日志回调异常不能中断训练
        pass


def build_model(num_classes: int, input_size: int,
                fine_tune_last_n: int = DEFAULT_FINE_TUNE_LAST_N,
                log=None):
    """构造 MobileNetV3Small 迁移学习模型。

    返回 (model, base_model)。base_model 暴露出来便于分别设置训练态。
    """
    import tensorflow as tf

    _emit_log(log, f"加载 MobileNetV3Small 预训练权重（ImageNet）…")
    base = tf.keras.applications.MobileNetV3Small(
        input_shape=(input_size, input_size, 3),
        include_top=False,
        include_preprocessing=True,
        weights="imagenet",
    )
    base.trainable = False

    inputs = tf.keras.Input(shape=(input_size, input_size, 3))
    x = base(inputs, training=False)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(0.2)(x)
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax")(x)
    model = tf.keras.Model(inputs, outputs)
    _emit_log(log, f"模型参数量: {model.count_params():,}")
    return model, base


def fine_tune(model, base, last_n: int, log=None) -> None:
    """解冻骨干网最后 last_n 层做微调（BatchNorm 保持推理态）。"""
    import tensorflow as tf

    base.trainable = True
    total = len(base.layers)
    start = max(0, total - max(1, int(last_n)))
    for layer in base.layers[:start]:
        layer.trainable = False
    # BatchNorm 在微调期必须保持 inference 行为，否则统计被小 batch 打乱。
    for layer in base.layers[start:]:
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False
    _emit_log(log, f"微调：解冻骨干网最后 {total - start} 层（共 {total} 层）")


def train_model(config: TrainConfig, split_path: str, output_dir: str,
                should_stop=None, on_progress=None, log=None):
    """执行训练，保存最佳模型与配置。

    参数：
      config        TrainConfig
      split_path    pvl_split 生成的 split.json
      output_dir    产物目录（best.keras / config.json / history.json）
      should_stop   可调用对象，返回 True 时协作式取消
      on_progress   可调用对象，接收 TrainProgress
      log           可调用对象，接收日志字符串

    返回 TrainProgress（终态）。失败时 state="error" 且 message 有原因，
    绝不抛出到 GUI 线程。
    """
    started = time.time()
    progress = TrainProgress(
        state="running",
        total_epochs=config.epochs,
        total_steps=0,
    )

    def _log(text):
        if log is not None:
            try:
                log(text)
            except Exception:  # noqa: BLE001 - 日志回调异常绝不能中断训练
                pass

    def _emit(**kwargs):
        for key, value in kwargs.items():
            setattr(progress, key, value)
        progress.elapsed_seconds = time.time() - started
        if on_progress is not None:
            try:
                on_progress(progress)
            except Exception:  # noqa: BLE001 - 进度回调异常绝不能中断训练
                pass

    def _logline(text: str) -> None:
        progress.log_lines.append(text)
        if len(progress.log_lines) > 500:
            progress.log_lines = progress.log_lines[-500:]
        _log(text)
        _emit()

    device_scope = None
    try:
        # ---- 延迟 import：只有真正训练才加载 TensorFlow ----
        import numpy as np  # noqa: F401 - 由 tf 间接使用
        import tensorflow as tf
        from pvl_preprocess import PreprocessSpec, preprocess
        from pvl_split import load_split

        device, device_note = resolve_device(config.device)
        _logline(f"设备: {device}（{device_note}）")
        scope = tf.device("/GPU:0" if device == "gpu" else "/CPU:0")
        scope.__enter__()
        device_scope = scope

        _set_seeds(config.seed)
        _logline(f"随机种子: {config.seed}")

        split = load_split(split_path)
        if not split.train or not split.val:
            raise ValueError(
                "训练集或验证集为空：请先完成数据划分（每个类别至少 2 个采集批次）")
        _logline(f"训练样本 {len(split.train)} 张，验证样本 {len(split.val)} 张")

        spec = PreprocessSpec.from_dict(config.preprocess) if config.preprocess \
            else PreprocessSpec(input_size=config.input_size, normalization="raw")
        problems = spec.validate()
        if problems:
            raise ValueError("预处理配置非法：" + "；".join(problems))
        if (spec.normalization != "raw" or spec.color_order != "RGB"
                or spec.layout != "NHWC" or spec.input_size != config.input_size):
            raise ValueError("MobileNetV3 训练要求 RGB、NHWC、raw [0,255] 且输入尺寸一致；请重新配置训练")
        config.preprocess = spec.to_dict()
        _logline(f"预处理: {spec.input_size}px {spec.color_order} "
                 f"{spec.layout} {spec.normalization}")

        if any(os.path.exists(os.path.join(output_dir, name))
               for name in ("best.keras", "history.json")):
            raise ValueError("训练目录已有模型或记录，请选择新的运行目录以避免覆盖")
        os.makedirs(output_dir, exist_ok=True)

        # ---- 数据加载（小数据集：全部读入内存；大数据集应改为 tf.data 生成器）----
        _logline("加载图片数据…")
        train_x, train_y = _load_split_arrays(
            split.train, config, spec, log=_logline)
        val_x, val_y = _load_split_arrays(
            split.val, config, spec, log=_logline)
        num_classes = len(config.class_names)
        if num_classes < 2:
            raise ValueError("至少需要 2 个类别才能训练分类模型")
        _logline(f"类别数: {num_classes}")

        # ---- 构建模型 ----
        model, base = build_model(
            num_classes, config.input_size,
            fine_tune_last_n=config.fine_tune_last_n, log=_logline)

        stage1_epochs = max(1, config.epochs // 2)
        stage2_epochs = max(1, config.epochs - stage1_epochs)
        progress.total_steps = ((len(train_x) + config.batch_size - 1) // config.batch_size) * \
            (stage1_epochs + stage2_epochs)

        best_path = os.path.join(output_dir, "best.keras")
        best_acc = -1.0
        global_step = 0

        # ---- 阶段 1：冻结骨干网，只训练分类头 ----
        _logline(f"阶段 1/2：冻结骨干网训练分类头（{stage1_epochs} epochs）")
        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=config.learning_rate),
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )
        global_step = _run_epochs(
            model, train_x, train_y, val_x, val_y,
            epochs=stage1_epochs, batch_size=config.batch_size,
            progress=progress, start_step=global_step, epoch_offset=0,
            should_stop=should_stop, _emit=_emit, _logline=_logline,
            best_state={"acc": best_acc, "path": best_path})

        if should_stop is not None and should_stop():
            _emit(state="cancelled", message="训练已被用户取消")
            _save_config(config, output_dir, split_path)
            return progress

        # ---- 阶段 2：微调骨干网最后 N 层 ----
        _logline(f"阶段 2/2：微调骨干网最后 {config.fine_tune_last_n} 层"
                 f"（{stage2_epochs} epochs）")
        fine_tune(model, base, config.fine_tune_last_n, log=_logline)
        # 微调期用更小的学习率（默认 1/10），避免破坏预训练特征。
        model.compile(
            optimizer=tf.keras.optimizers.Adam(
                learning_rate=config.learning_rate / 10.0),
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )
        global_step = _run_epochs(
            model, train_x, train_y, val_x, val_y,
            epochs=stage2_epochs, batch_size=config.batch_size,
            progress=progress, start_step=global_step, epoch_offset=stage1_epochs,
            should_stop=should_stop, _emit=_emit, _logline=_logline,
            best_state={"acc": progress.best_val_accuracy, "path": best_path})

        if should_stop is not None and should_stop():
            _emit(state="cancelled", message="训练已被用户取消")
            _save_config(config, output_dir, split_path)
            return progress

        if global_step < MIN_TRAIN_STEPS_FOR_EXPORT:
            raise ValueError(
                f"训练步数过少（{global_step} < {MIN_TRAIN_STEPS_FOR_EXPORT}），"
                f"不能作为训练成果导出")

        # ---- 保存最佳模型与训练元数据 ----
        if os.path.isfile(best_path):
            _logline(f"已保存最佳模型（验证准确率 "
                     f"{progress.best_val_accuracy:.4f}）: {best_path}")
        else:
            # 未触发过保存（极端情况）：保存当前权重，绝不留下空目录。
            model.save(best_path)
            _logline(f"已保存最终模型: {best_path}")

        history = {
            "best_val_accuracy": progress.best_val_accuracy,
            "final_val_accuracy": progress.val_accuracy,
            "final_val_loss": progress.val_loss,
            "total_steps": global_step,
            "elapsed_seconds": time.time() - started,
            "device": device,
            "device_note": device_note,
            "seed": config.seed,
        }
        with open(os.path.join(output_dir, "history.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(history, fh, ensure_ascii=False, indent=2)
        _save_config(config, output_dir, split_path)

        _emit(state="done",
              message=f"训练完成，最佳验证准确率 {progress.best_val_accuracy:.4f}")
        return progress

    except Exception as e:  # noqa: BLE001 - 训练失败必须转为可展示状态
        import traceback
        detail = traceback.format_exc(limit=3)
        _logline(f"训练失败: {e}")
        _logline(detail)
        _emit(state="error", message=str(e))
        return progress
    finally:
        if device_scope is not None:
            device_scope.__exit__(None, None, None)


def _run_epochs(model, train_x, train_y, val_x, val_y, epochs, batch_size,
                progress, start_step, epoch_offset, should_stop, _emit,
                _logline, best_state) -> int:
    """跑若干 epoch，逐 step 回调进度，返回累计 step 数。

    epoch_offset 是"本阶段之前已完成的 epoch 数"，用于让界面上的
    Epoch N/M 连续递增（阶段 1 跑完 5 个，阶段 2 从 6 开始）。
    """
    import tensorflow as tf

    step = start_step
    best_path = best_state["path"]
    best_acc = best_state["acc"]

    for epoch in range(epochs):
        if should_stop is not None and should_stop():
            return step
        progress.epoch = epoch_offset + epoch + 1
        _emit(message=f"Epoch {progress.epoch}/{progress.total_epochs}")

        # 手动分 batch：这样能在每个 step 后检查取消并回调进度，
        # 比 model.fit(callbacks=...) 更直接，也避免回调跨线程问题。
        indices = tf.random.shuffle(tf.range(len(train_x)))
        epoch_loss = 0.0
        epoch_correct = 0
        epoch_seen = 0
        for start in range(0, len(train_x), batch_size):
            if should_stop is not None and should_stop():
                return step
            batch_idx = indices[start:start + batch_size]
            bx = tf.gather(train_x, batch_idx)
            by = tf.gather(train_y, batch_idx)
            logs = model.train_on_batch(bx, by, return_dict=True)
            step += 1
            epoch_loss += float(logs.get("loss", 0.0))
            epoch_correct += float(logs.get("accuracy", 0.0)) * len(bx)
            epoch_seen += len(bx)
            _emit(step=step, loss=float(logs.get("loss", 0.0)),
                  accuracy=float(logs.get("accuracy", 0.0)),
                  message=f"step {step}/{progress.total_steps}")

        # epoch 末评估验证集
        val_logs = model.evaluate(val_x, val_y, verbose=0, return_dict=True)
        val_acc = float(val_logs.get("accuracy", 0.0) or 0.0)
        val_loss = float(val_logs.get("loss", 0.0) or 0.0)
        progress.val_accuracy = val_acc
        progress.val_loss = val_loss
        progress.loss = epoch_loss / max(1, epoch_seen)
        progress.accuracy = epoch_correct / max(1, epoch_seen)

        if val_acc > best_acc:
            best_acc = val_acc
            progress.best_val_accuracy = val_acc
            model.save(best_path)
            best_state["acc"] = best_acc
            _logline(f"  Epoch {progress.epoch}: 验证准确率提升到 "
                     f"{val_acc:.4f}（已保存最佳模型）")
        else:
            _logline(f"  Epoch {progress.epoch}: 验证准确率 {val_acc:.4f}"
                     f"（最佳 {best_acc:.4f}）")

    return step


def _load_split_arrays(samples, config: TrainConfig, spec, log=None):
    """把样本列表读成 (float32 张量, int 标签) 两个 numpy 数组。"""
    import numpy as np
    import tensorflow as tf
    from PIL import Image

    from pvl_preprocess import preprocess

    class_index = {c: i for i, c in enumerate(config.class_names)}
    xs = []
    ys = []
    for s in samples:
        full = os.path.join(config.dataset_root, s.relative_path)
        with Image.open(full) as img:
            rgb = img.convert("RGB")
        arr = np.asarray(rgb, dtype=np.uint8)
        # PIL 给的是 RGB；preprocess 期望 BGR（OpenCV 语义），转回去保持契约一致。
        bgr = arr[:, :, ::-1]
        tensor = preprocess(bgr, spec)[0]
        xs.append(tensor)
        ys.append(class_index[s.class_name])
    _emit_log(log, f"  读取 {len(xs)} 张（{len(set(ys))} 个类别）")
    return (tf.constant(np.stack(xs), dtype=tf.float32),
            tf.constant(np.asarray(ys, dtype=np.int32)))


def _save_config(config: TrainConfig, output_dir: str, split_path: str) -> None:
    """把训练配置与划分信息写入产物目录（保证可复现）。"""
    payload = config.to_dict()
    payload["split_path"] = split_path
    payload["pretrained"] = PRETRAINED_INFO
    with open(os.path.join(output_dir, "config.json"), "w",
              encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


class Trainer:
    """训练任务的线程封装：独立线程运行，GUI 只轮询进度。

    为什么用线程而不是子进程：TensorFlow 已在本进程内加载权重与数据，
    线程足够且更易共享数据；取消通过协作式 should_stop 实现，退出前
    join(timeout) 回收，避免遗留训练线程。
    """

    def __init__(self, config: TrainConfig, split_path: str, output_dir: str):
        self.config = config
        self.split_path = split_path
        self.output_dir = output_dir
        self._stop_event = None
        self._thread = None
        self.progress = TrainProgress(total_epochs=config.epochs)
        self._log_lines: list = []

    def start(self) -> None:
        import threading

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event = threading.Event()

        def _should_stop():
            return self._stop_event.is_set()

        def _on_progress(p):
            self.progress = p

        def _log(text):
            self._log_lines.append(text)

        def _run():
            try:
                train_model(
                    self.config, self.split_path, self.output_dir,
                    should_stop=_should_stop, on_progress=_on_progress, log=_log)
            finally:
                with self._lock:
                    pass

        self._lock = __import__("threading").Lock()
        self._thread = threading.Thread(target=_run, daemon=True,
                                        name="pvl-trainer")
        self._thread.start()

    def cancel(self) -> None:
        """请求取消（协作式）；训练循环会在当前 step 结束后退出。"""
        if self._stop_event is not None:
            self._stop_event.set()

    def join(self, timeout: float = 5.0) -> None:
        """等待训练线程退出（GUI 关闭时调用，回收资源）。"""
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def log_text(self) -> str:
        return "\n".join(self._log_lines)
