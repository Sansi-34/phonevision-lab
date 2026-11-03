"""
PhoneVision Lab Web — 训练与导出任务服务（后台运行 + 可查询进度）。

职责：把 pc-client 的 pvl_train / pvl_export / pvl_split 包成"任务"，
让网页可以启动训练、轮询进度、取消、导出，而不阻塞 HTTP 请求。

为什么这样设计：
  - 浏览器不能直接跑现有 Python 训练代码（TensorFlow 不在浏览器里），
    因此训练必须跑在本服务进程/线程中；页面只发命令 + 轮询进度。
  - 训练用 pvl_train.Trainer 的协作式取消（should_stop），与桌面客户端
    完全同一套实现，不复制训练逻辑。
  - 环境检测独立成函数：没装 TensorFlow 时返回明确的缺失原因与修复命令，
    前端把"开始训练"置灰并展示原因，而不是留一个不能点的按钮。
  - 导出走 pvl_export.export_model：一致性校验不通过时它会拒绝产出模型包，
    本服务只如实转发结果，绝不把失败包装成成功。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback

_PC_CLIENT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from .util import (  # noqa: E402
    ApiError, ERR_BUSY, ERR_TRAIN_ENV, StoppableThread, safe_float, safe_int,
    traceback_text,
)


# 环境检测缓存：导入 TensorFlow 需要数秒，没必要每次请求都重新 import。
_ENV_CACHE: dict | None = None
_ENV_CACHE_LOCK = threading.Lock()


def training_environment() -> dict:
    """检测训练环境（真实结果，不猜测）。结果缓存到进程内。"""
    global _ENV_CACHE
    with _ENV_CACHE_LOCK:
        if _ENV_CACHE is not None:
            return dict(_ENV_CACHE)

    info = {
        "tensorflow": False,
        "tensorflow_version": "",
        "gpu": False,
        "gpu_devices": [],
        "ready": False,
        "reason": "",
        "fix_command": "pip install -r requirements.txt -r requirements-train.txt",
        "missing": [],
    }
    try:
        import tensorflow as tf  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - 导入失败就是没装/装坏了
        info["reason"] = f"未检测到 TensorFlow（{exc.__class__.__name__}）"
        info["missing"].append("tensorflow")
        with _ENV_CACHE_LOCK:
            _ENV_CACHE = dict(info)
        return info

    info["tensorflow"] = True
    info["tensorflow_version"] = getattr(tf, "__version__", "")
    try:
        gpus = [g.name for g in tf.config.list_physical_devices("GPU")]
    except Exception:  # noqa: BLE001
        gpus = []
    info["gpu"] = bool(gpus)
    info["gpu_devices"] = gpus
    if not gpus:
        info["reason"] = ("未检测到可用 GPU，将使用 CPU 训练（速度较慢但可复现；"
                          "TensorFlow 在原生 Windows 上默认不支持 GPU）")
    else:
        info["reason"] = "已检测到 GPU，可选择 GPU 训练"
    info["ready"] = True
    with _ENV_CACHE_LOCK:
        _ENV_CACHE = dict(info)
    return info


def reset_environment_cache() -> None:
    """清除环境检测缓存（安装依赖后由"重新检测"按钮调用）。"""
    global _ENV_CACHE
    with _ENV_CACHE_LOCK:
        _ENV_CACHE = None


class TrainingJob:
    """一次训练/导出任务的可变状态（线程内更新，HTTP 线程读取）。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: StoppableThread | None = None
        self._state = "idle"        # idle/running/done/cancelled/error
        self._progress = None
        self._logs: list[str] = []
        self._started_at = 0.0
        self._config = None
        self._output_dir = ""
        self._dataset_root = ""
        self._dataset_name = ""
        self._export_state = "idle"  # idle/running/done/error
        self._export_result = None
        self._export_error = ""

    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> dict:
        from pvl_train import TrainProgress
        with self._lock:
            progress = self._progress
            if progress is None:
                progress = TrainProgress(state=self._state)
            total = max(1, progress.total_steps)
            return {
                "state": self._state,
                "epoch": progress.epoch,
                "total_epochs": progress.total_epochs,
                "step": progress.step,
                "total_steps": progress.total_steps,
                "percent": min(100, int(progress.step * 100 / total))
                if progress.total_steps else 0,
                "loss": round(progress.loss, 4) if progress.loss else None,
                "accuracy": round(progress.accuracy, 4) if progress.accuracy else None,
                "val_loss": round(progress.val_loss, 4) if progress.val_loss else None,
                "val_accuracy": (round(progress.val_accuracy, 4)
                                 if progress.val_accuracy else None),
                "best_val_accuracy": (round(progress.best_val_accuracy, 4)
                                      if progress.best_val_accuracy else None),
                "elapsed_seconds": round(progress.elapsed_seconds, 1),
                "message": progress.message,
                "logs": list(self._logs[-200:]),
                "output_dir": self._output_dir,
                "dataset_name": self._dataset_name,
                "export_state": self._export_state,
                "export_result": self._export_result,
                "export_error": self._export_error,
                "started_at": self._started_at,
            }

    # ------------------------------------------------------------------

    def start(self, dataset_root: str, dataset_name: str, params: dict) -> dict:
        """启动训练。返回当前快照。

        前置条件（真实检查，不默认满足）：
          - 训练环境可用（TensorFlow 可导入）；
          - 数据集已划分 split.json；
          - 划分里训练集与验证集都非空；
          - 类别数 ≥ 2。
        任一条不满足 → 抛出带原因的 ApiError，前端展示原因与下一步。
        """
        from pvl_dataset import DatasetStore
        from pvl_preprocess import PreprocessSpec
        from pvl_split import load_split

        split_path = os.path.join(dataset_root, "split.json")
        if not os.path.isfile(split_path):
            raise ApiError("no_split",
                           "数据集还没有划分训练/验证集，请先在数据集工作区执行“数据体检并划分”")
        split = load_split(split_path)
        if not split.train or not split.val:
            raise ApiError("no_split",
                           "训练集或验证集为空：每个类别至少需要 2 个采集批次（避免相邻帧跨集合导致指标虚高）")

        store = DatasetStore(dataset_root)
        dataset = store.open(dataset_root)
        class_names = dataset.class_names()
        if len(class_names) < 2:
            raise ApiError("bad_request",
                           "至少需要 2 个类别才能训练分类模型")

        # 环境检测会 import TensorFlow（数秒～数十秒）。放在数据前置检查之后：
        # 数据没准备好时先用便宜、更可操作的错误回答，不让用户为一个必然失败的
        # 请求等环境探测。
        env = training_environment()
        if not env["ready"]:
            raise ApiError(ERR_TRAIN_ENV, env["reason"])

        from pvl_train import DEFAULT_BATCH_SIZE, DEFAULT_EPOCHS, TrainConfig

        params = params or {}
        # 训练参数同样来自 HTTP：非法值统一 400，而不是在 int()/float() 上崩成 500。
        epochs = safe_int(params.get("epochs") or DEFAULT_EPOCHS,
                          DEFAULT_EPOCHS, minimum=1, maximum=1000)
        batch_size = safe_int(params.get("batch_size") or DEFAULT_BATCH_SIZE,
                              DEFAULT_BATCH_SIZE, minimum=1, maximum=1024)
        input_size = safe_int(params.get("input_size") or 224, 224,
                              minimum=32, maximum=1024)
        learning_rate = safe_float(params.get("learning_rate") or 1e-3, 1e-3,
                                   minimum=1e-6, maximum=1.0, strict=True)
        fine_tune_last_n = safe_int(params.get("fine_tune_last_n") or 20, 20,
                                    minimum=0, maximum=10000)
        seed = safe_int(params.get("seed") or 1234, 1234,
                        minimum=0, maximum=2**31 - 1)
        requested_device = str(params.get("device") or "cpu")
        val_ratio = float(split.val_ratio or 0.2)

        spec = PreprocessSpec(input_size=input_size, normalization="raw")
        problems = spec.validate()
        if problems:
            raise ApiError("bad_request", "预处理配置非法：" + "；".join(problems))

        config = TrainConfig(
            dataset_root=dataset_root,
            input_size=input_size,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            fine_tune_last_n=fine_tune_last_n,
            seed=seed,
            device=requested_device,
            val_ratio=val_ratio,
            class_names=class_names,
            display_names=dataset.display_names(),
            preprocess=spec.to_dict(),
        )

        from uuid import uuid4
        from pvl_paths import runs_dir
        run_name = f"run-{DatasetStore.sanitize_name(dataset_name)}-" \
                   f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        output_dir = os.path.join(runs_dir(), run_name)
        os.makedirs(output_dir, exist_ok=False)
        run_split_path = os.path.join(output_dir, "split.json")
        import shutil
        shutil.copyfile(split_path, run_split_path)

        with self._lock:
            if self.is_running():
                raise ApiError(ERR_BUSY, "已有训练任务在进行中，请先取消或等待完成")
            self._state = "running"
            self._progress = None
            self._logs = []
            self._started_at = time.time()
            self._config = config
            self._output_dir = output_dir
            self._dataset_root = dataset_root
            self._dataset_name = dataset_name
            self._export_state = "idle"
            self._export_result = None
            self._export_error = ""

            from pvl_train import Trainer
            trainer = Trainer(config, run_split_path, output_dir)
            self._trainer = trainer

            def _run(stop_event):
                def _should_stop():
                    return stop_event.is_set()

                def _on_progress(p):
                    with self._lock:
                        self._progress = p
                        if p.state in ("done", "cancelled", "error"):
                            self._state = p.state

                def _log(text):
                    with self._lock:
                        self._logs.append(text)
                        if len(self._logs) > 500:
                            self._logs = self._logs[-500:]

                try:
                    trainer.progress.state = "running"
                    from pvl_train import train_model
                    train_model(config, run_split_path, output_dir,
                                should_stop=_should_stop,
                                on_progress=_on_progress, log=_log)
                except Exception as exc:  # noqa: BLE001 - 后台失败转状态
                    _log(f"训练失败: {exc}")
                    _log(traceback_text())
                    with self._lock:
                        self._state = "error"
                finally:
                    trainer.join(timeout=2.0)

            self._thread = StoppableThread(_run, name="pvl-web-training")

        self._thread.start()
        return self.snapshot()

    def cancel(self) -> dict:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.stop()
        with self._lock:
            if self._state == "running":
                self._state = "cancelling"
                if self._progress is not None:
                    self._progress.state = "cancelled"
                    self._progress.message = "已请求取消，正在安全停止…"
        return self.snapshot()

    # ------------------------------------------------------------------

    def export(self) -> dict:
        """导出模型包（后台线程 + 轮询）。只允许训练完成后调用。"""
        with self._lock:
            if self.is_running():
                raise ApiError(ERR_BUSY, "训练仍在进行，请等待完成后再导出")
            if self._state != "done":
                raise ApiError("not_ready",
                               "训练尚未成功完成，不能导出模型包（避免导出未训练的模型）")
            if self._export_state == "running":
                raise ApiError(ERR_BUSY, "导出已在进行中")
            config = self._config
            output_dir = self._output_dir
            run_split_path = os.path.join(output_dir, "split.json")
            self._export_state = "running"
            self._export_result = None
            self._export_error = ""

        env = training_environment()
        if not env["ready"]:
            with self._lock:
                self._export_state = "error"
                self._export_error = env["reason"]
            raise ApiError(ERR_TRAIN_ENV, env["reason"])

        def _run(stop_event):
            try:
                from pvl_export import export_model
                from pvl_preprocess import PreprocessSpec
                spec = PreprocessSpec.from_dict(config.preprocess or {})
                keras_path = os.path.join(output_dir, "best.keras")
                result = export_model(keras_path, config, spec, output_dir,
                                      run_split_path,
                                      package_name=os.path.basename(output_dir))
                with self._lock:
                    self._export_state = "done" if result.success else "error"
                    self._export_result = result.to_dict()
                    self._export_error = result.error
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._export_state = "error"
                    self._export_error = f"导出失败: {exc}"

        thread = StoppableThread(_run, name="pvl-web-export")
        with self._lock:
            self._export_thread = thread
        thread.start()
        return self.snapshot()

    def last_run(self) -> dict:
        """最近一次已完成训练的产物信息（供部署页读取真实文件）。"""
        with self._lock:
            return {
                "output_dir": self._output_dir,
                "dataset_name": self._dataset_name,
                "state": self._state,
                "export_state": self._export_state,
                "export_result": self._export_result,
            }

    def traceback(self) -> str:
        return traceback_text()
