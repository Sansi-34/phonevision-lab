"""
PhoneVision Lab — 训练与导出面板（PySide6）。

职责：在数据集面板基础上提供"训练 -> 导出模型包"的入口，显示进度、
日志、损失与验证指标，并支持取消。

为什么这样设计：
  - 训练在独立线程（pvl_train.Trainer）运行，GUI 只用 QTimer 轮询进度，
    绝不阻塞事件循环；取消是协作式的，关闭面板时 join 回收线程。
  - TensorFlow 是训练专用依赖：本模块延迟 import，普通预览/采集客户端
    没装 TensorFlow 时面板会给出明确安装提示，而不是崩掉。
  - 导出成功后直接显示一致性结果（最大误差 / Top-1 一致率），
    不通过时明确说"不导出"，绝不悄悄产出不可用的模型包。

初学者调试观察点：
  - 点开始训练提示缺依赖：按提示 pip install -r requirements-train.txt。
  - 训练很快结束但准确率低：样本太少或类别失衡，先看数据集面板的体检结果。
"""
from __future__ import annotations

import os
import shutil
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QSpinBox, QTextEdit, QVBoxLayout,
)

from pvl_paths import runs_dir
from pvl_preprocess import PreprocessSpec


class _ExportSignals(QObject):
    completed = Signal(object)


