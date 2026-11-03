"""
PhoneVision Lab — 性能测量与报告（PC 侧统计与导出）。

职责：分别测量不同阶段的指标，聚合成可复现的测试记录，导出 CSV 与摘要。

为什么这样设计：
  - 阶段分离：采集帧率 / 接收帧率 / 显示帧率 / 推理帧率各自测量，
    绝不混用。手机实际完成的推理帧率只能由手机端实测（Android 侧
    InferenceEngine 上报），PC 侧记录的是"电脑看到的口径"。
  - 单调时钟：所有本机时间间隔用 time.monotonic()，绝不拿手机与电脑的
    未同步时间戳相减（相减得到的"端到端延迟"没有物理意义）。
  - 分位数：平均值 + P50 + P95，避免被个别抖动帧误导。
  - 功耗数据必须标注来源与性质：实测 / 估算 / 电量变化，
    不支持的指标显示"不支持"，绝不把电量百分比当成功率。
  - 测试流程可重复：预热 -> 固定时长 -> 固定配置 -> 可选固定样本 ->
    导出 CSV + 摘要。

初学者调试观察点：
  - P95 远大于平均值：有偶发卡顿，看是否 GUI 线程被阻塞或磁盘写入慢。
  - 推理帧率上不去：看 model_ms（单次模型执行耗时）是否接近 1/目标帧率。
"""
from __future__ import annotations

import csv
import os
import platform
import statistics
import time
from dataclasses import dataclass, field


