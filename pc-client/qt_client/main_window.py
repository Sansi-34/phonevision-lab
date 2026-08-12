"""
PhoneVision Lab — PySide6 主窗口（产品级客户端核心）。

职责：一个窗口内集成"视频画面 + 命令台 + 状态仪表盘"：
  - 顶部：视频画面区（QLabel 显示处理后的帧）
  - 左侧：命令台（5 个模式按钮 + 参数滑块 + 操作按钮）
  - 底部：指标仪表盘（状态 / 三个 FPS / 分辨率 / JPEG / 带宽 / 帧数）

为什么这样设计：
  - 用 PySide6 专业 GUI 框架 + QSS 样式表（style.qss），做出产品级质感。
  - 后台用 mjpeg_reader 线程收帧（只留最新帧），QTimer 在主线程轮询显示，
    互不阻塞，延迟不累积。
  - 视觉处理复用 vision_modes.apply_mode，本窗口只负责取帧、调参、显示。

初学者调试观察点：
  - 画面不动：看状态指示灯变琥珀（Reconnecting），说明流断了在等重连。
  - 滑块没效果：确认当前模式匹配（Canny 滑块只影响 Canny 模式）。
  - 处理慢：看"显示FPS"明显低于"接收FPS"。
"""
import logging
import os
import sys
import threading
import time
from datetime import datetime

import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

import requests

import app_model
import mjpeg_reader
import vision_modes

# 保存截图目录：qt_client 的上一级 captures/
CAPTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")

# 渲染类型常量：画面区当前显示内容的语义分类。
# 用于"类型或连接状态不变"时跳过重复创建占位 QPixmap（30/60Hz 刷新下省 CPU）。
RENDER_FRAME = "frame"
RENDER_CONNECTING = "connecting-placeholder"
RENDER_RECONNECTING = "reconnecting-placeholder"
RENDER_STOPPED = "stopped-placeholder"


