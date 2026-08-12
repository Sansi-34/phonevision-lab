"""
PhoneVision Lab — PySide6 可复用 UI 组件。

职责：把主窗口（main_window.py）里与"布局编排"解耦的原子组件抽出来：
  - StatusPill        连接状态胶囊（圆点 + 颜色 + 文字）
  - ToastBanner       横向通知条（success/info/warning/error，自动消退）
  - VideoView         视频画面区（实时帧 + 左下角信息浮层 + 居中占位）
  - DiagnosticsPanel  诊断面板（默认三项，可展开）

为什么这样设计：
  - main_window.py 只负责"把哪些组件摆在哪里、绑哪些数据"，这些组件是纯展示的
    可复用件，不持有 AppModel、不实现网络/状态机，可被任意窗口复用与离线测试。
  - 每个组件的动态外观都用 setProperty("xxxRole", value) 暴露给 QSS 选择器
    （另一 agent 会在 style.qss 里写对应规则），组件本身不内嵌硬编码外观，
    主题统一由 QSS 管理。
  - 颜色/状态语义集中定义在常量表里，与 AppModel 的 connection_state 命名对齐，
    避免两套 GUI 口径分叉。

初学者调试观察点：
  - 画面不动：看 StatusPill 是否变琥珀（Reconnecting），说明流断了在等重连。
  - 长错误不完整：ToastBanner 的 QLabel 开了 setWordWrap，且带 tooltip。
  - 占位不居中：VideoView 的占位层是 Qt 布局布局居中的，不是 numpy 黑图手绘。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

__all__ = ["StatusPill", "ToastBanner", "VideoView", "DiagnosticsPanel"]


def _repolish(widget):
    """setProperty 改动态属性后强制刷新 QSS 重绘。

    为什么这样设计：Qt 样式表按属性值缓存，改了 setProperty 不重绘就看不见新样式，
    必须 unpolish + polish 让 QSS 重新匹配选择器。
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


# =====================================================================
# StatusPill —— 连接状态胶囊
# =====================================================================

# 连接状态 -> (chipState 角色, 颜色)。角色名与 QSS 选择器约定一致：
#   chipState="success" 用绿色、warning 用琥珀、error 用红、idle 用灰。
# 颜色值同时写在这里，方便另一 agent 写 QSS 时对齐（QSS 只需角色，不需要颜色常量）。
STATUS_COLORS = {
    "Streaming":    ("success", "#3DD68C"),
    "Reconnecting": ("warning", "#F5A524"),
    "Error":        ("error",   "#F2645F"),
    "Connecting":   ("idle",    "#5C6470"),
    "Stopped":      ("idle",    "#5C6470"),
    "Idle":         ("idle",    "#5C6470"),
}