class TrainPanel(QFrame):
    """训练与导出面板。"""

    # 训练状态变化信号：state(str)
    training_state_changed = Signal(str)
    # 模型包生成成功信号：package_path(str)
    package_created = Signal(str)

    def __init__(self, translator, dataset_panel=None, parent=None):
        super().__init__(parent)
        self.tr = translator
        self.dataset_panel = dataset_panel
        self.setObjectName("trainPanel")

        self.trainer = None
        self._last_state = "idle"
        self._tensorflow_available = False
        self._export_thread = None
        self._export_signals = _ExportSignals(self)
        self._export_signals.completed.connect(self._on_export_finished)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_progress)

        self._build_ui()
        # _build_ui 内部已调用过一次 _refresh_env_label（按钮已建好）；
        # 这里只在语言切换后需要重刷文案，因此直接走 _apply_language。
        self._apply_language()
        self.tr.language_changed.connect(self._apply_language)

    # =====================================================================
    # 界面
    # =====================================================================

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        # ---- 环境提示 ----
        self.env_label = QLabel()
        self.env_label.setProperty("textRole", "caption")
        self.env_label.setWordWrap(True)
        outer.addWidget(self.env_label)
        self._refresh_env_label()

        # ---- 参数 ----
        params = QHBoxLayout()
        self.epochs_label = QLabel("Epochs")
        params.addWidget(self.epochs_label)
        self.epochs_spin = QSpinBox()
        self.epochs_spin.setRange(2, 100)
        self.epochs_spin.setValue(15)
        params.addWidget(self.epochs_spin)

        self.batch_label = QLabel("Batch")
        params.addWidget(self.batch_label)
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 64)
        self.batch_spin.setValue(16)
        params.addWidget(self.batch_spin)

        self.size_label = QLabel("Input")
        params.addWidget(self.size_label)
        self.size_combo = QComboBox()
        for size in (96, 128, 160, 192, 224):
            self.size_combo.addItem(f"{size}px", size)
        self.size_combo.setCurrentText("224px")
        params.addWidget(self.size_combo)

        self.device_label = QLabel("Device")
        params.addWidget(self.device_label)
        self.device_combo = QComboBox()
        params.addWidget(self.device_combo)
        outer.addLayout(params)

        # ---- 控制 ----
        controls = QHBoxLayout()
        self.start_button = QPushButton()
        self.start_button.clicked.connect(self.on_start)
        controls.addWidget(self.start_button)
        self.cancel_button = QPushButton()
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.on_cancel)
        controls.addWidget(self.cancel_button)
        self.export_button = QPushButton()
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.on_export)
        controls.addWidget(self.export_button)
        outer.addLayout(controls)

        # ---- 进度 ----
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        self.status_label = QLabel()
        self.status_label.setProperty("textRole", "caption")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        # ---- 日志 ----
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(160)
        outer.addWidget(self.log_view, 1)

        self._refresh_device_combo()

    def _refresh_env_label(self):
        """检测 TensorFlow 是否可用；按钮可能尚未创建，做防御性判断。"""
        try:
            import tensorflow  # noqa: F401
            available = True
        except Exception:  # noqa: BLE001
            available = False
        self._tensorflow_available = available
        if hasattr(self, "env_label"):
            self.env_label.setText(
                self.tr.text("tr_env_ok") if available
                else self.tr.text("tr_need_tensorflow"))
        if hasattr(self, "start_button"):
            self.start_button.setEnabled(available and self._last_state == "idle")

    def _refresh_device_combo(self):
        if not hasattr(self, "device_combo"):
            return
        current = self.device_combo.currentData()
        self.device_combo.clear()
        self.device_combo.addItem(self.tr.text("tr_device_cpu"), "cpu")
        # 只在真的检测到 GPU 时才提供 GPU 选项，绝不假装有加速
        try:
            import tensorflow as tf
            if tf.config.list_physical_devices("GPU"):
                self.device_combo.addItem(self.tr.text("tr_device_gpu"), "gpu")
        except Exception:  # noqa: BLE001
            pass
        if current is not None:
            index = self.device_combo.findData(current)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)

    def _apply_language(self):
        t = self.tr.text
        self.epochs_label.setText("Epochs")
        self.batch_label.setText("Batch")
        self.size_label.setText("Input")
        self.device_label.setText("Device")
        self.start_button.setText(t("tr_start"))
        self.cancel_button.setText(t("tr_cancel"))
        self.export_button.setText(t("tr_export"))
        self._refresh_env_label()
        self._refresh_device_combo()
        if self._last_state == "running":
            self.status_label.setText(t("tr_running"))

    # =====================================================================
    # 训练
    # =====================================================================

    def _require_dataset(self) -> bool:
        if self.dataset_panel is None or not self.dataset_panel.dataset_root():
            QMessageBox.information(self, self.tr.text("tr_title"),
                                    self.tr.text("tr_no_dataset"))
            return False
        return True

    def on_start(self):
        if not self._require_dataset():
            return
        if not self._check_split():
            return
        try:
            from pvl_train import Trainer, TrainConfig
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self.tr.text("tr_title"),
                                 self.tr.text("tr_need_tensorflow") + f"\n\n{e}")
            return

        root = self.dataset_panel.dataset_root()
        dataset = self.dataset_panel.store.dataset
        size = int(self.size_combo.currentData())
        # MobileNetV3 includes its own rescaling layer and expects RGB 0..255.
        spec = PreprocessSpec(input_size=size, normalization="raw")
        config = TrainConfig(
            dataset_root=root,
            input_size=size,
            epochs=self.epochs_spin.value(),
            batch_size=self.batch_spin.value(),
            device=str(self.device_combo.currentData()),
            class_names=dataset.class_names(),
            display_names=dataset.display_names(),
            preprocess=spec.to_dict(),
        )
        from uuid import uuid4
        from pvl_dataset import DatasetStore
        run_name = f"run-{DatasetStore.sanitize_name(dataset.name)}-{self._stamp()}-{uuid4().hex[:8]}"
        output_dir = os.path.join(runs_dir(), run_name)
        try:
            os.makedirs(output_dir, exist_ok=False)
            split_snapshot = os.path.join(output_dir, "split.json")
            shutil.copyfile(self._split_path(), split_snapshot)
        except OSError as e:
            QMessageBox.critical(self, self.tr.text("tr_title"), str(e))
            return
        self._current_output_dir = output_dir
        self._current_config = config
        self._current_spec = spec
        self._run_split_path = split_snapshot

        self.trainer = Trainer(config, split_snapshot, output_dir)
        self._log_lines = []
        self.log_view.clear()
        self.progress.setValue(0)
        self._set_running(True)
        self.trainer.start()
        self._poll_timer.start(300)

    def _check_split(self) -> bool:
        root = self.dataset_panel.dataset_root()
        split_path = os.path.join(root, "split.json")
        if not os.path.isfile(split_path):
            QMessageBox.information(self, self.tr.text("tr_title"),
                                    self.tr.text("tr_no_split"))
            return False
        return True

    def _split_path(self) -> str:
        return os.path.join(self.dataset_panel.dataset_root(), "split.json")

    @staticmethod
    def _stamp() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def on_cancel(self):
        if self.trainer is not None:
            self.trainer.cancel()
            self.status_label.setText(self.tr.text("tr_cancelled"))

    def _set_running(self, running: bool):
        self.start_button.setEnabled(not running and self._tensorflow_available)
        self.cancel_button.setEnabled(running)
        self.export_button.setEnabled(False)
        self._last_state = "running" if running else "idle"
        if running:
            self.status_label.setText(self.tr.text("tr_running"))
            self.training_state_changed.emit("running")

    def _poll_progress(self):
        trainer = self.trainer
        if trainer is None:
            self._poll_timer.stop()
            return
        progress = trainer.progress
        total = max(1, progress.total_steps)
        self.progress.setValue(min(100, int(progress.step * 100 / total)))

        parts = [self.tr.text("tr_epoch", epoch=progress.epoch,
                              total=progress.total_epochs)]
        if progress.step:
            parts.append(self.tr.text("tr_step", step=progress.step,
                                      total=progress.total_steps))
        if progress.loss:
            parts.append(self.tr.text("tr_loss", loss=f"{progress.loss:.3f}"))
        if progress.accuracy:
            parts.append(self.tr.text("tr_acc", acc=f"{progress.accuracy:.3f}"))
        if progress.val_accuracy:
            parts.append(self.tr.text("tr_val", acc=f"{progress.val_accuracy:.3f}"))
        parts.append(self.tr.text("tr_best", acc=f"{progress.best_val_accuracy:.3f}"))
        self.status_label.setText("  ".join(parts))

        text = trainer.log_text()
        if text and text != self._log_view_text:
            self._log_view_text = text
            self.log_view.setPlainText(text)
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.End)
            self.log_view.setTextCursor(cursor)

        if progress.state in ("done", "cancelled", "error"):
            self._poll_timer.stop()
            self._set_running(False)
            self.trainer.join(timeout=2.0)
            if progress.state == "done":
                self.export_button.setEnabled(True)
                self.status_label.setText(
                    self.tr.text("tr_done") + " — " +
                    self.tr.text("tr_best", acc=f"{progress.best_val_accuracy:.4f}"))
            elif progress.state == "cancelled":
                self.status_label.setText(self.tr.text("tr_cancelled"))
            else:
                self.status_label.setText(
                    self.tr.text("tr_failed", error=progress.message))
                QMessageBox.critical(self, self.tr.text("tr_title"),
                                     self.tr.text("tr_failed", error=progress.message))
            self.training_state_changed.emit(progress.state)

    _log_view_text = ""

    # =====================================================================
    # 导出
    # =====================================================================

    def on_export(self):
        if self.export_in_progress():
            return
        config = getattr(self, "_current_config", None)
        if config is None:
            QMessageBox.information(self, self.tr.text("tr_title"),
                                    self.tr.text("tr_no_split"))
            return
        output_dir = self._current_output_dir
        keras_path = os.path.join(output_dir, "best.keras")
        if not os.path.isfile(keras_path):
            QMessageBox.information(self, self.tr.text("tr_title"),
                                    self.tr.text("tr_export_no_model"))
            return
        try:
            from pvl_export import export_model
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self.tr.text("tr_title"),
                                 self.tr.text("tr_need_tensorflow") + f"\n\n{e}")
            return

        self.export_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self._last_state = "exporting"
        self.status_label.setText(self.tr.text("tr_exporting"))
        split_path = self._run_split_path
        spec = self._current_spec

        def run_export():
            try:
                result = export_model(keras_path, config, spec, output_dir, split_path,
                                      package_name=os.path.basename(output_dir))
                self._export_signals.completed.emit(result)
            except Exception as exc:  # noqa: BLE001
                from pvl_export import ExportResult
                self._export_signals.completed.emit(ExportResult(error=str(exc)))

        self._export_thread = threading.Thread(target=run_export, name="pvl-export", daemon=True)
        self._export_thread.start()

    def export_in_progress(self):
        return self._last_state == "exporting"

    def _on_export_finished(self, result):
        self._last_state = "idle"
        self.start_button.setEnabled(self._tensorflow_available)
        self.export_button.setEnabled(True)

        if not result.success:
            QMessageBox.critical(self, self.tr.text("tr_title"),
                                 self.tr.text("tr_export_failed", error=result.error))
            self.status_label.setText(
                self.tr.text("tr_export_failed", error=result.error))
            return

        c = result.consistency
        self.status_label.setText(
            self.tr.text("tr_export_done", path=result.package_path) + "\n" +
            self.tr.text("tr_consistency", error=f"{c['max_abs_error']:.6f}",
                         agreement=f"{c['top1_agreement']:.2%}"))
        QMessageBox.information(
            self, self.tr.text("tr_title"),
            self.tr.text("tr_export_done", path=result.package_path) + "\n\n" +
            self.tr.text("tr_consistency", error=f"{c['max_abs_error']:.6f}",
                         agreement=f"{c['top1_agreement']:.2%}"))
        self.package_created.emit(result.package_path)

    def closeEvent(self, event):
        """面板关闭：取消并回收训练线程，避免遗留后台任务。"""
        if self.trainer is not None and self.trainer.is_running():
            self.trainer.cancel()
            self.trainer.join(timeout=3.0)
        self._poll_timer.stop()
        super().closeEvent(event)