def _percentile(values: list, pct: float) -> float:
    """计算分位数（线性插值）。空列表返回 0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * (pct / 100.0)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return float(ordered[low] * (1 - frac) + ordered[high] * frac)


@dataclass
class StageStats:
    """一个阶段的耗时统计（平均值 / P50 / P95）。"""

    samples: list = field(default_factory=list)

    def add(self, value_ms: float) -> None:
        if value_ms is None or value_ms < 0:
            return
        self.samples.append(float(value_ms))

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples) if self.samples else 0.0

    @property
    def p50(self) -> float:
        return _percentile(self.samples, 50)

    @property
    def p95(self) -> float:
        return _percentile(self.samples, 95)

    @property
    def max(self) -> float:
        return max(self.samples) if self.samples else 0.0

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "mean_ms": round(self.mean, 3) if self.count else None,
            "p50_ms": round(self.p50, 3) if self.count else None,
            "p95_ms": round(self.p95, 3) if self.count else None,
            "max_ms": round(self.max, 3) if self.count else None,
        }


@dataclass
class PerfRecord:
    """一次完整测试的记录（可序列化，可导出）。"""

    # ---- 测试环境 ----
    started_at: str = ""
    device_model: str = ""
    os_version: str = ""
    client_version: str = ""
    # ---- 被测对象 ----
    model_name: str = ""
    input_size: int = 0
    color_order: str = ""
    layout: str = ""
    normalization: str = ""
    num_classes: int = 0
    # ---- 采集与接收（PC 侧口径）----
    phone_capture_fps: float = 0.0
    pc_receive_fps: float = 0.0
    pc_display_fps: float = 0.0
    dropped_frames: int = 0
    transport_available: bool = False
    transport_sample_count: int = 0
    # ---- 推理（手机实测上报；PC 侧记录，不自己算）----
    phone_inference_fps: float = 0.0
    inference_completed: int = 0
    inference_skipped: int = 0
    inference_available: bool = False
    preprocess: StageStats = field(default_factory=StageStats)
    model: StageStats = field(default_factory=StageStats)
    postprocess: StageStats = field(default_factory=StageStats)
    # ---- 硬件联动 ----
    rule_latency_ms: StageStats = field(default_factory=StageStats)
    command_rtt_ms: StageStats = field(default_factory=StageStats)
    commands_sent: int = 0
    commands_received: int = 0
    commands_executed: int = 0
    commands_failed: int = 0
    commands_timeout: int = 0
    hardware_available: bool = False
    # ---- 功耗（明确区分来源与性质）----
    power_source: str = "unsupported"     # measured / estimated / battery_delta / unsupported
    power_value: str = ""                 # 人类可读值；不支持时为空
    power_charging: bool | None = None
    power_note: str = ""
    # ---- 测试流程 ----
    warmup_seconds: float = 0.0
    duration_seconds: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "environment": {
                "device_model": self.device_model,
                "os_version": self.os_version,
                "client_version": self.client_version,
            },
            "model": {
                "name": self.model_name,
                "input_size": self.input_size,
                "color_order": self.color_order,
                "layout": self.layout,
                "normalization": self.normalization,
                "num_classes": self.num_classes,
            },
            "capture_and_transport": {
                "phone_capture_fps": round(self.phone_capture_fps, 2) if self.transport_available else None,
                "pc_receive_fps": round(self.pc_receive_fps, 2) if self.transport_available else None,
                "pc_display_fps": round(self.pc_display_fps, 2) if self.transport_available else None,
                "dropped_frames": self.dropped_frames if self.transport_available else None,
                "sample_count": self.transport_sample_count,
            },
            "inference": {
                "phone_inference_fps": round(self.phone_inference_fps, 2) if self.inference_available else None,
                "completed_frames": self.inference_completed if self.inference_available else None,
                "skipped_frames": self.inference_skipped if self.inference_available else None,
                "preprocess": self.preprocess.to_dict(),
                "model": self.model.to_dict(),
                "postprocess": self.postprocess.to_dict(),
            },
            "hardware": {
                "rule_latency": self.rule_latency_ms.to_dict(),
                "command_ack_latency": self.command_rtt_ms.to_dict(),
                "commands_sent": self.commands_sent if self.hardware_available else None,
                "commands_received": self.commands_received if self.hardware_available else None,
                "commands_executed": self.commands_executed if self.hardware_available else None,
                "commands_failed": self.commands_failed if self.hardware_available else None,
                "commands_timeout": self.commands_timeout if self.hardware_available else None,
                "note": (
                    "command_ack_latency 是'命令发送到控制器确认'的耗时。"
                    "设备只确认接收时，它不等于真实机械动作完成耗时。"
                ),
            },
            "power": {
                "source": self.power_source,
                "value": self.power_value,
                "charging": self.power_charging,
                "note": self.power_note,
            },
            "procedure": {
                "warmup_seconds": self.warmup_seconds,
                "duration_seconds": self.duration_seconds,
                "notes": self.notes,
            },
        }

    def summary_text(self) -> str:
        """人类可读摘要（用于界面显示与报告）。"""
        def value(number, available, suffix=""):
            return f"{number:.2f}{suffix}" if available else "未采集"

        def stage(stats):
            return (f"{stats.mean:.2f}/{stats.p50:.2f}/{stats.p95:.2f} ms"
                    if stats.count else "未采集")

        charging = "未知" if self.power_charging is None else ("是" if self.power_charging else "否")
        lines = [
            "PhoneVision Lab 性能测试摘要",
            "=" * 40,
            f"时间: {self.started_at}",
            f"电脑: {self.device_model}  {self.os_version}",
            f"客户端: {self.client_version}",
            "",
            f"模型: {self.model_name}",
            f"  输入: {self.input_size}px {self.color_order} {self.layout} "
            f"{self.normalization}",
            f"  类别数: {self.num_classes}",
            "",
            "采集与传输（PC 侧口径）",
            f"  手机采集帧率: {value(self.phone_capture_fps, self.transport_available, ' fps')}",
            f"  PC 接收帧率:   {value(self.pc_receive_fps, self.transport_available, ' fps')}",
            f"  PC 显示帧率:   {value(self.pc_display_fps, self.transport_available, ' fps')}",
            f"  丢帧:          {self.dropped_frames if self.transport_available else '未采集'}",
            "",
            "推理（手机上报）" if self.inference_available else "推理（尚未接入手机上报）",
            f"  推理帧率:       {value(self.phone_inference_fps, self.inference_available, ' fps')}",
            f"  完成帧:         {self.inference_completed if self.inference_available else '未采集'}",
            f"  主动跳过帧:     {self.inference_skipped if self.inference_available else '未采集'}",
            f"  预处理 (mean/P50/P95): {stage(self.preprocess)}",
            f"  模型执行 (mean/P50/P95): {stage(self.model)}",
            f"  后处理 (mean/P50/P95): {stage(self.postprocess)}",
            "  单位说明: 均为本机单调时钟测得的时间间隔（毫秒）。",
            "",
            "硬件联动",
            f"  规则确认耗时: {self.rule_latency_ms.to_dict()}",
            f"  命令确认耗时: {self.command_rtt_ms.to_dict()}",
            "  发送/接收/执行/失败/超时: " +
            (f"{self.commands_sent}/{self.commands_received}/{self.commands_executed}/"
             f"{self.commands_failed}/{self.commands_timeout}" if self.hardware_available else "未采集"),
            "  说明: 命令确认耗时 = 发送到控制器确认；"
            "设备只确认接收时不等于机械动作完成耗时。",
            "",
            "功耗",
            f"  数据来源: {self.power_source}",
            f"  数值: {self.power_value or '不支持'}",
            f"  是否充电: {charging}",
            f"  说明: {self.power_note or '（无）'}",
            "",
            "测试流程",
            f"  预热: {self.warmup_seconds:.1f}s  正式: {self.duration_seconds:.1f}s",
            f"  备注: {self.notes or '（无）'}",
        ]
        return "\n".join(lines)


def new_record(model_name: str = "", input_size: int = 0,
               color_order: str = "", layout: str = "",
               normalization: str = "", num_classes: int = 0,
               client_version: str = "") -> PerfRecord:
    """创建一个带默认环境信息的记录。"""
    record = PerfRecord(
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        device_model=platform.node() or "unknown",
        os_version=f"{platform.system()} {platform.release()}",
        client_version=client_version,
        model_name=model_name,
        input_size=input_size,
        color_order=color_order,
        layout=layout,
        normalization=normalization,
        num_classes=num_classes,
    )
    # 功耗默认值：PC 侧不测手机功耗，明确标为不支持。
    record.power_source = "unsupported"
    record.power_value = ""
    record.power_note = (
        "PC 客户端不测量手机功耗。手机侧若提供电流/电压数据源，"
        "请在手机端记录后填入，并注明是实测还是估算。"
    )
    return record


def export_csv(record: PerfRecord, path: str) -> str:
    """把扁平化指标导出为 CSV（便于表格软件分析）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    d = record.to_dict()
    rows = []

    def _flatten(prefix, obj):
        for key, value in obj.items():
            if isinstance(value, dict):
                _flatten(f"{prefix}.{key}" if prefix else key, value)
            else:
                rows.append((f"{prefix}.{key}" if prefix else key, value))

    _flatten("", d)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["metric", "value"])
        writer.writerows(rows)
    return path


