"""
PhoneVision Lab — PySide6 主窗口（视觉工作台布局）。

职责：一个窗口内集成"顶栏 + 最大画面区 + 右侧上下文检查器 + 底部可折叠诊断区"，
形态更像单目显微镜/示波器工作台，而非功能原型：
  - 顶栏：品牌标识 + 设备名 + 状态灯 + 保存/重连（标题固定 "PhoneVision Lab"）
  - 画面区：VideoView 占主窗口大部分空间，居中占位 / 左下角信息
  - 右侧检查器：模式 1-5 + 当前模式参数滑块（按模式过滤隐藏）+ 教学提示
  - 底部：DiagnosticsPanel 诊断区（默认只显示 接收FPS/显示FPS/丢帧）

为什么这样设计：
  - 用 PySide6 专业 GUI 框架 + QSS 样式表（style.qss），做出产品级质感。
  - 后台用 mjpeg_reader 线程收帧（只留最新帧），QTimer 在主线程轮询显示，
    互不阻塞，延迟不累积。
  - 视觉处理复用 vision_modes.apply_mode，本窗口只负责取帧、调参、显示。
  - UI 复用组件从 ui_components 导入（StatusPill/ToastBanner/VideoView/
    DiagnosticsPanel），本文件只负责工作台布局与交互编排。

初学者调试观察点：
  - 画面不动：看 StatusPill 变琥珀（Reconnecting），说明流断了在等重连。
  - 滑块没效果：确认当前模式匹配（Canny 滑块只影响 Canny 模式），
    无关模式的滑块整行隐藏、但值会保留。
  - 处理慢：看诊断区"显示FPS"明显低于"接收FPS"。
  - 快捷键：S 保存、R 重连、1-5 切模式、Ctrl+Q 退出。
"""
import logging
import os
from datetime import datetime

import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QButtonGroup, QComboBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton,
    QScrollArea, QSlider, QTextEdit, QVBoxLayout, QWidget,
)

import app_model
import mjpeg_reader
import vision_modes
from qt_client.i18n import Translator

# 保存截图目录：qt_client 的上一级 captures/
CAPTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")

# 渲染类型常量：画面区当前显示内容的语义分类。由 VideoView.render_state 承接。
RENDER_FRAME = "frame"
RENDER_CONNECTING = "connecting"
RENDER_RECONNECTING = "reconnecting"
RENDER_STOPPED = "stopped"
RENDER_ERROR = "error"

# 各模式可见参数（其余滑块整行隐藏，但滑块对象始终存在、保留值）。
# 可见参数数：original=0, gray=0, canny=2, hsv=6, contour=7。
MODE_PARAM_KEYS = {
    vision_modes.MODE_ORIGINAL: [],
    vision_modes.MODE_GRAY: [],
    vision_modes.MODE_CANNY: ["canny_low", "canny_high"],
    vision_modes.MODE_HSV: ["h_min", "h_max", "s_min", "s_max", "v_min", "v_max"],
    vision_modes.MODE_CONTOUR: [
        "h_min", "h_max", "s_min", "s_max", "v_min", "v_max", "contour_min_area",
    ],
}

# 滑块英文主标签（两种语言一致，与 STRINGS 参数主标签对齐）。
SLIDER_LABELS = {
    "canny_low": "Canny Low", "canny_high": "Canny High",
    "h_min": "H Min", "h_max": "H Max",
    "s_min": "S Min", "s_max": "S Max",
    "v_min": "V Min", "v_max": "V Max",
    "contour_min_area": "Min Area",
}
# 参数键 → STRINGS 副标签 key（双语）。
SLIDER_SUB_KEYS = {
    "canny_low": "param_canny_low_sub", "canny_high": "param_canny_high_sub",
    "h_min": "param_h_min_sub", "h_max": "param_h_max_sub",
    "s_min": "param_s_min_sub", "s_max": "param_s_max_sub",
    "v_min": "param_v_min_sub", "v_max": "param_v_max_sub",
    "contour_min_area": "param_contour_min_area_sub",
}

