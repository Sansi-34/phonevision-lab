"""
PhoneVision Lab — 数据集工作台（PySide6 面板）。

职责：在现有 PySide6 工作台里增加"数据集"页：创建/打开数据集、管理类别、
浏览样本、启动采集、查看划分与训练入口。

为什么这样设计：
  - 复用现有 qt_client 组件风格（QSS + 双语 + Translator），不重写客户端。
  - 本面板只负责"数据"这一环；训练、导出、硬件、性能各自独立面板，
    通过 pvl_* 模块（无 GUI 依赖）通信，便于单测。
  - 采集通过"帧提供者"注入：预览模式下帧来自手机 MJPEG 流，
    测试时可以注入合成帧，不需要真机。

初学者调试观察点：
  - 采集不到图：看 frame_provider 是否返回了帧（None 表示当前无画面）。
  - 保存失败：面板会显示真实错误原因（目录不可写/磁盘满等）。
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from pvl_dataset import DatasetStore, list_datasets, normalize_class_name
from pvl_paths import datasets_dir
from pvl_split import check_dataset, save_split, split_dataset


class DatasetPanel(QFrame):
    """数据集工作台面板（嵌入主窗口的右侧检查器或独立标签页）。"""

    # 采集状态变化信号：(是否正在采集, 已采集张数)
    capture_state_changed = Signal(bool, int)

    # 数据集变化信号（训练/导出面板据此刷新）
    dataset_changed = Signal(str)

    def __init__(self, translator, frame_provider=None, parent=None):
        super().__init__(parent)
        self.tr = translator
        # frame_provider: 可调用对象，返回 (BGR ndarray 或 None, 帧号或 None)
        self.frame_provider = frame_provider
        self.setObjectName("datasetPanel")

        self.store: DatasetStore | None = None
        self.current_batch = None
        self.captured_count = 0
        self._last_saved_frame_num = None
        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self._on_capture_tick)

        self._build_ui()
        self._apply_language()
        self.tr.language_changed.connect(self._apply_language)

    # =====================================================================
    # 界面
    # =====================================================================

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        # ---- 数据集选择/创建 ----
        self.dataset_row = QHBoxLayout()
        self.dataset_combo = QComboBox()
        self.dataset_combo.setMinimumWidth(180)
        self.dataset_row.addWidget(self.dataset_combo, 1)
        self.open_button = QPushButton()
        self.open_button.clicked.connect(self.on_open_dataset)
        self.dataset_row.addWidget(self.open_button)
        self.new_button = QPushButton()
        self.new_button.clicked.connect(self.on_create_dataset)
        self.dataset_row.addWidget(self.new_button)
        outer.addLayout(self.dataset_row)

        self.path_label = QLabel()
        self.path_label.setProperty("textRole", "caption")
        self.path_label.setWordWrap(True)
        outer.addWidget(self.path_label)

        # ---- 类别管理 ----
        self.class_header = QLabel()
        self.class_header.setProperty("textRole", "groupTitle")
        outer.addWidget(self.class_header)

        self.class_list = QListWidget()
        self.class_list.setMaximumHeight(120)
        outer.addWidget(self.class_list)

        class_row = QHBoxLayout()
        self.class_input = QLineEdit()
        self.class_input.setPlaceholderText("例如 apple / pen / empty")
        class_row.addWidget(self.class_input, 1)
        self.add_class_button = QPushButton()
        self.add_class_button.clicked.connect(self.on_add_class)
        class_row.addWidget(self.add_class_button)
        self.rename_class_button = QPushButton()
        self.rename_class_button.clicked.connect(self.on_rename_class)
        class_row.addWidget(self.rename_class_button)
        outer.addLayout(class_row)

        # ---- 采集 ----
        self.capture_header = QLabel()
        self.capture_header.setProperty("textRole", "groupTitle")
        outer.addWidget(self.capture_header)

        cap_row = QHBoxLayout()
        self.capture_class_combo = QComboBox()
        self.capture_class_combo.setMinimumWidth(120)
        cap_row.addWidget(self.capture_class_combo, 1)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(100, 10000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setValue(500)
        cap_row.addWidget(self.interval_spin)
        self.interval_unit = QLabel("ms")
        cap_row.addWidget(self.interval_unit)
        outer.addLayout(cap_row)

        cap_btn_row = QHBoxLayout()
        self.single_capture_button = QPushButton()
        self.single_capture_button.clicked.connect(self.on_single_capture)
        cap_btn_row.addWidget(self.single_capture_button)
        self.start_capture_button = QPushButton()
        self.start_capture_button.clicked.connect(self.on_start_capture)
        cap_btn_row.addWidget(self.start_capture_button)
        self.stop_capture_button = QPushButton()
        self.stop_capture_button.clicked.connect(self.on_stop_capture)
        cap_btn_row.addWidget(self.stop_capture_button)
        outer.addLayout(cap_btn_row)

        self.capture_status = QLabel()
        self.capture_status.setProperty("textRole", "caption")
        outer.addWidget(self.capture_status)

        # ---- 统计与划分 ----
        self.stats_label = QLabel()
        self.stats_label.setProperty("textRole", "caption")
        self.stats_label.setWordWrap(True)
        outer.addWidget(self.stats_label)

        split_row = QHBoxLayout()
        self.val_ratio_spin = QSpinBox()
        self.val_ratio_spin.setRange(5, 50)
        self.val_ratio_spin.setValue(20)
        self.val_ratio_spin.setSuffix(" %")
        split_row.addWidget(self.val_ratio_spin)
        self.split_button = QPushButton()
        self.split_button.clicked.connect(self.on_make_split)
        split_row.addWidget(self.split_button)
        self.check_button = QPushButton()
        self.check_button.clicked.connect(self.on_check_dataset)
        split_row.addWidget(self.check_button)
        outer.addLayout(split_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        outer.addStretch(1)
        self._refresh_dataset_list()

    # =====================================================================
    # 语言
    # =====================================================================

    def _apply_language(self):
        t = self.tr.text
        self.open_button.setText(t("ds_open"))
        self.new_button.setText(t("ds_create"))
        self.class_header.setText(t("ds_classes"))
        self.add_class_button.setText(t("ds_add_class"))
        self.rename_class_button.setText(t("ds_rename"))
        self.capture_header.setText(t("ds_capture"))
        self.single_capture_button.setText(t("ds_capture_one"))
        self.start_capture_button.setText(t("ds_capture_start"))
        self.stop_capture_button.setText(t("ds_capture_stop"))
        self.split_button.setText(t("ds_split"))
        self.check_button.setText(t("ds_check"))
        self.class_input.setPlaceholderText(t("ds_class_placeholder"))
        self._refresh_status()

    # =====================================================================
    # 数据集操作
    # =====================================================================

    def _refresh_dataset_list(self):
        self.dataset_combo.clear()
        for info in list_datasets():
            self.dataset_combo.addItem(info["name"], info["root"])
        if self.dataset_combo.count() == 0:
            self.dataset_combo.addItem(self.tr.text("ds_none"), "")

    def current_root(self) -> str:
        return self.dataset_combo.currentData() or ""

    def on_open_dataset(self):
        root = self.current_root()
        if not root:
            QMessageBox.information(self, self.tr.text("ds_title"),
                                    self.tr.text("ds_none"))
            return
        self._open(root)

    def _open(self, root: str):
        if self._capture_timer.isActive():
            self.on_stop_capture()
        try:
            self.store = DatasetStore(root).open(root)
        except Exception as e:  # noqa: BLE001 - 打开失败要能看到原因
            QMessageBox.critical(self, self.tr.text("ds_title"),
                                 self.tr.text("ds_open_failed", error=str(e)))
            return
        self.path_label.setText(root)
        self._last_saved_frame_num = None
        self._refresh_classes()
        self.dataset_changed.emit(root)

    def on_create_dataset(self):
        name, ok = self._ask_text(self.tr.text("ds_create_title"),
                                  self.tr.text("ds_create_prompt"))
        if not ok or not name.strip():
            return
        if self._capture_timer.isActive():
            self.on_stop_capture()
        try:
            safe_name = DatasetStore.sanitize_name(name.strip())
            store = DatasetStore(os.path.join(datasets_dir(), safe_name))
            dataset = store.create(name.strip())
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self.tr.text("ds_title"),
                                 self.tr.text("ds_create_failed", error=str(e)))
            return
        self.store = store
        self._last_saved_frame_num = None
        self.path_label.setText(dataset.root)
        self._refresh_dataset_list()
        # 选中刚创建的数据集
        index = self.dataset_combo.findData(dataset.root)
        if index >= 0:
            self.dataset_combo.setCurrentIndex(index)
        self._refresh_classes()
        self.dataset_changed.emit(dataset.root)

    def _ask_text(self, title: str, prompt: str) -> tuple:
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getText(self, title, prompt)

    def _refresh_classes(self):
        selected = self.capture_class_combo.currentData()
        self.class_list.clear()
        self.capture_class_combo.clear()
        if self.store is None or self.store.dataset is None:
            return
        dataset = self.store.dataset
        for info in dataset.classes:
            count = dataset.count_images(info.name)
            item = QListWidgetItem(f"{info.display_name}  ({count})")
            item.setData(Qt.UserRole, info.name)
            self.class_list.addItem(item)
            self.capture_class_combo.addItem(info.display_name, info.name)
        index = self.capture_class_combo.findData(selected)
        if index >= 0:
            self.capture_class_combo.setCurrentIndex(index)
        self._refresh_status()

    def on_add_class(self):
        if self.store is None:
            QMessageBox.information(self, self.tr.text("ds_title"),
                                    self.tr.text("ds_open_first"))
            return
        raw = self.class_input.text().strip()
        if not raw:
            return
        try:
            info = self.store.dataset.add_class(raw)
            self.store.save()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self.tr.text("ds_title"),
                                 self.tr.text("ds_add_failed", error=str(e)))
            return
        self.class_input.clear()
        self._refresh_classes()

    def on_rename_class(self):
        if self.store is None:
            return
        item = self.class_list.currentItem()
        if item is None:
            return
        old_name = item.data(Qt.UserRole)
        new_display, ok = self._ask_text(
            self.tr.text("ds_rename_title"),
            self.tr.text("ds_rename_prompt"))
        if not ok or not new_display.strip():
            return
        try:
            self.store.dataset.rename_class(old_name, new_display.strip())
            self.store.save()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self.tr.text("ds_title"),
                                 self.tr.text("ds_rename_failed", error=str(e)))
            return
        self._refresh_classes()

    # =====================================================================
    # 采集
    # =====================================================================

    def on_single_capture(self):
        if self.current_batch is not None:
            self._capture_one()
            return
        if self.store is None:
            QMessageBox.information(self, self.tr.text("ds_title"),
                                    self.tr.text("ds_open_first"))
            return
        class_name = self.capture_class_combo.currentData()
        if not class_name:
            QMessageBox.information(self, self.tr.text("ds_title"),
                                    self.tr.text("ds_no_class"))
            return
        frame_info = self._fresh_frame()
        if frame_info is None:
            return
        try:
            self.current_batch = self.store.start_batch(class_name)
            self.captured_count = 0
            self._capture_one(frame_info)
        except Exception as e:  # noqa: BLE001
            self.capture_status.setText(self.tr.text("ds_save_failed", error=str(e)))
        finally:
            if self.current_batch is not None:
                self.on_stop_capture()

    def on_start_capture(self):
        if self._capture_timer.isActive():
            return
        if self.store is None:
            QMessageBox.information(self, self.tr.text("ds_title"),
                                    self.tr.text("ds_open_first"))
            return
        class_name = self.capture_class_combo.currentData()
        if not class_name:
            QMessageBox.information(self, self.tr.text("ds_title"),
                                    self.tr.text("ds_no_class"))
            return
        try:
            self.current_batch = self.store.start_batch(class_name)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self.tr.text("ds_title"),
                                 self.tr.text("ds_batch_failed", error=str(e)))
            return
        self.captured_count = 0
        self._capture_timer.start(self.interval_spin.value())
        self.capture_class_combo.setEnabled(False)
        self.start_capture_button.setEnabled(False)
        self.capture_state_changed.emit(True, 0)
        self._refresh_status()

    def on_stop_capture(self):
        self._capture_timer.stop()
        if self.store is not None and self.current_batch is not None:
            try:
                self.store.end_batch(self.current_batch.class_name,
                                     self.current_batch.batch_id)
            except Exception:  # noqa: BLE001 - 结束批次失败不影响已保存的图
                pass
        self.current_batch = None
        self.capture_class_combo.setEnabled(True)
        self.start_capture_button.setEnabled(True)
        self.capture_state_changed.emit(False, self.captured_count)
        self._refresh_classes()
        self.capture_status.setText(self.tr.text("ds_capture_stopped", count=self.captured_count))

    def _on_capture_tick(self):
        self._capture_one()

    def _fresh_frame(self):
        if self.frame_provider is None:
            frame, number = None, None
        else:
            frame, number = self.frame_provider()
        if frame is None or number is None:
            if self._capture_timer.isActive():
                self.on_stop_capture()
            self.capture_status.setText(self.tr.text("ds_no_frame"))
            return None
        if number == self._last_saved_frame_num:
            self.capture_status.setText(self.tr.text("ds_wait_new_frame"))
            return None
        return frame, number

    def _capture_one(self, frame_info=None):
        if self.store is None or self.current_batch is None:
            return
        frame_info = frame_info if frame_info is not None else self._fresh_frame()
        if frame_info is None:
            return
        frame, frame_num = frame_info
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if not ok:
                raise ValueError("JPEG 编码失败")
            self.store.save_frame(self.current_batch.class_name,
                                  self.current_batch.batch_id,
                                  buf.tobytes())
        except Exception as e:  # noqa: BLE001
            self.capture_status.setText(
                self.tr.text("ds_save_failed", error=str(e)))
            return
        self._last_saved_frame_num = frame_num
        self.captured_count += 1
        self.capture_state_changed.emit(self._capture_timer.isActive(), self.captured_count)
        self._refresh_status()

    # =====================================================================
    # 统计 / 划分 / 体检
    # =====================================================================

    def _refresh_status(self):
        if self.store is None or self.store.dataset is None:
            self.stats_label.setText(self.tr.text("ds_no_dataset"))
            self.capture_status.setText("")
            return
        dataset = self.store.dataset
        counts = dataset.class_counts()
        total = sum(counts.values())
        parts = [f"{name}: {counts.get(name, 0)}" for name in dataset.class_names()]
        self.stats_label.setText(
            self.tr.text("ds_stats", classes=", ".join(parts), total=total))
        if self.current_batch is not None:
            self.capture_status.setText(
                self.tr.text("ds_capturing", count=self.captured_count,
                             batch=self.current_batch.batch_id))
        elif not self.capture_status.text():
            self.capture_status.setText("")

    def on_check_dataset(self):
        if self.store is None or self.store.dataset is None:
            return
        problems, warnings = check_dataset(self.store.dataset)
        text = []
        if problems:
            text.append(self.tr.text("ds_check_problems"))
            text.extend(f"- {p}" for p in problems)
        if warnings:
            text.append(self.tr.text("ds_check_warnings"))
            text.extend(f"- {w}" for w in warnings)
        if not problems and not warnings:
            text.append(self.tr.text("ds_check_ok"))
        QMessageBox.information(self, self.tr.text("ds_title"),
                                "\n".join(text))

    def on_make_split(self):
        if self.store is None or self.store.dataset is None:
            QMessageBox.information(self, self.tr.text("ds_title"),
                                    self.tr.text("ds_open_first"))
            return
        ratio = self.val_ratio_spin.value() / 100.0
        try:
            result = split_dataset(self.store.dataset, val_ratio=ratio, seed=1234)
            split_path = os.path.join(self.store.root, "split.json")
            save_split(result, split_path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self.tr.text("ds_title"),
                                 self.tr.text("ds_split_failed", error=str(e)))
            return
        train_counts = result.class_counts("train")
        val_counts = result.class_counts("val")
        text = [
            self.tr.text("ds_split_done"),
            self.tr.text("ds_split_train", count=len(result.train),
                         detail=self._format_counts(train_counts)),
            self.tr.text("ds_split_val", count=len(result.val),
                         detail=self._format_counts(val_counts)),
        ]
        if result.warnings:
            text.append(self.tr.text("ds_check_warnings"))
            text.extend(f"- {w}" for w in result.warnings)
        if result.problems:
            text.append(self.tr.text("ds_check_problems"))
            text.extend(f"- {p}" for p in result.problems)
        text.append(self.tr.text("ds_split_path", path=split_path))
        self.last_split_path = split_path
        QMessageBox.information(self, self.tr.text("ds_title"), "\n".join(text))

    @staticmethod
    def _format_counts(counts: dict) -> str:
        return ", ".join(f"{k}={v}" for k, v in counts.items()) or "-"

    # =====================================================================
    # 对外
    # =====================================================================

    def dataset_root(self) -> str:
        return self.store.root if self.store else ""

    def is_capturing(self) -> bool:
        return self._capture_timer.isActive()

    def closeEvent(self, event):
        """面板关闭时停止采集定时器，避免遗留后台任务。"""
        if self._capture_timer.isActive():
            self.on_stop_capture()
        super().closeEvent(event)