def export_summary(record: PerfRecord, path: str) -> str:
    """导出人类可读摘要（txt）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(record.summary_text())
        fh.write("\n")
    return path


def export_json(record: PerfRecord, path: str) -> str:
    """导出结构化 JSON（含分位数等全部字段）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json_dump(record.to_dict(), fh)
    return path


def json_dump(data, fh) -> None:
    import json
    json.dump(data, fh, ensure_ascii=False, indent=2)


class PerfSampler:
    """实时采样器：在测试期间按阶段累计样本，结束时写回 PerfRecord。

    使用方式：
        sampler = PerfSampler(record)
        sampler.begin()
        ... 推理循环里 sampler.add_inference(pre_ms, model_ms, post_ms) ...
        sampler.end(duration_seconds=60)
    """

    def __init__(self, record: PerfRecord):
        self.record = record
        self._start_monotonic = 0.0
        self._warmup_start = 0.0

    def begin(self, warmup_seconds: float = 3.0) -> None:
        self._warmup_start = time.monotonic()
        self.record.warmup_seconds = warmup_seconds

    def end(self, duration_seconds: float) -> None:
        self.record.duration_seconds = duration_seconds

    def add_inference(self, preprocess_ms: float, model_ms: float,
                      postprocess_ms: float) -> None:
        self.record.inference_available = True
        self.record.preprocess.add(preprocess_ms)
        self.record.model.add(model_ms)
        self.record.postprocess.add(postprocess_ms)
        self.record.inference_completed += 1

    def add_skipped(self, count: int = 1) -> None:
        self.record.inference_skipped += count

    def add_rule_latency(self, ms: float) -> None:
        self.record.rule_latency_ms.add(ms)

    def add_command(self, status: str, rtt_ms: float | None = None) -> None:
        self.record.hardware_available = True
        self.record.commands_sent += 1
        if status == "received":
            self.record.commands_received += 1
        elif status == "executed":
            self.record.commands_executed += 1
        elif status == "failed":
            self.record.commands_failed += 1
        if rtt_ms is not None:
            self.record.command_rtt_ms.add(rtt_ms)