class StatusPill(QWidget):
    """连接状态胶囊：圆点 + 颜色 + 文字三重表达，一眼可读当前连接状态。

    对外接口只暴露 set_state(state)，由主窗口把 AppSnapshot.connection_state 喂进来。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusPill")
        self.setProperty("pillRole", "status")  # QSS 可给胶囊整体加底
        self._state = "Idle"

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # 圆点：用 QLabel 撑出一个小方块，QSS 用 statusRole="dot" 画圆形着色。
        self._dot = QLabel(self)
        self._dot.setProperty("statusRole", "dot")
        self._dot.setFixedSize(10, 10)
        lay.addWidget(self._dot)

        # 文字：文本随状态变色（chipState 复用现有 QSS 的颜色规则）。
        self._text = QLabel(self._state, self)
        self._text.setProperty("textRole", "chipValue")
        lay.addWidget(self._text)

        self.set_state(self._state)

    def set_state(self, state: str) -> None:
        """切换连接状态：更新圆点颜色与文字。未知状态一律回落到灰色 idle。

        文字显示英文专名（Streaming/Connecting/...），双语文案由主窗口的
        占位/状态映射接管，本组件保持状态语义稳定。
        """
        self._state = state
        role, _ = STATUS_COLORS.get(state, ("idle", "#5C6470"))
        for w in (self._dot, self._text):
            w.setProperty("chipState", role)
            _repolish(w)
        self._text.setText(state)

    def state(self) -> str:
        """返回当前连接状态字符串。"""
        return self._state

    def state_role(self) -> str:
        """返回当前颜色角色（success/warning/error/idle），供测试断言。"""
        return STATUS_COLORS.get(self._state, ("idle", "#5C6470"))[0]


# =====================================================================
# ToastBanner —— 横向通知条
# =====================================================================

# 每种 kind 的左侧小标：全部用几何/文字字符，不用 Emoji 做关键图标。
TOAST_ICONS = {
    "success": "✓",
    "info":    "i",
    "warning": "!",
    "error":   "✕",
}
TOAST_ACCESSIBLE_NAMES = {
    "success": "Success notification",
    "info":    "Information notification",
    "warning": "Warning notification",
    "error":   "Error notification",
}


class ToastBanner(QFrame):
    """横向通知条：非阻断地提示保存成功、网络错误等一次性消息。

    为什么这样设计：
      - 用 QTimer 自动消退：show_message 时先取消旧 timer 再设新 timer，
        避免"旧消息的消退定时器关掉刚弹出的新消息"。
      - 消息 QLabel 开 setWordWrap 并带 tooltip，长错误信息完整可见，不截断 30 字。
      - 本组件只动自己的内容与可见性，绝不修改窗口标题。
      - 颜色由 setProperty("toastRole", kind) 交给 QSS 着色，不同 kind 不同底色。

    用法：win.banner.show_message("已保存截图", kind="success")；
    网络恢复时调用 win.banner.clear() 立即清掉错误提示。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toastBanner")
        self.setAccessibleName("Toast")
        self._kind = "info"

        # 单发定时器：到点自动 clear。每次 show_message 都会重启它。
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.clear)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        self._icon = QLabel(self)
        self._icon.setProperty("textRole", "toastIcon")
        lay.addWidget(self._icon)

        self._message = QLabel(self)
        self._message.setProperty("textRole", "toastText")
        self._message.setWordWrap(True)  # 长错误信息完整显示，不截断
        lay.addWidget(self._message, 1)

        self.hide()  # 初始隐藏，不占布局空间

    def show_message(self, text: str, kind: str = "info",
                     auto_dismiss_ms: int = 4000) -> None:
        """弹出一条通知。kind 取 success/info/warning/error。

        auto_dismiss_ms 传 0 表示不自动消退（等调用方 clear）。
        """
        self._dismiss_timer.stop()  # 取消旧 timer，避免旧消退关掉新消息
        self._kind = kind
        self.setProperty("toastRole", kind)
        _repolish(self)
        self._icon.setText(TOAST_ICONS.get(kind, "i"))
        self._message.setText(text)
        self._message.setToolTip(text)  # 超长时悬停可看全文
        self.setAccessibleName(TOAST_ACCESSIBLE_NAMES.get(
            kind, "Notification"))
        if auto_dismiss_ms > 0:
            self._dismiss_timer.start(auto_dismiss_ms)
        self.show()

    def clear(self) -> None:
        """立即隐藏并清空，同时取消未触发的消退定时器。"""
        self._dismiss_timer.stop()
        self.hide()
        self._message.clear()

    def current_kind(self) -> str:
        return self._kind

    def is_error_visible(self) -> bool:
        """测试/诊断用：当前是否正显示 error 类型通知。"""
        return self._kind == "error" and self.isVisible()


# =====================================================================
# VideoView —— 视频画面区
# =====================================================================

# 占位状态 -> 渲染状态 / 图标 / 主文案 / 副文案。
# 图标全部用几何字符或文字（⏻ 电源符号、↻ 回转箭头、✕ 乘号），
# 不用 Emoji，避免跨平台渲染风格不一致、也避免被当成"表情"。
PLACEHOLDER_CONFIG = {
    "Connecting":   dict(render_state="connecting",
                         icon="⏻", title="正在连接...",
                         sub="正在建立与手机推流的连接"),
    "Idle":         dict(render_state="connecting",
                         icon="⏻", title="等待连接...",
                         sub="请确认手机已在推流"),
    "Reconnecting": dict(render_state="reconnecting",
                         icon="↻", title="视频流已中断",
                         sub="正在自动重连，或点击下方按钮立即重试"),
    "Stopped":      dict(render_state="stopped",
                         icon="⏻", title="已停止",
                         sub="未在接收视频"),
    "Error":        dict(render_state="error",
                         icon="✕", title="连接失败",
                         sub="请检查网络或手机推流状态"),
}


