"""
PhoneVision Lab Web — 性能采样服务（只记录真实数据，未接入项标"未采集"）。

职责：按"预热 → 固定时长 → 固定配置"流程采样传输指标，用 pvl_perf 汇总并
导出 CSV / 摘要 / JSON。

为什么这样设计：
  - 复用 pvl_perf.PerfRecord / PerfSampler / export_*：分位数、口径、导出格式
    与桌面客户端完全一致，网页不另造一套统计。
  - 采样值来自 DeviceSession.transport_metrics()，即手机 /ping 自报的采集帧率、
    PC 解析出的接收帧率、前端显示回调累加出的显示帧率。没有真实连接时全部为
    None，界面显示"—（未采集）"，绝不用 0 或示例值填充。
  - 手机推理帧率、推理各阶段耗时、硬件命令耗时、功耗在本服务中无数据来源，
    明确标为"未采集/暂不支持"（pvl_perf 的 power_source 默认就是 unsupported）。
"""
from __future__ import annotations

import os
import sys
import threading
import time

_PC_CLIENT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pc-client")
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

from .util import ApiError  # noqa: E402


class PerformanceService:
    """一次性能测试的生命周期。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._record = None
        self._sampler = None
        self._running = False
        self._warmup_seconds = 3.0
        self._duration = 60.0
        self._sample_at = 0.0
        self._end_at = 0.0
        self._latest_transport = None
        self._last_dropped = None
        self._sums = [0.0, 0.0, 0.0]
        self._count = 0
        self._early_stop = False

    # ------------------------------------------------------------------

    def start(self, warmup_seconds: float, duration_seconds: float,
              device_session) -> dict:
        if not device_session.is_connected:
            raise ApiError("not_connected",
                           "尚未连接手机：性能测试需要真实推流数据，请先连接设备")
        if warmup_seconds < 0 or duration_seconds <= 0:
            raise ApiError("bad_request", "预热时间不能为负，测试时长必须大于 0")

        from pvl_perf import new_record
        with self._lock:
            if self._running:
                raise ApiError("busy", "已有性能测试在进行中")
            self._record = new_record(client_version="phonevision-lab-web")
            self._record.notes = (
                "网页客户端采样：仅包含手机推流与电脑接收/显示口径；"
                "手机推理、硬件命令与功耗数据未接入。")
            self._sampler = None
            self._warmup_seconds = float(warmup_seconds)
            self._duration = float(duration_seconds)
            now = time.monotonic()
            self._sample_at = now + float(warmup_seconds)
            self._end_at = self._sample_at + float(duration_seconds)
            self._latest_transport = None
            self._last_dropped = None
            self._sums = [0.0, 0.0, 0.0]
            self._count = 0
            self._early_stop = False
            self._running = True
        return self.snapshot()

    def stop(self) -> dict:
        with self._lock:
            if not self._running:
                raise ApiError("bad_request", "当前没有进行中的性能测试")
            record = self._record
            if record is not None:
                elapsed = max(0.0, min(self._duration,
                                       time.monotonic() - self._sample_at))
                record.duration_seconds = elapsed
                record.warmup_seconds = self._warmup_seconds
                if self._early_stop:
                    record.notes += f"（提前结束：实际 {elapsed:.0f}s / 计划 {self._duration:.0f}s）"
            self._running = False
        return self.snapshot()

    def tick(self, device_session) -> None:
        """由后台线程周期调用：在采样窗口内累加真实指标。"""
        with self._lock:
            if not self._running or self._record is None:
                return
            now = time.monotonic()
            if not (self._sample_at <= now <= self._end_at):
                if now > self._end_at:
                    self._running = False
                return
            record = self._record

        try:
            metrics = device_session.transport_metrics()
        except Exception:  # noqa: BLE001 - 取指标失败本次跳过
            return
        phone_fps = metrics.get("phone_capture_fps")
        receive_fps = metrics.get("pc_receive_fps")
        display_fps = metrics.get("pc_display_fps")
        dropped = metrics.get("dropped_frames")

        if phone_fps is None and receive_fps is None:
            # 没有真实数据：不写入任何数值（保持"未采集"）
            return

        with self._lock:
            self._count += 1
            for index, value in enumerate((phone_fps or 0.0, receive_fps or 0.0,
                                           display_fps or 0.0)):
                self._sums[index] += float(value)
            record.phone_capture_fps = self._sums[0] / self._count
            record.pc_receive_fps = self._sums[1] / self._count
            record.pc_display_fps = self._sums[2] / self._count
            record.transport_available = True
            record.transport_sample_count = self._count
            if self._last_dropped is not None and dropped is not None:
                record.dropped_frames += max(0, dropped - self._last_dropped)
            if dropped is not None:
                self._last_dropped = dropped

    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            record = self._record
            running = self._running
            warmup, duration = self._warmup_seconds, self._duration
            sample_at, end_at = self._sample_at, self._end_at
        if record is None:
            return {
                "running": False,
                "has_record": False,
                "phase": "idle",
                "elapsed": 0.0,
                "warmup_seconds": warmup,
                "duration_seconds": duration,
                "metrics": None,
                "exports": [],
            }
        now = time.monotonic()
        if running:
            phase = ("warmup" if now < sample_at else "sampling")
            elapsed = max(0.0, now - sample_at)
        else:
            phase = "finished"
            elapsed = record.duration_seconds or 0.0
        return {
            "running": running,
            "has_record": True,
            "phase": phase,
            "elapsed": round(elapsed, 1),
            "total": round(duration, 1),
            "warmup_seconds": warmup,
            "duration_seconds": duration,
            "metrics": self._metric_view(record),
            "exports": [],
        }

    @staticmethod
    def _metric_view(record) -> dict:
        def stage(stats):
            if stats.count == 0:
                return None
            return {
                "mean": round(stats.mean, 3),
                "p50": round(stats.p50, 3),
                "p95": round(stats.p95, 3),
                "count": stats.count,
            }

        return {
            "capture_and_transport": {
                "phone_capture_fps": (round(record.phone_capture_fps, 2)
                                      if record.transport_available else None),
                "pc_receive_fps": (round(record.pc_receive_fps, 2)
                                   if record.transport_available else None),
                "pc_display_fps": (round(record.pc_display_fps, 2)
                                   if record.transport_available else None),
                "dropped_frames": (record.dropped_frames
                                   if record.transport_available else None),
                "sample_count": record.transport_sample_count,
            },
            "inference": {
                "phone_inference_fps": (round(record.phone_inference_fps, 2)
                                        if record.inference_available else None),
                "completed": (record.inference_completed
                              if record.inference_available else None),
                "skipped": (record.inference_skipped
                            if record.inference_available else None),
                "preprocess": stage(record.preprocess),
                "model": stage(record.model),
                "postprocess": stage(record.postprocess),
            },
            "hardware": {
                "commands_sent": (record.commands_sent
                                  if record.hardware_available else None),
                "commands_executed": (record.commands_executed
                                      if record.hardware_available else None),
                "command_ack": stage(record.command_rtt_ms),
            },
            "power": {
                "source": record.power_source,
                "value": record.power_value,
                "note": record.power_note,
            },
            "procedure": {
                "warmup_seconds": record.warmup_seconds,
                "duration_seconds": record.duration_seconds,
                "notes": record.notes,
            },
            "environment": record.to_dict().get("environment", {}),
        }

    # ------------------------------------------------------------------

    def export(self, kind: str) -> str:
        from pvl_perf import export_csv, export_json, export_summary
        from pvl_paths import exports_dir
        with self._lock:
            record = self._record
        if record is None:
            raise ApiError("bad_request", "还没有可导出的测试记录，请先运行一次性能测试")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        directory = exports_dir()
        path = os.path.join(directory, f"perf-web-{stamp}.{kind}")
        if kind == "csv":
            export_csv(record, path)
        elif kind == "txt":
            export_summary(record, path)
        elif kind == "json":
            export_json(record, path)
        else:
            raise ApiError("bad_request", f"未知导出格式: {kind}")
        return path

    def has_record(self) -> bool:
        with self._lock:
            return self._record is not None