# 教学提示：key 随模式更新（双语字典取文案）。
MODE_HINT_KEYS = {
    vision_modes.MODE_ORIGINAL: "hint_original",
    vision_modes.MODE_GRAY: "hint_gray",
    vision_modes.MODE_CANNY: "hint_canny",
    vision_modes.MODE_HSV: "hint_hsv",
    vision_modes.MODE_CONTOUR: "hint_contour",
}
# 无参数模式的参数区空状态 key（双语）。
MODE_EMPTY_KEYS = {
    vision_modes.MODE_ORIGINAL: "param_empty_original",
    vision_modes.MODE_GRAY: "param_empty_gray",
}

# 模式 → STRINGS 模式名 key（双语）。
MODE_NAME_KEYS = {
    vision_modes.MODE_ORIGINAL: "mode_original",
    vision_modes.MODE_GRAY: "mode_gray",
    vision_modes.MODE_CANNY: "mode_canny",
    vision_modes.MODE_HSV: "mode_hsv",
    vision_modes.MODE_CONTOUR: "mode_contour",
}

# 语言选择器映射：界面选项显示名 → Translator 语言标识。
LANGUAGE_SELECTOR_OPTIONS = {
    "简体中文": "zh-CN",
    "English": "en",
}


class MainWindow(QMainWindow):
    """PhoneVision Lab 主窗口（视觉工作台布局）。"""

    def __init__(self, stream_url, ping_url, ping_info, translator=None):
        super().__init__()
        self.stream_url = stream_url
        self.ping_url = ping_url
        self.ping_info = ping_info

        # 双语文案服务：外部可注入（main.py 传入全局 Translator）；未传时
        # 内部创建默认实例（zh-CN 兼容），存为 self.tr 并暴露 self.translator 别名。
        self.tr = translator if translator is not None else Translator()
        self.translator = self.tr
        # 语言切换（下拉或外部 set_language）统一走 _apply_language 刷新文案。
        self.tr.language_changed.connect(self._apply_language)
        # 当前 toast 的可重译状态：(i18n_key, kwargs, kind)。语言切换时重发。
        self._toast_state = None
        # 上一次已展示的连接错误。用于"错误从有到无"时只清一次 error toast，
        # 而不是每 33ms 无条件 clear()（那会把一次性 success/warning 也吞掉）。
        self._last_error_shown = ""

        # 窗口标题固定为 "PhoneVision Lab"。
        # HTTPConnectionPool/保存结果/错误信息绝不允许进标题。
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
        self._last_placeholder = None  # (state, detail)：占位去重，避免每 tick 重绘
        self._qimg = None  # 保引用，防止 QImage 底层数据被回收
        # 兼容旧接口：metrics dict（键与旧版一致），供测试与诊断区使用。
        self.metrics = {
            "phone": None, "recv": None, "disp": None, "res": None,
            "jpeg": None, "mbps": None, "received": None,
            "invalid": None, "dropped": None,
        }

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

        # ---- 快捷键 ----
        self._build_shortcuts()

        # ---- 定时刷新 ----
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(33)  # ~30fps

    # =====================================================================
    # 界面构建
    # =====================================================================

    def _build_ui(self):
        from qt_client.ui_components import (
            DiagnosticsPanel, StatusPill, ToastBanner, VideoView,
        )

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # ---- 顶栏：品牌 + 设备名 + 状态灯 + 保存/重连 ----
        self._build_topbar(outer, StatusPill, ToastBanner)

        # ---- 内容行：画面区(最大面积) + 右侧检查器 ----
        content = QHBoxLayout()
        content.setSpacing(10)
        outer.addLayout(content, 1)

        # 画面区：VideoView 占主窗口大部分空间
        self.video_view = VideoView(translator=self.tr)
        self.video_view.reconnect_requested.connect(self.reconnect)
        self.tr.language_changed.connect(self.video_view._apply_language)
        content.addWidget(self.video_view, 1)

        # 右侧检查器：模式 1-5 + 当前模式参数 + 教学提示
        self._build_inspector(content)

        # ---- 底部诊断区（可折叠）----
        self.diagnostics = DiagnosticsPanel(translator=self.tr)
        self.tr.language_changed.connect(self.diagnostics._apply_language)
        outer.addWidget(self.diagnostics)

        # ---- 底部工作台标签页：数据集 / 训练导出 / 硬件联动 / 性能 ----
        self._build_workbench_tabs(outer)

        # ---- Toast（顶栏下浮层）----
        self.toast = ToastBanner()
        outer.addWidget(self.toast)

        # 按当前语言刷新全部可见文案（构造时 _apply_mode_params 等已用英文
        # 标签初始化滑块副标签，这里统一切到正确语言）。
        self._apply_language()

    def _build_workbench_tabs(self, outer):
        """底部标签页：把"数据集 -> 训练导出 -> 硬件联动 -> 性能分析"串成一条工作流。

        为什么用标签页而不是弹窗：这几步是同一任务的连续阶段，放在一个窗口里
        切换比开多个对话框更贴近"工作台"的心智模型，也避免窗口丢失。
        """
        from PySide6.QtWidgets import QTabWidget

        from qt_client.dataset_panel import DatasetPanel
        from qt_client.hardware_panel import HardwarePanel
        from qt_client.perf_panel import PerfPanel
        from qt_client.train_panel import TrainPanel

        self.tabs = QTabWidget()
        self.tabs.setObjectName("workbenchTabs")
        self.tabs.setMinimumHeight(300)

        # 数据集：帧来自当前 MJPEG 流（复用 reader，不另开连接）
        self.dataset_panel = DatasetPanel(
            translator=self.tr, frame_provider=self._capture_frame_provider)
        self.train_panel = TrainPanel(
            translator=self.tr, dataset_panel=self.dataset_panel)
        self.hardware_panel = HardwarePanel(
            translator=self.tr, class_provider=self._class_provider)
        self.perf_panel = PerfPanel(
            translator=self.tr, model_provider=self._model_info_provider)

        for panel in (self.dataset_panel, self.train_panel,
                      self.hardware_panel, self.perf_panel):
            # The bottom workspace may be shorter than a panel on a laptop.
            # Preserve natural control sizes and make every action reachable.
            panel.setMinimumHeight(panel.sizeHint().height())
            scroll = QScrollArea()
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            self.tabs.addTab(scroll, "")
        outer.addWidget(self.tabs, 1)

        # 语言切换时刷新标签页标题
        self.tr.language_changed.connect(self._apply_tab_language)
        # 构造时也要刷一次：language_changed 只在"切换语言"时触发，
        # 不刷的话标签页标题会是空字符串。
        self._apply_tab_language()

    def _apply_tab_language(self):
        """按当前语言刷新底部标签页标题。

        索引 0~3 对应 数据集/训练导出/硬件联动/性能分析；
        "视觉工作台"是主界面本身，不占标签页。
        """
        tab_keys = ["wb_tab_dataset", "wb_tab_train", "wb_tab_hardware",
                    "wb_tab_perf"]
        for index, key in enumerate(tab_keys):
            self.tabs.setTabText(index, self.tr.text(key))

    # ---- 标签页需要的数据提供者 ----

    def _capture_frame_provider(self):
        """采集用的帧提供者：直接复用 MJPEG reader 的最新帧。

        返回 (BGR ndarray 或 None, 帧号或 None)。断线/无帧时返回 (None, None)，
        数据集面板会明确提示"当前没有可采集的画面"。
        """
        try:
            frame, num = self.model.get_latest_frame()
        except Exception:  # noqa: BLE001 - 取帧失败按"无帧"处理
            return None, None
        return frame, num

    def _class_provider(self):
        """当前数据集/模型的类别名（硬件面板的目标类别下拉用）。"""
        panel = self.dataset_panel
        if panel is not None and panel.store is not None \
                and panel.store.dataset is not None:
            return panel.store.dataset.class_names()
        return []

    def _model_info_provider(self):
        """PC 当前无法确认手机加载了哪个模型。"""
        return {}

    def _build_topbar(self, outer, StatusPill, ToastBanner):
        """顶栏：左侧品牌+设备名，右侧 StatusPill + 保存/重连按钮。"""
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(48)
        bar = QHBoxLayout(topbar)
        bar.setContentsMargins(14, 0, 14, 0)
        bar.setSpacing(10)

        brand = QLabel("PhoneVision Lab")
        brand.setObjectName("brandLabel")
        bar.addWidget(brand)

        device_sep = QLabel("·")
        device_sep.setProperty("textRole", "muted")
        bar.addWidget(device_sep)

        self.device_label = QLabel(self.tr.text("device_placeholder"))
        self.device_label.setObjectName("deviceLabel")
        bar.addWidget(self.device_label)

        bar.addStretch(1)

        # 语言选择器：简体中文 / English，切换即时生效并持久化。
        self.language_selector = QComboBox()
        self.language_selector.setObjectName("languageSelector")
        for label, lang in LANGUAGE_SELECTOR_OPTIONS.items():
            self.language_selector.addItem(label, lang)
        self.language_selector.setCurrentIndex(
            list(LANGUAGE_SELECTOR_OPTIONS.values()).index(self.tr.language()))
        self.language_selector.currentIndexChanged.connect(
            self._on_language_selector_changed)
        self.language_selector.setToolTip(self.tr.text("language"))
        bar.addWidget(self.language_selector)

        self.status_pill = StatusPill()
        self.status_pill.set_state(self.stats["state"])
        bar.addWidget(self.status_pill)

        self.save_btn = QPushButton(self.tr.text("save_screenshot"))
        self.save_btn.setObjectName("saveButton")
        self.save_btn.setProperty("buttonRole", "primary")
        self.save_btn.setFixedHeight(32)
        self.save_btn.clicked.connect(self.save_capture)
        bar.addWidget(self.save_btn)

        self.reconnect_btn = QPushButton(self.tr.text("reconnect"))
        self.reconnect_btn.setObjectName("reconnectButton")
        self.reconnect_btn.setProperty("buttonRole", "ghost")
        self.reconnect_btn.setFixedHeight(32)
        self.reconnect_btn.clicked.connect(self.reconnect)
        bar.addWidget(self.reconnect_btn)

        outer.addWidget(topbar)

    def _build_inspector(self, content):
        """右侧上下文检查器：模式 1-5 + 参数滑块 + 教学提示。"""
        inspector = QFrame()
        inspector.setObjectName("inspector")
        inspector.setFixedWidth(272)
        box = QVBoxLayout(inspector)
        box.setContentsMargins(14, 12, 14, 14)
        box.setSpacing(10)
        content.addWidget(inspector)

        # ---- 模式卡片（紧凑纵向 5 模式，编号 1-5）----
        mode_card = QFrame()
        mode_card.setProperty("cardRole", "card")
        mbox = QVBoxLayout(mode_card)
        mbox.setContentsMargins(12, 10, 12, 12)
        mbox.setSpacing(8)

        mtitle = QLabel(self.tr.text("mode_title"))
        mtitle.setProperty("textRole", "groupTitle")
        mbox.addWidget(mtitle)

        self._build_mode_buttons(mbox)

        self.mode_label = QLabel(
            self.tr.text("current_mode", mode=self._mode_name(self.mode)))
        self.mode_label.setProperty("textRole", "caption")
        mbox.addWidget(self.mode_label)

        box.addWidget(mode_card)

        # ---- 参数卡片（QScrollArea，按模式过滤隐藏无关行）----
        param_card = QFrame()
        param_card.setProperty("cardRole", "card")
        pv = QVBoxLayout(param_card)
        pv.setContentsMargins(12, 10, 12, 12)
        pv.setSpacing(6)

        ptitle = QLabel(self.tr.text("param_title"))
        ptitle.setProperty("textRole", "groupTitle")
        pv.addWidget(ptitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(150)
        self._param_container = QWidget()
        self._param_box = QVBoxLayout(self._param_container)
        self._param_box.setContentsMargins(2, 2, 2, 2)
        self._param_box.setSpacing(6)
        self._param_box.addStretch(1)
        scroll.setWidget(self._param_container)
        pv.addWidget(scroll, 1)

        self._build_sliders(self._param_box)

        # 教学提示：单行文案随模式更新
        self.hint_label = QLabel()
        self.hint_label.setProperty("textRole", "hint")
        self.hint_label.setWordWrap(True)
        pv.addWidget(self.hint_label)

        box.addWidget(param_card, 1)

        # 初始应用当前模式（original）：隐藏全部参数行，显示教学空状态
        self._apply_mode_params()

    def _build_mode_buttons(self, parent):
        """5 个模式按钮（纵向紧凑），QButtonGroup 互斥，当前模式高亮。"""
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = {}
        # 每个模式的编号（1-5）与 STRINGS key，供按钮文本/apply 语言刷新用。
        self._mode_numbers = {}
        self._mode_name_keys = dict(MODE_NAME_KEYS)

        for num, mode in enumerate(
                (vision_modes.MODE_ORIGINAL, vision_modes.MODE_GRAY,
                 vision_modes.MODE_CANNY, vision_modes.MODE_HSV,
                 vision_modes.MODE_CONTOUR), start=1):
            btn = QPushButton(f"{num} {self._mode_name(mode)}")
            btn.setObjectName("modeButton")
            btn.setProperty("mode", mode)
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            self.mode_group.addButton(btn)
            self.mode_buttons[mode] = btn
            self._mode_numbers[mode] = num
            parent.addWidget(btn)
        # 默认选中"原始"
        self.mode_buttons[vision_modes.MODE_ORIGINAL].setChecked(True)

    def _build_sliders(self, parent):
        """参数滑块（9 个全部存在，仅按模式隐藏；滑块带中文副标签）。"""
        self.sliders = {}
        self.slider_value_labels = {}
        self._slider_sub_labels = {}
        # 记录每个参数对应的行容器（QWidget，便于 setVisible 整行隐藏）
        self._param_rows = {}

        def make_slider(key, maxv):
            # 每个参数一个独立 QWidget 行：setVisible(False) 才能整行隐藏
            row_widget = QWidget()
            row_widget.setProperty("paramRole", "row")
            row = QVBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(2)

            lab_row = QHBoxLayout()
            lab_row.setSpacing(6)
            lab = QLabel(SLIDER_LABELS[key])
            lab.setProperty("textRole", "caption")
            lab.setFixedWidth(88)
            lab_row.addWidget(lab)
            sub = QLabel(self.tr.text(SLIDER_SUB_KEYS[key]))
            sub.setProperty("textRole", "hint")
            lab_row.addWidget(sub, 1)
            row.addLayout(lab_row)

            slider_row = QHBoxLayout()
            slider_row.setSpacing(6)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, maxv)
            slider.setValue(self.params[key])
            slider.valueChanged.connect(
                lambda v, k=key: self.on_slider(k, v))
            slider_row.addWidget(slider, 1)

            vlab = QLabel(str(self.params[key]))
            vlab.setObjectName("sliderValue")
            vlab.setFixedWidth(36)
            vlab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            slider_row.addWidget(vlab)

            row.addLayout(slider_row)

            self.sliders[key] = slider
            self.slider_value_labels[key] = vlab
            self._slider_sub_labels[key] = sub
            self._param_rows[key] = row_widget
            parent.insertWidget(parent.count() - 1, row_widget)  # 插到 stretch 之前

        make_slider("canny_low", 255)
        make_slider("canny_high", 255)
        make_slider("h_min", 179)
        make_slider("h_max", 179)
        make_slider("s_min", 255)
        make_slider("s_max", 255)
        make_slider("v_min", 255)
        make_slider("v_max", 255)
        make_slider("contour_min_area", 5000)

    def _apply_mode_params(self):
        """按当前模式显示/隐藏参数行（无关参数整行隐藏，不是禁用）。"""
        visible = set(MODE_PARAM_KEYS.get(self.mode, []))
        for key, row in self._param_rows.items():
            row.setVisible(key in visible)

    def _apply_mode_hint(self):
        """更新教学提示文案与参数区空状态。"""
        hint = self.tr.text(MODE_HINT_KEYS.get(self.mode, ""))
        empty = not MODE_PARAM_KEYS.get(self.mode, [])
        if empty:
            hint = self.tr.text(
                MODE_EMPTY_KEYS.get(self.mode, "param_empty_original"))
        self.hint_label.setText(hint)
        self.hint_label.setProperty("hintRole", "empty" if empty else "active")
        self.hint_label.style().unpolish(self.hint_label)
        self.hint_label.style().polish(self.hint_label)

    def _mode_name(self, mode):
        """取某模式的当前语言显示名（编号由按钮文本拼，这里只回翻译名）。"""
        return self.tr.text(MODE_NAME_KEYS.get(mode, "mode_original"))

    # =====================================================================
    # 语言切换
    # =====================================================================

    def _on_language_selector_changed(self, index):
        """下拉切换语言：持久化并触发 language_changed → _apply_language。"""
        lang = self.language_selector.itemData(index)
        if lang and lang != self.tr.language():
            self.tr.set_language(lang, persist=True)

    def _apply_language(self):
        """按当前语言刷新全部可见文案（不重启网络/模型/模式/参数）。

        只更新"纯文案"控件，绝不动模式、参数值、诊断展开态、视频画面与
        AppModel——这些是 UI 用户状态，必须与语言正交（P0-4B 契约）。
        """
        # 顶栏：设备占位、保存/重连按钮、语言选择器 tooltip
        self.device_label.setText(self.tr.text("device_placeholder"))
        self.save_btn.setText(self.tr.text("save_screenshot"))
        self.reconnect_btn.setText(self.tr.text("reconnect"))
        self.language_selector.setToolTip(self.tr.text("language"))

        # 模式按钮（编号 + 翻译名，格式 f"{num} {name}"）
        for mode, btn in self.mode_buttons.items():
            num = self._mode_numbers.get(mode, 1)
            btn.setText(f"{num} {self._mode_name(mode)}")

        # 当前模式标签
        self.mode_label.setText(
            self.tr.text("current_mode", mode=self._mode_name(self.mode)))

        # 教学提示 / 参数区空状态
        self._apply_mode_hint()

        # 参数滑块副标签
        for key, sub in self._slider_sub_labels.items():
            sub.setText(self.tr.text(SLIDER_SUB_KEYS[key]))

        # 若当前有 toast 显示，用新语言重发（错误 toast 由 _update_metrics 接管）
        if self._toast_state is not None:
            key, kwargs, kind = self._toast_state
            self.toast.show_message(self.tr.text(key, **kwargs), kind)

    # =====================================================================
    # 快捷键
    # =====================================================================

    def _build_shortcuts(self):
        """S=保存、R=重连、1-5=切模式、Ctrl+Q=退出。

        单字符快捷键是窗口级的，Qt 会先于焦点控件处理按键。若不做守卫，
        用户在数据集类别名、硬件 IP/端口输入框里打字就会触发保存/重连/切模式
        （输入 192.168.1.10 必然命中 "1"）。因此统一包一层 _guarded()。
        """
        self.shortcuts = [
            QShortcut(QKeySequence("S"), self),
            QShortcut(QKeySequence("R"), self),
            QShortcut(QKeySequence("Ctrl+Q"), self),
        ]
        self.shortcuts[0].activated.connect(self._guarded(self.save_capture))
        self.shortcuts[1].activated.connect(self._guarded(self.reconnect))
        self.shortcuts[2].activated.connect(self.close)

        for i, mode in enumerate(MODE_PARAM_KEYS, start=1):
            sc = QShortcut(QKeySequence(str(i)), self)
            sc.activated.connect(self._guarded(lambda m=mode: self.set_mode(m)))
            self.shortcuts.append(sc)

    @staticmethod
    def _focus_in_text_input() -> bool:
        """焦点是否落在文本输入类控件上（此时单字符快捷键必须让位）。"""
        w = QApplication.focusWidget()
        if w is None:
            return False
        return isinstance(w, (QLineEdit, QAbstractSpinBox, QTextEdit,
                              QPlainTextEdit))

    def _guarded(self, action):
        """把单字符快捷键动作包一层：在输入框里打字时不触发。"""
        def runner():
            if self._focus_in_text_input():
                return
            action()
        return runner

    # =====================================================================
    # 交互
    # =====================================================================

    def set_mode(self, mode):
        if mode not in MODE_PARAM_KEYS:
            mode = vision_modes.MODE_ORIGINAL
        self.mode = mode
        btn = self.mode_buttons.get(mode)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        self.mode_label.setText(
            self.tr.text("current_mode", mode=self._mode_name(mode)))
        self._apply_mode_params()
        self._apply_mode_hint()

    def on_slider(self, key, value):
        self.params[key] = int(value)
        self.slider_value_labels[key].setText(str(int(value)))

    def save_capture(self):
        frame, _ = self.reader.get_latest_frame()
        if frame is None:
            # 无帧：warning 通道，不改标题、不写 error 通道
            self._toast_state = ("toast_no_frame", {}, "warning")
            self.toast.show_message(self.tr.text("toast_no_frame"), "warning")
            return
        try:
            import cv2
            os.makedirs(CAPTURES_DIR, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            h, w = frame.shape[:2]
            tag = f"{stamp}-{self.mode}-{w}x{h}"
            disp = vision_modes.apply_mode(self.mode, frame, self.params)
            cv2.imwrite(os.path.join(CAPTURES_DIR, f"{tag}-original.jpg"), frame)
            cv2.imwrite(os.path.join(CAPTURES_DIR, f"{tag}-{self.mode}.png"), disp)
        except Exception as e:  # noqa: BLE001 - 保存失败走 error toast
            self._toast_state = ("toast_save_failed", {"error": str(e)}, "error")
            self.toast.show_message(
                self.tr.text("toast_save_failed", error=str(e)), "error")
            return
        path = os.path.join(CAPTURES_DIR, f"{tag}-{self.mode}.png")
        # 保存成功：success 通道，绝不写 error 通道、绝不改标题
        self._toast_state = ("toast_saved", {"path": path}, "success")
        self.toast.show_message(
            self.tr.text("toast_saved", path=path), "success")

    def reconnect(self):
        # 手动重连：AppModel 内部在后台线程执行 stop+start，不阻塞 GUI
        self.model.reconnect()

    def closeEvent(self, event):
        """窗口关闭：确保后台读取线程被 stop，并回收各面板的长任务。"""
        training_panel = getattr(self, "train_panel", None)
        if training_panel is not None and training_panel.export_in_progress():
            self.toast.show_message(self.tr.text("tr_export_wait_close"), "warning")
            event.ignore()
            return
        self.model.stop()
        # 训练线程：取消并 join，避免遗留后台训练进程
        trainer = getattr(self, "train_panel", None)
        if trainer is not None and trainer.trainer is not None \
                and trainer.trainer.is_running():
            trainer.trainer.cancel()
            trainer.trainer.join(timeout=3.0)
        # 硬件连接：断开，清理去重缓存
        hardware = getattr(self, "hardware_panel", None)
        if hardware is not None:
            hardware.on_disconnect()
        # 数据集采集定时器
        dataset = getattr(self, "dataset_panel", None)
        if dataset is not None and dataset.is_capturing():
            dataset.on_stop_capture()
        super().closeEvent(event)

    # =====================================================================
    # 刷新
    # =====================================================================

    def _refresh(self):
        try:
            self.model.refresh()  # 汇总统计（不含网络请求；/ping 由后台 worker 负责）
            self._update_frame()
            self._update_metrics()
            self._feed_perf_panel()
        except Exception as e:  # noqa: BLE001 - UI 刷新不能崩
            logging.exception("PySide6 刷新异常")
            self.stats["error"] = str(e)

    def _feed_perf_panel(self):
        """把当前连接/推理口径喂给性能面板（只在测试进行中才有意义）。"""
        perf = getattr(self, "perf_panel", None)
        if perf is None or perf.record is None:
            return
        st = self.stats
        if st.get("state") != "Streaming":
            perf.clear_transport()
            return
        perf.update_transport(
            phone_capture_fps=st.get("phone_fps", 0.0) or 0.0,
            pc_receive_fps=st.get("recv_fps", 0.0) or 0.0,
            pc_display_fps=st.get("disp_fps", 0.0) or 0.0,
            dropped=int(st.get("dropped", 0) or 0),
        )

    def _update_frame(self):
        # 共享模型帧新鲜度语义：未收到首帧或超过阈值（3s）无新帧时
        # 返回 (None, None)，进入占位分支，替换旧画面。
        frame, num = self.reader.get_latest_frame()
        snap = self.model.snapshot()

        if num is not None and num != self._last_frame_num:
            # 只有"新帧"才付出 apply_mode + 重建 QPixmap 的代价。
            self._last_frame_num = num
            disp = vision_modes.apply_mode(self.mode, frame, self.params)
            self.model.mark_frame_displayed()  # 通知共享模型：本帧已显示
            self._show_frame(disp)
            self._last_placeholder = None      # 画面已恢复，允许下次重新占位
        elif frame is None:
            # 断流/未连接/陈旧：占位分支。帧号去重绝不能挡住这里，
            # 否则停流后状态灯与占位会永久停在上一次有新帧的时刻。
            state, detail = self._placeholder_for(snap)
            if (state, detail) != self._last_placeholder:
                self._last_placeholder = (state, detail)
                self.video_view.set_placeholder(state, detail)

        # 从共享快照同步统计（不再在本窗口自算 FPS/吞吐/丢帧）。
        # 必须在"有没有新帧"之外执行：状态/分辨率/错误都会在没有新帧时变化。
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
        # 分辨率必须跟着快照走：ping_info 为空（走启动页连接）时初始值是 0x0，
        # 只有这里同步，诊断区的 "分辨率" 才会在 /ping 成功后真正更新。
        st["width"] = snap.width
        st["height"] = snap.height
        # 双向同步错误：有错误显示真实错误；无错误（连接恢复后模型已清空）
        # 立即清空本地残留，不留旧 HTTP 错误。
        st["error"] = snap.last_error or ""
        # 设备名：从 /ping 获得后更新顶栏；未获得/被清空时显示占位文案
        if snap.device_name:
            self.device_label.setText(snap.device_name)
        else:
            self.device_label.setText(self.tr.text("device_placeholder"))

    def _placeholder_for(self, snap):
        """按快照决定占位类型与副文案（纯函数，便于测试）。"""
        # 状态名用大写，匹配 VideoView.PLACEHOLDER_CONFIG。
        if snap.connection_state == "Stopped":
            return "Stopped", self.tr.text("placeholder_stopped")
        if snap.connection_state == "Reconnecting":
            return "Reconnecting", self.tr.text("placeholder_reconnecting_sub")
        if snap.last_error:
            return "Error", snap.last_error or self.tr.text("placeholder_error")
        return ("Connecting",
                f"{self.tr.text('placeholder_connecting_sub')}: "
                f"{snap.connection_state}")

    def _show_frame(self, frame_bgr):
        """把 BGR 帧转 QPixmap 显示到画面区（等比例缩放）。"""
        img = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, c = img.shape
        # copy()：QImage 不持有 numpy 内存，img 是局部变量，函数返回即释放，
        # 不 copy 会把一个悬垂视图交给 QPixmap。帧率约 30fps，一次拷贝可忽略。
        self._qimg = QImage(img.data, w, h, c * w,
                            QImage.Format_RGB888).copy()
        self.video_view.set_frame(QPixmap.fromImage(self._qimg))

    def _update_metrics(self):
        st = self.stats

        # StatusPill 状态：仅表状态，错误只走 toast
        state = st["state"]
        if st["error"] and state in ("Idle", "Stopped", "Connecting"):
            state = "Error"
        self.status_pill.set_state(state)

        # 设备名保持同步（/ping 可能更新 device 字段）；空值回占位文案
        dev = self.model.snapshot().device_name
        if dev:
            self.device_label.setText(dev)
        else:
            self.device_label.setText(self.tr.text("device_placeholder"))

        # 错误语义：真实错误走 error toast；恢复后只清错误提示。
        # 关键：不能每个 tick 无条件 clear()——那会在 33ms 内吞掉
        # save_capture 的 success、"无画面" warning、关窗拦截警告，
        # 用户什么都看不到。一次性消息由 ToastBanner 自己的定时器消退。
        err = st["error"]
        if err:
            if err != self._last_error_shown:
                self._last_error_shown = err
                self.toast.show_message(err, "error")
        elif self._last_error_shown:
            # 错误从"有"变"无"：只清一次，且只清 error 类提示；
            # 若当前显示的是一次性 success/warning，不抢它。
            self._last_error_shown = ""
            current_kind = self._toast_state[2] if self._toast_state else None
            if current_kind in (None, "error"):
                self._toast_state = None
                self.toast.clear()

        # 诊断区：更新全部指标（DiagnosticsPanel 默认只显示 接收/显示FPS/丢帧）
        self.diagnostics.update_values({
            "phone_fps": st["phone_fps"],
            "recv_fps": st["recv_fps"],
            "disp_fps": st["disp_fps"],
            "mbps": st["throughput_mbps"],
            "avg_jpeg_mb": st["avg_jpeg_mb"],
            "received": st["received"],
            "invalid": st["invalid"],
            "dropped": st["dropped"],
            "width": st["width"],
            "height": st["height"],
        })
        # 同步兼容 dict（旧测试依赖 self.metrics）
        m = self.metrics
        m["phone"] = f"{st['phone_fps']:.1f}"
        m["recv"] = f"{st['recv_fps']:.1f}"
        m["disp"] = f"{st['disp_fps']:.1f}"
        m["res"] = f"{st['width']}x{st['height']}"
        m["jpeg"] = f"{st['avg_jpeg_mb']:.2f}MB"
        m["mbps"] = f"{st['throughput_mbps']:.1f}"
        m["received"] = str(st["received"])
        m["invalid"] = str(st["invalid"])
        m["dropped"] = str(st["dropped"])


import cv2  # noqa: E402
