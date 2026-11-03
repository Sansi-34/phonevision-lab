"""
PhoneVision Lab — 性能分析面板（PySide6）。

职责：按可重复流程（预热 -> 固定时长 -> 固定配置）采样性能指标，
显示平均值/P50/P95，并导出 CSV / 摘要 / JSON。

为什么这样设计：
  - 各阶段分开显示：采集帧率、接收帧率、显示帧率、推理帧率互不混算。
  - 推理帧率由手机实测上报（PC 侧只记录，不自己算）；
    PC 侧自己测的是接收/显示口径，界面上明确标注。
  - 所有时间间隔用单调时钟，绝不拿手机与电脑时间戳相减。
  - 功耗：PC 客户端不测量手机功耗，明确显示"不支持"，
    并说明"设备提供真实数据源时才显示，且不把电量百分比当成功率"。

初学者调试观察点：
  - 推理帧率为 0：手机端没上报（未开始推理或断连）。
  - P95 远大于平均值：有偶发卡顿，常见原因是 GUI 线程被阻塞或磁盘写入慢。
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSpinBox, QVBoxLayout,
)

from pvl_paths import exports_dir
from pvl_perf import PerfRecord, PerfSampler, export_csv, export_json, \
    export_summary, new_record


class PerfPanel(QFrame):
    """性能分析面板。"""

    # 测试状态变化信号：running(bool)
    measuring_changed = Signal(bool)

    def __init__(self, translator, model_provider=None, parent=None):
        super().__init__(parent)
        self.tr = translator
        # model_provider: 可调用对象，返回 dict(name=, input_size=, color_order=,
        #                  layout=, normalization=, num_classes=)
        self.model_provider = model_provider
        self.setObjectName("perfPanel")

        self.record: PerfRecord | None = None
        self.sampler: PerfSampler | None = None
        self._elapsed = QTimer(self)
        self._elapsed.setInterval(1000)
        self._elapsed.timeout.connect(self._tick)

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

        # ---- 测试流程参数 ----
        proc = QHBoxLayout()
        self.warmup_label = QLabel()
        proc.addWidget(self.warmup_label)
        self.warmup_spin = QSpinBox()
        self.warmup_spin.setRange(0, 60)
        self.warmup_spin.setValue(3)
        proc.addWidget(self.warmup_spin)
        self.duration_label = QLabel()
        proc.addWidget(self.duration_label)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 3600)
        self.duration_spin.setValue(60)
        proc.addWidget(self.duration_spin)
        self.start_button = QPushButton()
        self.start_button.clicked.connect(self.on_start)
        proc.addWidget(self.start_button)
        self.stop_button = QPushButton()
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.on_stop)
        proc.addWidget(self.stop_button)
        outer.addLayout(proc)

        self.proc_hint = QLabel()
        self.proc_hint.setProperty("textRole", "hint")
        self.proc_hint.setWordWrap(True)
        outer.addWidget(self.proc_hint)

        # ---- 指标网格 ----
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(8)
        self._value_labels = {}
        self._build_metrics()
        outer.addLayout(self.grid)

        self.power_note = QLabel()
        self.power_note.setProperty("textRole", "hint")
        self.power_note.setWordWrap(True)
        outer.addWidget(self.power_note)

        self.hw_note = QLabel()
        self.hw_note.setProperty("textRole", "hint")
        self.hw_note.setWordWrap(True)
        outer.addWidget(self.hw_note)

        # ---- 导出 ----
        export_row = QHBoxLayout()
        self.csv_button = QPushButton()
        self.csv_button.setEnabled(False)
        self.csv_button.clicked.connect(lambda: self._export("csv"))
        export_row.addWidget(self.csv_button)
        self.summary_button = QPushButton()
        self.summary_button.setEnabled(False)
        self.summary_button.clicked.connect(lambda: self._export("summary"))
        export_row.addWidget(self.summary_button)
        self.json_button = QPushButton()
        self.json_button.setEnabled(False)
        self.json_button.clicked.connect(lambda: self._export("json"))
        export_row.addWidget(self.json_button)
        export_row.addStretch(1)
        outer.addLayout(export_row)

        outer.addStretch(1)

    def _build_metrics(self):
        """(i18n key, 行)。分阶段组织，避免指标混在一起。"""
        self._metric_rows = [
            ("pf_capture_fps", "phone_capture_fps", "fps"),
            ("pf_receive_fps", "pc_receive_fps", "fps"),
            ("pf_display_fps", "pc_display_fps", "fps"),
            ("pf_infer_fps", "phone_inference_fps", "fps"),
            ("pf_completed", "inference_completed", ""),
            ("pf_dropped", "dropped_frames", ""),
            ("pf_preprocess", "preprocess", "stage"),
            ("pf_model", "model", "stage"),
            ("pf_postprocess", "postprocess", "stage"),
            ("pf_hw_latency", "command_ack", "stage"),
        ]
        for row, (_key, field_name, kind) in enumerate(self._metric_rows):
            label = QLabel()
            label.setProperty("textRole", "metricLabel")
            self.grid.addWidget(label, row, 0)
            value = QLabel("--")
            value.setProperty("valueRole", "value")
            self.grid.addWidget(value, row, 1)
            self._value_labels[field_name] = value
            if kind == "stage":
                hint = QLabel("mean / P50 / P95")
                hint.setProperty("textRole", "hint")
                self.grid.addWidget(hint, row, 2)
                setattr(self, f"_hint_{field_name}", hint)

    def _apply_language(self):
        t = self.tr.text
        self.warmup_label.setText(t("pf_warmup"))
        self.duration_label.setText(t("pf_duration"))
        self.start_button.setText(t("pf_start"))
        self.stop_button.setText(t("pf_stop"))
        self.proc_hint.setText(t("pf_procedure_note"))
        self.power_note.setText(t("pf_power_note"))
        self.hw_note.setText(t("pf_hw_note"))
        self.csv_button.setText(t("pf_export_csv"))
        self.summary_button.setText(t("pf_export_summary"))
        self.json_button.setText(t("pf_export_json"))
        for row, (key, _field, kind) in enumerate(self._metric_rows):
            lab = self.grid.itemAtPosition(row, 0).widget()
            lab.setText(t(key))

    # =====================================================================
    # 测试流程
    # =====================================================================

    def _new_record(self) -> PerfRecord:
        info = {}
        if self.model_provider is not None:
            try:
                info = self.model_provider() or {}
            except Exception:  # noqa: BLE001
                info = {}
        record = new_record(
            model_name=info.get("name", ""),
            input_size=int(info.get("input_size", 0) or 0),
            color_order=info.get("color_order", ""),
            layout=info.get("layout", ""),
            normalization=info.get("normalization", ""),
            num_classes=int(info.get("num_classes", 0) or 0),
            client_version="pc-client")
        record.notes = "当前仅采集手机推流与电脑接收、显示帧率；手机推理、硬件和功耗尚未接入。"
        return record

    def on_start(self):
        self.record = self._new_record()
        self.sampler = PerfSampler(self.record)
        self.sampler.begin(warmup_seconds=float(self.warmup_spin.value()))
        self._duration = float(self.duration_spin.value())
        self._sample_at = time.monotonic() + self.warmup_spin.value()
        self._end_at = self._sample_at + self._duration
        self._latest_transport = None
        self._last_dropped = None
        self._transport_sums = [0.0, 0.0, 0.0]
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.csv_button.setEnabled(False)
        self.summary_button.setEnabled(False)
        self.json_button.setEnabled(False)
        self.measuring_changed.emit(True)
        self._elapsed.start()
        self._refresh_values()

    def on_stop(self):
        if self.sampler is not None:
            elapsed = max(0.0, min(self._duration, time.monotonic() - self._sample_at))
            self.sampler.end(duration_seconds=elapsed)
        self._elapsed.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.csv_button.setEnabled(True)
        self.summary_button.setEnabled(True)
        self.json_button.setEnabled(True)
        self.measuring_changed.emit(False)
        self._refresh_values()

    def _tick(self):
        now = time.monotonic()
        if self._sample_at <= now <= self._end_at and self._latest_transport is not None:
            self.record.transport_sample_count += 1
            count = self.record.transport_sample_count
            for index, value in enumerate(self._latest_transport):
                self._transport_sums[index] += value
            (self.record.phone_capture_fps, self.record.pc_receive_fps,
             self.record.pc_display_fps) = [total / count for total in self._transport_sums]
            self.record.transport_available = True
        self._refresh_values()
        if now >= self._end_at:
            self.on_stop()

    def _can_sample(self):
        return (self.record is not None and self._elapsed.isActive()
                and self._sample_at <= time.monotonic() <= self._end_at)

    # =====================================================================
    # 数据接入（由主窗口定时调用）
    # =====================================================================

    def update_transport(self, phone_capture_fps: float, pc_receive_fps: float,
                         pc_display_fps: float, dropped: int) -> None:
        if not self._can_sample():
            return
        self._latest_transport = (phone_capture_fps, pc_receive_fps, pc_display_fps)
        if self._last_dropped is not None:
            self.record.dropped_frames += max(0, dropped - self._last_dropped)
        self._last_dropped = dropped

    def clear_transport(self):
        self._latest_transport = None
        self._last_dropped = None

    def update_inference(self, fps: float, completed: int, skipped: int,
                         pre_ms: float | None = None,
                         model_ms: float | None = None,
                         post_ms: float | None = None) -> None:
        if not self._can_sample():
            return
        self.record.inference_available = True
        self.record.phone_inference_fps = fps
        self.record.inference_completed = completed
        self.record.inference_skipped = skipped
        if pre_ms is not None and model_ms is not None and post_ms is not None:
            # 单帧样本：由调用方决定何时计入（避免把同一帧重复计）
            self.sampler.add_inference(pre_ms, model_ms, post_ms)

    def add_command(self, status: str, rtt_ms: float | None = None) -> None:
        if not self._can_sample():
            return
        self.sampler.add_command(status, rtt_ms)

    def _refresh_values(self):
        record = self.record
        if record is None:
            return
        for name in ("phone_capture_fps", "pc_receive_fps", "pc_display_fps"):
            self._value_labels[name].setText(
                f"{getattr(record, name):.2f}" if record.transport_available else "--")
        self._value_labels["phone_inference_fps"].setText(
            f"{record.phone_inference_fps:.2f}" if record.inference_available else "--")
        self._value_labels["inference_completed"].setText(
            str(record.inference_completed) if record.inference_available else "--")
        self._value_labels["dropped_frames"].setText(
            str(record.dropped_frames) if record.transport_available else "--")
        self._set_stage("preprocess", record.preprocess)
        self._set_stage("model", record.model)
        self._set_stage("postprocess", record.postprocess)
        self._set_stage("command_ack", record.command_rtt_ms)

    def _set_stage(self, field_name: str, stats) -> None:
        if stats.count == 0:
            self._value_labels[field_name].setText("--")
            hint = getattr(self, f"_hint_{field_name}", None)
            if hint is not None:
                hint.setText("mean / P50 / P95")
            return
        self._value_labels[field_name].setText(
            f"{stats.mean:.2f} / {stats.p50:.2f} / {stats.p95:.2f}")
        hint = getattr(self, f"_hint_{field_name}", None)
        if hint is not None:
            hint.setText(f"n={stats.count}  max={stats.max:.2f} ms")

    # =====================================================================
    # 导出
    # =====================================================================

    def _export(self, kind: str):
        if self.record is None:
            return
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        directory = exports_dir()
        try:
            if kind == "csv":
                path = export_csv(self.record,
                                  os.path.join(directory, f"perf-{stamp}.csv"))
            elif kind == "summary":
                path = export_summary(
                    self.record, os.path.join(directory, f"perf-{stamp}.txt"))
            else:
                path = export_json(self.record,
                                   os.path.join(directory, f"perf-{stamp}.json"))
        except OSError as e:
            QMessageBox.critical(self, self.tr.text("pf_title"),
                                 self.tr.text("toast_save_failed", error=str(e)))
            return
        QMessageBox.information(self, self.tr.text("pf_title"),
                                self.tr.text("pf_exported", path=path))