class MainWindow(QMainWindow):
    """PhoneVision Lab 主窗口。"""

    def __init__(self, stream_url, ping_url, ping_info):
        super().__init__()
        self.stream_url = stream_url
        self.ping_url = ping_url
        self.ping_info = ping_info

        self.setWindowTitle("PhoneVision Lab")
        self.resize(1024, 700)
        self.setMinimumSize(960, 640)

        # ---- 状态 ----
        self.mode = vision_modes.MODE_ORIGINAL
        self.params = dict(vision_modes.DEFAULT_PARAMS)
        self.stats = {
            "state": "Idle",
            "phone_fps": float(ping_info.get("actualFps", 0) or 0),
            "recv_fps": 0.0,
            "disp_fps": 0.0,
            "width": int(ping_info.get("width") or 0),
            "height": int(ping_info.get("height") or 0),
            "avg_jpeg_mb": 0.0,
            "throughput_mbps": 0.0,
            "received": 0,
            "invalid": 0,
            "dropped": 0,
            "error": "",
        }
        self._last_frame_num = None
        self._qimg = None  # 保引用，防止 QImage 底层数据被回收
        # 画面区当前渲染类型与占位时的连接状态快照：
        # 类型/状态没变时跳过重建占位 QPixmap；收到新帧立即重置。
        self._render_type = None
        self._placeholder_state = None

        # ---- 共享客户端状态模型（网络 / 统计 / 生命周期唯一来源）----
        self.model = app_model.AppModel(
            stream_url=stream_url,
            ping_url=ping_url,
            device_name=str(ping_info.get("device", "")),
            width=int(ping_info.get("width") or 0),
            height=int(ping_info.get("height") or 0),
            phone_fps=float(ping_info.get("actualFps", 0) or 0),
        )
        self.model.start()
        # 兼容旧引用（部分方法仍用 self.reader）
        self.reader = self.model

        # ---- 构建界面 ----
        self._build_ui()

        # ---- 定时刷新 ----
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(33)  # ~30fps

    # =====================================================================
    # 界面构建
    # =====================================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # ---- 内容行：画面区(左) + 命令台(右) ----
        content = QHBoxLayout()
        content.setSpacing(12)
        outer.addLayout(content, 1)

        # 画面区
        video_card = QFrame()
        video_card.setObjectName("videoCard")
        video_card.setProperty("cardRole", "card")
        vbox = QVBoxLayout(video_card)
        vbox.setContentsMargins(8, 8, 8, 8)
        self.video_view = QLabel("等待连接手机推流...")
        self.video_view.setObjectName("videoView")
        self.video_view.setAlignment(Qt.AlignCenter)
        self.video_view.setMinimumSize(480, 320)
        vbox.addWidget(self.video_view, 1)
        content.addWidget(video_card, 1)

        # 命令台
        self._build_sidebar(content)

        # ---- 底部指标仪表盘 ----
        self._build_metrics_bar(outer)

    def _build_sidebar(self, content):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(264)
        box = QVBoxLayout(sidebar)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(10)
        content.addWidget(sidebar)

        # ---- 视觉模式卡片 ----
        mode_card = QFrame()
        mode_card.setProperty("cardRole", "card")
        mbox = QVBoxLayout(mode_card)
        mbox.setContentsMargins(16, 12, 16, 16)
        mbox.setSpacing(8)

        title = QLabel("视觉模式")
        title.setProperty("textRole", "groupTitle")
        mbox.addWidget(title)

        self._build_mode_buttons(mbox)

        self.mode_label = QLabel("当前: 原始")
        self.mode_label.setProperty("textRole", "caption")
        mbox.addWidget(self.mode_label)

        box.addWidget(mode_card)

        # ---- 参数调节卡片 ----
        param_card = QFrame()
        param_card.setProperty("cardRole", "card")
        pbox = QVBoxLayout(param_card)
        pbox.setContentsMargins(16, 12, 16, 16)
        pbox.setSpacing(4)

        ptitle = QLabel("参数调节")
        ptitle.setProperty("textRole", "groupTitle")
        pbox.addWidget(ptitle)
        hint = QLabel("按模式生效")
        hint.setProperty("textRole", "hint")
        pbox.addWidget(hint)

        self._build_sliders(pbox)

        box.addWidget(param_card, 1)

        # ---- 操作卡片 ----
        act_card = QFrame()
        act_card.setProperty("cardRole", "card")
        abox = QHBoxLayout(act_card)
        abox.setContentsMargins(16, 12, 16, 16)
        abox.setSpacing(8)

        save_btn = QPushButton("保存截图")
        save_btn.setProperty("buttonRole", "primary")
        save_btn.clicked.connect(self.save_capture)

        reconnect_btn = QPushButton("重新连接")
        reconnect_btn.setProperty("buttonRole", "ghost")
        reconnect_btn.clicked.connect(self.reconnect)

        quit_btn = QPushButton("退出")
        quit_btn.setProperty("buttonRole", "danger")
        quit_btn.clicked.connect(self.close)

        abox.addWidget(save_btn)
        abox.addWidget(reconnect_btn)
        abox.addWidget(quit_btn)
        box.addWidget(act_card)

    def _build_mode_buttons(self, parent):
        """5 个模式按钮，QButtonGroup 互斥，checkable 选中态由 QSS 处理。"""
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = {}

        mode_defs = [
            ("1", "原始", vision_modes.MODE_ORIGINAL),
            ("2", "灰度", vision_modes.MODE_GRAY),
            ("3", "Canny", vision_modes.MODE_CANNY),
            ("4", "HSV", vision_modes.MODE_HSV),
            ("5", "轮廓", vision_modes.MODE_CONTOUR),
        ]
        # 3 列网格
        grid = QVBoxLayout()
        grid.setSpacing(6)
        row = None
        for i, (key, label, mode) in enumerate(mode_defs):
            if i % 3 == 0:
                row = QHBoxLayout()
                row.setSpacing(6)
                grid.addLayout(row)
            btn = QPushButton(f"{key} {label}")
            btn.setProperty("buttonRole", "mode")
            btn.setCheckable(True)
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            self.mode_group.addButton(btn)
            self.mode_buttons[mode] = btn
            row.addWidget(btn, 1)
        parent.addLayout(grid)
        # 默认选中"原始"
        self.mode_buttons[vision_modes.MODE_ORIGINAL].setChecked(True)

    def _build_sliders(self, parent):
        """参数滑块：Canny 阈值、HSV 上下限、轮廓最小面积。"""
        self.sliders = {}
        self.slider_value_labels = {}

        def make_slider(label, key, maxv):
            row = QHBoxLayout()
            row.setSpacing(6)
            lab = QLabel(label)
            lab.setProperty("textRole", "caption")
            lab.setFixedWidth(64)
            row.addWidget(lab)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, maxv)
            slider.setValue(self.params[key])
            slider.valueChanged.connect(
                lambda v, k=key: self.on_slider(k, v))
            row.addWidget(slider, 1)

            vlab = QLabel(str(self.params[key]))
            vlab.setObjectName("sliderValue")
            vlab.setFixedWidth(36)
            vlab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(vlab)

            self.sliders[key] = slider
            self.slider_value_labels[key] = vlab
            parent.addLayout(row)

        make_slider("Canny Low", "canny_low", 255)
        make_slider("Canny High", "canny_high", 255)
        make_slider("H Min", "h_min", 179)
        make_slider("H Max", "h_max", 179)
        make_slider("S Min", "s_min", 255)
        make_slider("S Max", "s_max", 255)
        make_slider("V Min", "v_min", 255)
        make_slider("V Max", "v_max", 255)
        make_slider("Min Area", "contour_min_area", 5000)

    def _build_metrics_bar(self, outer):
        """底部指标仪表盘：状态 / 三个 FPS / 分辨率 / JPEG / 带宽 / 帧数。"""
        bar = QFrame()
        bar.setObjectName("metricsBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(12)

        # 状态块（含状态圆点）
        status_chip = QFrame()
        status_chip.setProperty("cardRole", "chip")
        sbox = QVBoxLayout(status_chip)
        sbox.setContentsMargins(12, 8, 12, 8)
        sbox.setSpacing(2)
        sl = QLabel("状态")
        sl.setProperty("textRole", "chipLabel")
        sbox.addWidget(sl)
        sval_row = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setProperty("statusRole", "dot")
        self.status_dot.setFixedSize(10, 10)
        sval_row.addWidget(self.status_dot)
        self.status_value = QLabel("Idle")
        self.status_value.setProperty("textRole", "chipValue")
        sval_row.addWidget(self.status_value)
        sbox.addLayout(sval_row)
        row.addWidget(status_chip)

        self.metrics = {}
        metric_defs = [
            ("采集FPS", "phone"), ("接收FPS", "recv"), ("显示FPS", "disp"),
            ("分辨率", "res"), ("平均JPEG", "jpeg"), ("带宽Mbps", "mbps"),
            ("接收帧", "received"), ("无效帧", "invalid"), ("丢帧", "dropped"),
        ]
        for label, key in metric_defs:
            chip = QFrame()
            chip.setProperty("cardRole", "chip")
            vbox = QVBoxLayout(chip)
            vbox.setContentsMargins(12, 8, 12, 8)
            vbox.setSpacing(2)
            lab = QLabel(label)
            lab.setProperty("textRole", "chipLabel")
            vbox.addWidget(lab)
            val = QLabel("--")
            val.setProperty("textRole", "chipValue")
            vbox.addWidget(val)
            row.addWidget(chip)
            self.metrics[key] = val

        outer.addWidget(bar)

    # =====================================================================
    # 交互
    # =====================================================================

    def set_mode(self, mode):
        self.mode = mode
        names = {
            vision_modes.MODE_ORIGINAL: "原始", vision_modes.MODE_GRAY: "灰度",
            vision_modes.MODE_CANNY: "Canny", vision_modes.MODE_HSV: "HSV",
            vision_modes.MODE_CONTOUR: "轮廓",
        }
        self.mode_label.setText(f"当前: {names.get(mode, mode)}")

    def on_slider(self, key, value):
        self.params[key] = int(value)
        self.slider_value_labels[key].setText(str(int(value)))

    def save_capture(self):
        frame, _ = self.reader.get_latest_frame()
        if frame is None:
            self.stats["error"] = "无帧可保存"
            return
        os.makedirs(CAPTURES_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        h, w = frame.shape[:2]
        tag = f"{stamp}-{self.mode}-{w}x{h}"
        disp = vision_modes.apply_mode(self.mode, frame, self.params)
        cv2.imwrite(os.path.join(CAPTURES_DIR, f"{tag}-original.jpg"), frame)
        cv2.imwrite(os.path.join(CAPTURES_DIR, f"{tag}-{self.mode}.png"), disp)
        self.stats["error"] = f"已保存: {tag}"

    def reconnect(self):
        # 手动重连：AppModel 内部在后台线程执行 stop+start，不阻塞 GUI
        self.model.set_last_error("已请求重连...")
        self.model.reconnect()

    def closeEvent(self, event):
        """窗口关闭：确保后台读取线程被 stop。"""
        self.model.stop()
        super().closeEvent(event)

    # =====================================================================
    # 刷新
    # =====================================================================

    def _refresh(self):
        try:
            self.model.refresh()  # 汇总统计（不含网络请求；/ping 由后台 worker 负责）
            self._update_frame()
            self._update_metrics()
        except Exception as e:  # noqa: BLE001 - UI 刷新不能崩
            logging.exception("PySide6 刷新异常")
            self.stats["error"] = str(e)

    def _update_frame(self):
        # 共享模型帧新鲜度语义：未收到首帧或超过阈值（3s）无新帧时
        # 返回 (None, None)，进入占位分支，替换旧画面。
        frame, num = self.reader.get_latest_frame()
        if num is not None and num == self._last_frame_num:
            return  # 同帧去重：帧号没变，跳过重复处理与重建
        self._last_frame_num = num

        snap = self.model.snapshot()
        if frame is not None:
            # 收到新帧（含恢复后第一张新帧）：立即替换占位画面并重置占位状态
            self._render_type = RENDER_FRAME
            self._placeholder_state = None
            disp = vision_modes.apply_mode(self.mode, frame, self.params)
            self.model.mark_frame_displayed()  # 通知共享模型：本帧已显示
            self._show_frame(disp)
        else:
            # 断流/未连接占位分支。占位图必须用 np.zeros 构造纯背景再画字，
            # 不能叠在旧帧像素上。只有渲染类型或连接状态变化时才重建。
            if snap.connection_state == "Stopped":
                render_type = RENDER_STOPPED
                text = "已停止"
            elif snap.connection_state == "Reconnecting":
                render_type = RENDER_RECONNECTING
                text = "视频流已中断，正在重连..."
            else:
                render_type = RENDER_CONNECTING
                text = f"正在连接... 状态: {snap.connection_state}"
            if render_type == self._render_type and snap.connection_state == self._placeholder_state:
                return
            self._render_type = render_type
            self._placeholder_state = snap.connection_state
            placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, text, (30, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            self._show_frame(placeholder)

        # 从共享快照同步统计（不再在本窗口自算 FPS/吞吐/丢帧）
        st = self.stats
        st["state"] = snap.connection_state
        st["phone_fps"] = snap.phone_fps
        st["recv_fps"] = snap.receive_fps
        st["disp_fps"] = snap.display_fps
        st["received"] = snap.received_frames
        st["invalid"] = snap.invalid_frames
        st["dropped"] = snap.estimated_dropped_frames
        st["avg_jpeg_mb"] = snap.average_jpeg_bytes / (1024 * 1024)
        st["throughput_mbps"] = snap.bandwidth_mbps
        # 双向同步错误：有错误显示真实错误；无错误（连接恢复后模型已清空）
        # 立即清空本地残留，标题栏恢复正常，不留旧 HTTP 错误。
        st["error"] = snap.last_error or ""

    def _show_frame(self, frame_bgr):
        """把 BGR 帧转 QPixmap 显示到画面区（等比例缩放）。"""
        img = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, c = img.shape
        self._qimg = QImage(img.data, w, h, c * w, QImage.Format_RGB888)
        # 缩放到画面区尺寸，保持比例
        target = self.video_view.size()
        if target.width() > 0 and target.height() > 0:
            pixmap = QPixmap.fromImage(self._qimg).scaled(
                target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.video_view.setPixmap(pixmap)

    def _update_ping(self):
        """已废弃：/ping 轮询与丢帧估算由 AppModel.refresh() 统一处理。"""

    def _update_metrics(self):
        st = self.stats
        # 状态块颜色：Streaming 绿 / Reconnecting 琥珀 / 错误红 / 其余灰
        state = st["state"]
        if state == "Streaming":
            chip_state, color = "success", "#3DD68C"
        elif state == "Reconnecting":
            chip_state, color = "warning", "#F5A524"
        elif st["error"]:
            chip_state, color = "error", "#F2645F"
        else:
            chip_state, color = "idle", "#5C6470"
        self.status_value.setText(state)
        self.status_value.setProperty("chipState", chip_state)
        self.status_value.style().unpolish(self.status_value)
        self.status_value.style().polish(self.status_value)
        self.status_dot.setProperty("chipState", chip_state)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

        self.metrics["phone"].setText(f"{st['phone_fps']:.1f}")
        self.metrics["recv"].setText(f"{st['recv_fps']:.1f}")
        self.metrics["disp"].setText(f"{st['disp_fps']:.1f}")
        self.metrics["res"].setText(f"{st['width']}x{st['height']}")
        self.metrics["jpeg"].setText(f"{st['avg_jpeg_mb']:.2f}MB")
        self.metrics["mbps"].setText(f"{st['throughput_mbps']:.1f}")
        self.metrics["received"].setText(str(st["received"]))
        self.metrics["invalid"].setText(str(st["invalid"]))
        self.metrics["dropped"].setText(str(st["dropped"]))

        # 错误信息显示在窗口标题栏提示（简单方式）。
        # st["error"] 已由 _update_frame() 与共享模型双向同步：有错误显示真实错误，
        # 连接恢复后模型把 last_error 清为 None，这里也随之恢复正常标题，不留残留。
        if st["error"]:
            self.setWindowTitle(f"PhoneVision Lab — {st['error'][:30]}")
        else:
            self.setWindowTitle("PhoneVision Lab")


import cv2  # noqa: E402