class VideoView(QWidget):
    """视频画面区：实时帧 + 左下角信息浮层 + 居中占位。

    为什么这样设计：
      - 保留原始 QPixmap 在 self._source_pixmap，resize 时总是从原始帧重新等比缩放，
        绝不"反复缩放已缩小的图像"导致清晰度逐级劣化。
      - 占位内容用 Qt 布局真正居中（QLabel 文本 + 按钮），不是 numpy 黑图手绘。
      - 占位内"重新连接"按钮只在 Reconnecting 状态显示，点击 emit reconnect_requested，
        由主窗口连接 AppModel.reconnect()。本组件不持有 AppModel。
      - 背景强制黑色：画面未铺满时四周是黑边，看起来像专业监视器。

    使用：
      view.set_frame(pixmap)                        # 显示实时帧
      view.set_frame_info(w, h, disp_fps)           # 更新左下角信息浮层
      view.set_placeholder("Reconnecting", detail)  # 显示居中占位
      view.reconnect_requested.connect(...)         # 占位按钮点击信号
    """

    reconnect_requested = Signal()

    def __init__(self, parent=None, translator=None):
        super().__init__(parent)
        self.setObjectName("videoView")
        self.setAccessibleName("Video view")
        self.setToolTip("Live video")
        self._source_pixmap = QPixmap()  # 原始帧，缩放始终以此为源
        self._render_state = "stopped"
        # 双语：外部可注入 Translator；未注入时占位文案用 PLACEHOLDER_CONFIG 默认
        self._tr = translator
        self._current_placeholder = None  # 当前占位状态，供语言切换刷新

        # 黑色兜底背景：即使 QSS 未覆盖也保证黑边。QSS 可再覆盖边框圆角等。
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor("#000000"))
        self.setAutoFillBackground(True)
        self.setPalette(pal)

        # 同一 grid 单元格里叠三个孩子：画面 / 信息浮层 / 占位层。
        # 用不同对齐让浮层固定左下角、占位层居中，resize 时由布局自动重排。
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        # ---- 画面层：铺满整格，等比例显示当前帧 ----
        self._frame_label = QLabel(self)
        self._frame_label.setObjectName("videoFrame")
        self._frame_label.setAlignment(Qt.AlignCenter)
        fpal = self._frame_label.palette()
        fpal.setColor(self._frame_label.backgroundRole(), QColor("#000000"))
        self._frame_label.setAutoFillBackground(True)
        self._frame_label.setPalette(fpal)
        grid.addWidget(self._frame_label, 0, 0)

        # ---- 信息浮层：左下角 分辨率 + 显示 FPS ----
        self._info_label = QLabel(self)
        self._info_label.setObjectName("videoInfo")
        self._info_label.setProperty("textRole", "videoInfo")
        info_font = self._info_label.font()
        info_font.setFamily("Consolas")
        self._info_label.setFont(info_font)
        # 半透明深底，保证压在画面上仍可读
        ipal = self._info_label.palette()
        ipal.setColor(self._info_label.backgroundRole(), QColor(0, 0, 0, 170))
        self._info_label.setAutoFillBackground(True)
        self._info_label.setPalette(ipal)
        self._info_label.hide()
        grid.addWidget(self._info_label, 0, 0,
                       Qt.AlignBottom | Qt.AlignLeft)

        # ---- 占位层：居中显示图标 + 主文案 + 副文案 + 重连按钮 ----
        self._placeholder = QFrame(self)
        self._placeholder.setObjectName("videoPlaceholder")
        self._placeholder.setProperty("placeholderRole", "overlay")
        pbox = QVBoxLayout(self._placeholder)
        pbox.setContentsMargins(24, 16, 24, 16)
        pbox.setSpacing(8)
        pbox.setAlignment(Qt.AlignCenter)  # 内容整体居中

        self._placeholder_icon = QLabel(self._placeholder)
        self._placeholder_icon.setProperty("textRole", "placeholderIcon")
        self._placeholder_icon.setAlignment(Qt.AlignCenter)
        icon_font = self._placeholder_icon.font()
        icon_font.setPointSize(30)
        self._placeholder_icon.setFont(icon_font)
        pbox.addWidget(self._placeholder_icon)

        self._placeholder_title = QLabel(self._placeholder)
        self._placeholder_title.setProperty("textRole", "placeholderTitle")
        self._placeholder_title.setAlignment(Qt.AlignCenter)
        title_font = self._placeholder_title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        self._placeholder_title.setFont(title_font)
        pbox.addWidget(self._placeholder_title)

        self._placeholder_sub = QLabel(self._placeholder)
        self._placeholder_sub.setProperty("textRole", "placeholderSub")
        self._placeholder_sub.setAlignment(Qt.AlignCenter)
        self._placeholder_sub.setWordWrap(True)  # 长 detail 完整显示
        pbox.addWidget(self._placeholder_sub)

        # 重新连接按钮：仅 Reconnecting 占位显示；点击 emit 信号，由主窗口去重连。
        self._reconnect_btn = QPushButton("Reconnect", self._placeholder)
        self._reconnect_btn.setObjectName("videoReconnectButton")
        self._reconnect_btn.setProperty("buttonRole", "ghost")
        self._reconnect_btn.setToolTip("Reconnect now")
        self._reconnect_btn.clicked.connect(
            lambda: self.reconnect_requested.emit())
        pbox.addWidget(self._reconnect_btn, 0, Qt.AlignCenter)

        grid.addWidget(self._placeholder, 0, 0, Qt.AlignCenter)
        self._placeholder.hide()
        # 保证叠放顺序：占位层、信息浮层压在画面层之上
        self._placeholder.raise_()
        self._info_label.raise_()

    # ---- 对外接口 ----

    def set_frame(self, pixmap: QPixmap) -> None:
        """显示一帧实时画面：记住原始图，切到 frame 渲染态并立即按当前尺寸缩放。"""
        self._source_pixmap = pixmap
        self._render_state = "frame"
        self._placeholder.hide()
        self._info_label.show()
        self._update_frame_scaling()

    def set_frame_info(self, width: int, height: int, disp_fps: float) -> None:
        """更新左下角信息浮层：分辨率 + 显示 FPS。"""
        self._info_label.setText(f"{width}x{height}   {disp_fps:.1f} FPS")

    def set_placeholder(self, state: str, detail: str = "") -> None:
        """切换为居中占位。state 取 Connecting/Reconnecting/Stopped/Error（Idle 亦可）。

        detail 非空时覆盖副文案（如具体错误原因）。
        """
        cfg = PLACEHOLDER_CONFIG.get(state, PLACEHOLDER_CONFIG["Connecting"])
        self._render_state = cfg["render_state"]
        self._placeholder_icon.setText(cfg["icon"])
        self._current_placeholder = state
        title, sub = self._placeholder_texts(state, cfg, detail)
        self._placeholder_title.setText(title)
        self._placeholder_sub.setText(sub)
        # 只有 Reconnecting 占位显示重连按钮
        self._reconnect_btn.setVisible(state == "Reconnecting")
        self._frame_label.setPixmap(QPixmap())  # 清掉旧帧，背后只留黑
        self._info_label.hide()
        self._placeholder.show()
        self._placeholder.raise_()

    def _placeholder_texts(self, state, cfg, detail=""):
        """返回 (title, sub) 占位文案；有 Translator 时走双语，否则用默认。"""
        if self._tr is None:
            return cfg["title"], (detail or cfg["sub"])
        key_map = {
            "Connecting": ("placeholder_connecting", "placeholder_connecting_sub"),
            "Idle": ("placeholder_connecting", "placeholder_connecting_sub"),
            "Reconnecting": ("placeholder_reconnecting", "placeholder_reconnecting_sub"),
            "Stopped": ("placeholder_stopped", "placeholder_stopped_sub"),
            "Error": ("placeholder_error", "placeholder_error_sub"),
        }
        t_key, s_key = key_map.get(state, ("placeholder_connecting",
                                           "placeholder_connecting_sub"))
        title = self._tr.text(t_key)
        sub = detail or self._tr.text(s_key)
        return title, sub

    def _apply_language(self) -> None:
        """语言切换时刷新占位文案（保持当前占位状态）。"""
        if self._current_placeholder is not None:
            state = self._current_placeholder
            cfg = PLACEHOLDER_CONFIG.get(state, PLACEHOLDER_CONFIG["Connecting"])
            title, sub = self._placeholder_texts(state, cfg)
            self._placeholder_title.setText(title)
            self._placeholder_sub.setText(sub)

    @property
    def render_state(self) -> str:
        """当前渲染状态："frame"/"connecting"/"reconnecting"/"stopped"/"error"。"""
        return self._render_state

    def pixmap(self) -> QPixmap:
        """兼容旧接口：返回当前显示的帧 QPixmap（占位时返回空）。

        旧代码/测试用 video_view.pixmap() 判断画面内容；现在画面在内部
        _frame_label 上，这里转发过去，避免破坏既有测试。
        """
        return self._frame_label.pixmap() or QPixmap()

    # ---- 内部 ----

    def _update_frame_scaling(self) -> None:
        """从原始图 self._source_pixmap 重新等比缩放，始终以原始帧为源。

        这样 resize 后画面不会因为"基于上次缩小结果再缩小"而越来越糊。
        """
        if self._source_pixmap.isNull():
            return
        target = self._frame_label.size()
        if target.width() <= 0 or target.height() <= 0:
            return  # 还没布局（未 show），等 resizeEvent 再来
        scaled = self._source_pixmap.scaled(
            target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._frame_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._render_state == "frame":
            self._update_frame_scaling()


# =====================================================================
# DiagnosticsPanel —— 诊断面板
# =====================================================================

# (显示名默认, values 键, 中文 tooltip, i18n 标签 key, i18n tooltip key)。
# resolution 由 width/height 合成，不单独入键。
MAIN_METRICS = [
    ("接收FPS", "recv_fps", "PC实际接收速率", "metric_recv_fps", "tip_recv_fps"),
    ("显示FPS", "disp_fps", "实际显示的新画面频率", "metric_disp_fps", "tip_disp_fps"),
    ("丢帧", "dropped", "手机发出但电脑没收到的帧", "metric_dropped", "tip_dropped"),
]
EXTRA_METRICS = [
    ("采集FPS", "phone_fps", "手机端采集帧率（来自 /ping）", "metric_phone_fps", "tip_phone_fps"),
    ("带宽Mbps", "mbps", "网络吞吐，反映推流带宽占用", "metric_mbps", "tip_mbps"),
    ("平均JPEG", "avg_jpeg_mb", "每帧 JPEG 平均大小", "metric_avg_jpeg", "tip_avg_jpeg"),
    ("接收帧", "received", "已成功解析的帧总数", "metric_received", "tip_received"),
    ("无效帧", "invalid", "损坏或无法解析的帧数", "metric_invalid", "tip_invalid"),
    ("分辨率", "resolution", "视频画面宽x高", "metric_resolution", "tip_resolution"),
]


class DiagnosticsPanel(QWidget):
    """诊断面板：默认只显示接收FPS/显示FPS/丢帧三个主要指标，展开才显示其余。

    为什么这样设计：
      - 不是十个同权 chip 排一排：默认只突出三项（丢帧弱化显示），
        需要深挖时点"展开诊断"看采集FPS/带宽/JPEG/帧计数/分辨率。
      - 每项：上方小标签 + 下方等宽数值，都带中文 tooltip 解释含义。
      - 数值更新走 update_values(values)，键与 AppSnapshot 字段一一对应，
        主窗口把快照字典喂进来即可。

    使用：
      panel.update_values({"recv_fps": 15.0, "disp_fps": 14.2, "dropped": 3, ...})
      panel.toggle() / panel.set_expanded(True)
    """

    def __init__(self, parent=None, translator=None):
        super().__init__(parent)
        self.setObjectName("diagnosticsPanel")
        self.setAccessibleName("诊断面板")
        self._tr = translator
        self._expanded = False
        self._value_labels: dict[str, QLabel] = {}
        self._extra_cells: list[QWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # ---- 标题行：标题 + 展开/收起切换按钮 ----
        header = QHBoxLayout()
        self._title_label = QLabel()
        self._title_label.setProperty("textRole", "groupTitle")
        header.addWidget(self._title_label)
        header.addStretch(1)
        self._toggle_btn = QPushButton()
        self._toggle_btn.setObjectName("diagnosticsToggleButton")
        self._toggle_btn.setProperty("buttonRole", "ghost")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.clicked.connect(self.toggle)
        header.addWidget(self._toggle_btn)
        outer.addLayout(header)

        # ---- 指标网格：3 列。第 0 行主指标常显，1~2 行展开项 ----
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)

        for col, (label, key, tip, lk, tk) in enumerate(MAIN_METRICS):
            cell = self._make_metric_cell(label, key, tip, lk, tk,
                                          weak=(key == "dropped"))
            grid.addWidget(cell, 0, col)

        for i, (label, key, tip, lk, tk) in enumerate(EXTRA_METRICS):
            row, col = divmod(i, 3)
            cell = self._make_metric_cell(label, key, tip, lk, tk)
            grid.addWidget(cell, row + 1, col)
            self._extra_cells.append(cell)

        outer.addLayout(grid)

        self.set_expanded(False)

    # ---- 对外接口 ----

    def update_values(self, values: dict) -> None:
        """用一组值刷新指标。values 键：recv_fps/disp_fps/dropped/phone_fps/
        mbps/avg_jpeg_mb/received/invalid/width/height。缺失的键保持 "--"。
        """
        for key, val in values.items():
            if key in ("width", "height"):
                continue  # 分辨率由 width/height 合成，单独处理
            label = self._value_labels.get(key)
            if label is None:
                continue
            label.setText(self._format_value(key, val))
        # 分辨率：width/height 都给了才合成
        if "width" in values and "height" in values:
            self._value_labels["resolution"].setText(
                f"{int(values['width'])}x{int(values['height'])}")

    def items(self) -> list:
        """测试用 items()：返回 [(键, 数值QLabel), ...] 对列表（类似 dict.items()）。

        同一数值 QLabel 只出现一次（别名优先），避免测试数可见项时重复计数。
        """
        seen = set()
        out = []
        for k, v in self._value_labels.items():
            alias = {"recv_fps": "recv", "disp_fps": "disp",
                     "phone_fps": "phone", "avg_jpeg_mb": "jpeg"}.get(k, k)
            key = alias if alias in ("recv", "disp", "phone", "jpeg") else k
            if id(v) in seen:
                continue
            seen.add(id(v))
            out.append((key, v))
        return out

    def set_expanded(self, expanded: bool) -> None:
        """展开/收起扩展指标，并同步切换按钮文字与选中态。"""
        self._expanded = bool(expanded)
        for cell in self._extra_cells:
            cell.setVisible(self._expanded)
        self._toggle_btn.setChecked(self._expanded)
        self._update_toggle_text()

    def _update_toggle_text(self) -> None:
        if self._tr:
            key = "diag_collapse" if self._expanded else "diag_expand"
            self._toggle_btn.setText(self._tr.text(key))
        else:
            self._toggle_btn.setText("收起诊断" if self._expanded else "展开诊断")

    def _apply_language(self) -> None:
        """语言切换时刷新标题、展开按钮和全部指标标签/tooltip。"""
        if self._tr:
            self._title_label.setText(self._tr.text("diag_title"))
            self._update_toggle_text()
            for label, key, tip, lk, tk in (MAIN_METRICS + EXTRA_METRICS):
                cell = self._value_labels[key].parentWidget()
                if cell is None:
                    continue
                tl = self._tr.text(lk)
                tt = self._tr.text(tk)
                # 更新标签（cell 第一个 QLabel 是标签）
                for w in cell.findChildren(QLabel):
                    if w.property("textRole") == "metricLabel":
                        w.setText(tl)
                        w.setToolTip(tt)
                cell.setToolTip(tt)
                self._value_labels[key].setToolTip(tt)

    def is_expanded(self) -> bool:
        return self._expanded

    def toggle(self) -> None:
        """反转展开状态。"""
        self.set_expanded(not self._expanded)

    # ---- 内部 ----

    def _make_metric_cell(self, label: str, key: str, tip: str,
                          label_key: str, tip_key: str,
                          weak: bool = False) -> QWidget:
        """构造一个"小标签在上 + 等宽数值在下"的指标格，并登记数值 QLabel。

        label_key/tip_key 是 i18n 字典 key；有 Translator 时用翻译，否则用
        label/tip 默认值。
        """
        cell = QWidget(self)
        cell.setProperty("metricRole", "cell")
        text_label = self._tr.text(label_key) if self._tr else label
        text_tip = self._tr.text(tip_key) if self._tr else tip
        cell.setToolTip(text_tip)
        box = QVBoxLayout(cell)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)

        lab = QLabel(text_label)
        lab.setProperty("textRole", "metricLabel")
        lab.setToolTip(text_tip)
        box.addWidget(lab)

        val = QLabel("--")
        # weak=True 表示"弱化"指标（如丢帧）：用不同 valueRole 让 QSS 调暗一点，
        # 视觉上不抢主要指标的注意力。
        val.setProperty("valueRole", "weak" if weak else "value")
        val.setToolTip(text_tip)
        font = val.font()
        font.setFamily("Consolas")  # 等宽数值，数字跳动时更稳
        val.setFont(font)
        box.addWidget(val)

        self._value_labels[key] = val
        return cell

    @staticmethod
    def _format_value(key: str, val) -> str:
        """按指标类型格式化数值；缺省/非法值显示 "--"。"""
        if val is None:
            return "--"
        try:
            num = float(val)
        except (TypeError, ValueError):
            return str(val)
        if key in ("recv_fps", "disp_fps", "phone_fps"):
            return f"{num:.1f}"
        if key == "avg_jpeg_mb":
            return f"{num:.2f}MB"
        if key == "mbps":
            return f"{num:.1f}"
        if key in ("dropped", "received", "invalid"):
            return f"{int(num)}"
        return str(val)
