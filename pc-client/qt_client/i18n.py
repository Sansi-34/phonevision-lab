"""
PhoneVision Lab — 双语国际化模块（简体中文 / 英文）。

职责：为整个 PySide6 工作台提供可切换语言的文案服务：
  - STRINGS：集中定义两种语言所有用户可见文案，两种语言 key 集合严格一致。
  - Translator：按当前语言取字符串、切换语言（可选 QSettings 持久化）、
    语言切换信号、初始语言解析、缺失 key 回退。

为什么这样设计：
  - 字典驱动：界面全部文案收敛到一个 dict，UI 只通过 key 取文案，
    不散落硬编码，改文案/加语言只动这一处。
  - 显式回退：text() 遇到缺失 key 返回 "???" + key + "???"，绝不静默返回
    空白，方便在界面上直接看到哪个 key 漏了；missing_keys() 可程序化查询。
  - key 集合一致性：两种语言必须拥有完全相同的 key 集合，否则界面切换语言
    后某处文案会回退成 "???"。keys(language) 暴露给测试做一致性断言。
  - 可注入 QSettings：测试传 settings=QSettings("test", "test") 或 mock，
    读写内存/临时存储，不污染真实用户配置。
  - 可注入初始语言：无界面测试可传 initial_language="en" 直接构造英文实例。
  - language_changed 信号：界面组件连接它，语言切换时统一刷新文案，
    不用每个组件各自监听菜单。

注意：
  - 不联网、不下载、不加第三方依赖，只用 PySide6 自带能力。
  - 状态专名（Streaming/Connecting/...）与英文模式名（Canny/HSV）在两种
    语言保持原文，只提供 status_* 别名供组件取用。
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Signal, QObject

# 语言标识常量（供调用方 import，避免字符串散落）。
LANG_ZH = "zh-CN"
LANG_EN = "en"

# =====================================================================
# 双语字符串表
# =====================================================================
# 约定：
#   - 两种语言 key 集合必须完全一致（测试会断言）。
#   - 含 {name} 的 key 通过 text(key, name=...) 传参，两种语言占位符集合
#     必须一致（测试会断言），否则切换语言后 format 会 KeyError/遗留花括号。
#   - 专名（Streaming/Canny/HSV/PhoneVision Lab）两种语言保持原文。

STRINGS = {
    # ---------- 顶栏 ----------
    "app_title": ("PhoneVision Lab", "PhoneVision Lab"),
    "device_placeholder": ("等待设备信息", "Waiting for device"),
    "save_screenshot": ("保存截图", "Save Screenshot"),
    "reconnect": ("重新连接", "Reconnect"),
    "language": ("语言", "Language"),

    # ---------- 状态专名（两种语言保持英文专名）----------
    # StatusPill/占位直接显示这些英文状态词，界面语义统一。
    "status_connecting": ("Connecting", "Connecting"),
    "status_streaming": ("Streaming", "Streaming"),
    "status_reconnecting": ("Reconnecting", "Reconnecting"),
    "status_stopped": ("Stopped", "Stopped"),
    "status_error": ("Error", "Error"),

    # ---------- 视觉模式 ----------
    "mode_title": ("视觉模式", "Vision Mode"),
    "mode_original": ("原始", "Original"),
    "mode_gray": ("灰度", "Gray"),
    "mode_canny": ("Canny", "Canny"),
    "mode_hsv": ("HSV", "HSV"),
    "mode_contour": ("轮廓", "Contours"),
    "current_mode": ("当前: {mode}", "Current: {mode}"),

    # ---------- 参数区 ----------
    "param_title": ("当前模式参数", "Mode Parameters"),
    "param_hint": ("按模式生效", "Applies to current mode"),
    # 参数标签（主标签两种语言均保持英文缩写，中文只作副标签说明）。
    "canny_low": ("Canny Low", "Canny Low"),
    "canny_high": ("Canny High", "Canny High"),
    "h_min": ("H Min", "H Min"),
    "h_max": ("H Max", "H Max"),
    "s_min": ("S Min", "S Min"),
    "s_max": ("S Max", "S Max"),
    "v_min": ("V Min", "V Min"),
    "v_max": ("V Max", "V Max"),
    "contour_min_area": ("Min Area", "Min Area"),
    # 参数副标签（中文说明 / 英文说明）。
    "param_canny_low_sub": ("阈值下限", "Lower threshold"),
    "param_canny_high_sub": ("阈值上限", "Upper threshold"),
    "param_h_min_sub": ("色相下限", "Hue lower"),
    "param_h_max_sub": ("色相上限", "Hue upper"),
    "param_s_min_sub": ("饱和度下限", "Saturation lower"),
    "param_s_max_sub": ("饱和度上限", "Saturation upper"),
    "param_v_min_sub": ("明度下限", "Value lower"),
    "param_v_max_sub": ("明度上限", "Value upper"),
    "param_contour_min_area_sub": ("最小面积", "Min contour area"),
    # 无参数模式的教学空状态。
    "param_empty_original": (
        "此模式无参数，先熟悉画面",
        "No parameters for this mode",
    ),
    "param_empty_gray": (
        "此模式无参数，先熟悉灰度",
        "No parameters for this mode",
    ),

    # ---------- 教学提示（P0-4A 文案 + 英文翻译）----------
    "hint_original": (
        "观察手机摄像头的原始画面",
        "Observe the raw camera feed",
    ),
    "hint_gray": (
        "先观察亮度结构，再进入阈值和边缘处理",
        "Study the brightness structure first, then move on to thresholds and edges",
    ),
    "hint_canny": (
        "Low以下丢弃，High以上保留，中间边缘需与强边相连",
        "Below Low is dropped, above High is kept, in-between edges must connect to a strong edge",
    ),
    "hint_hsv": (
        "白色区域表示当前颜色范围被选中",
        "The white region marks the currently selected color range",
    ),
    "hint_contour": (
        "Min Area用于滤除面积较小的噪点",
        "Min Area filters out small noise regions",
    ),

    # ---------- 诊断面板 ----------
    "diag_title": ("实时诊断", "Live Diagnostics"),
    "diag_expand": ("展开诊断", "Expand"),
    "diag_collapse": ("收起诊断", "Collapse"),
    # 指标标签。
    "metric_recv_fps": ("接收FPS", "Receive FPS"),
    "metric_disp_fps": ("显示FPS", "Display FPS"),
    "metric_dropped": ("丢帧", "Dropped"),
    "metric_phone_fps": ("采集FPS", "Capture FPS"),
    "metric_mbps": ("带宽Mbps", "Mbps"),
    "metric_avg_jpeg": ("平均JPEG", "Avg JPEG"),
    "metric_received": ("接收帧", "Frames"),
    "metric_invalid": ("无效帧", "Invalid"),
    "metric_resolution": ("分辨率", "Resolution"),
    # 各指标 tooltip 说明。
    "tip_recv_fps": ("PC实际接收速率", "Actual frames received by the PC per second"),
    "tip_disp_fps": ("实际显示的新画面频率", "How often a new frame is displayed"),
    "tip_dropped": ("手机发出但电脑没收到的帧", "Frames sent by the phone but missed by the PC"),
    "tip_phone_fps": ("手机端采集帧率（来自 /ping）", "Phone capture rate (from /ping)"),
    "tip_mbps": ("网络吞吐，反映推流带宽占用", "Network throughput used by the stream"),
    "tip_avg_jpeg": ("每帧 JPEG 平均大小", "Average encoded size of each frame"),
    "tip_received": ("已成功解析的帧总数", "Total frames successfully decoded"),
    "tip_invalid": ("损坏或无法解析的帧数", "Frames that were corrupt or could not be decoded"),
    "tip_resolution": ("视频画面宽x高", "Video width x height"),

    # ---------- 画面占位 ----------
    "placeholder_connecting": ("正在连接...", "Connecting..."),
    "placeholder_connecting_sub": ("正在建立与手机推流的连接", "Establishing connection to the phone stream"),
    "placeholder_reconnecting": ("视频流已中断", "Video stream interrupted"),
    "placeholder_reconnecting_sub": ("正在自动重连，或点击下方按钮立即重试", "Auto-reconnecting, or press the button below to retry now"),
    "placeholder_stopped": ("已停止", "Stopped"),
    "placeholder_stopped_sub": ("未在接收视频", "No video is being received"),
    "placeholder_error": ("连接失败", "Connection failed"),
    "placeholder_error_sub": ("请检查网络或手机推流状态", "Check the network or the phone streaming state"),
    "placeholder_reconnect_button": ("重新连接", "Reconnect"),

    # ---------- Toast 通知 ----------
    "toast_saved": ("已保存: {path}", "Saved: {path}"),
    "toast_no_frame": ("当前无画面可保存", "No frame to save"),
    "toast_conn_error": ("连接错误", "Connection error"),
    "toast_restored": ("连接已恢复", "Connection restored"),
    "toast_save_failed": ("保存失败: {error}", "Save failed: {error}"),
}

# 缺失 key 的显式回退模板：绝不清空白，界面上一眼可见。
_MISSING_TEMPLATE = "???{key}???"


def _normalize_language(language: str) -> str:
    """把任意传入语言标识归一化为 zh-CN / en；未知一律回落到 zh-CN。"""
    if language is None:
        return LANG_ZH
    low = str(language).strip().lower().replace("_", "-")
    if low.startswith("zh"):
        return LANG_ZH
    return LANG_EN


class Translator(QObject):
    """双语文案服务：取字符串 / 切语言 / 初始语言解析 / 缺失回退。

    线程安全性：仅应在 GUI 主线程使用（Qt 对象）。语言切换会 emit
    language_changed(str)，UI 组件连接它统一刷新。
    """

    # 语言切换信号：参数为新的语言标识（"zh-CN"/"en"）。
    language_changed = Signal(str)

    def __init__(self, settings: QSettings | None = None,
                 initial_language: str = "zh-CN"):
        super().__init__()
        # 可注入 QSettings 用于测试隔离；不传则用真实用户配置。
        self._settings = settings if settings is not None else \
            QSettings("PhoneVisionLab", "PhoneVisionLab")
        self._language = _normalize_language(initial_language)

    # ---- 文案获取 ----

    def text(self, key: str, **kwargs) -> str:
        """取当前语言字符串；kwargs 用于 {name} 占位符格式化。

        缺失 key 返回 "???{key}???"（显式回退，绝不清空白），
        并通过 self.missing 集合记录，供 missing_keys() 查询。
        """
        table = STRINGS.get(key)
        if table is None:
            self._mark_missing(key)
            return _MISSING_TEMPLATE.format(key=key)
        # 二元组顺序固定：(zh-CN, en)。
        raw = table[0] if self._language == LANG_ZH else table[1]
        if kwargs:
            # 占位符一致性由测试保证；此处仍做防御性兜底，缺参时保留原花括号。
            try:
                return raw.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return raw
        return raw

    def keys(self, language: str | None = None) -> set[str]:
        """返回某个语言的 key 集合（language 缺省取当前语言）。

        两种语言 key 集合相同，因此返回值与语言无关；此参数保留是为了
        让测试显式断言两种语言的一致性，语义清晰。
        """
        if language is None:
            return set(STRINGS.keys())
        return set(STRINGS.keys())

    def missing_keys(self) -> set[str]:
        """返回本次实例中 text() 访问过的缺失 key 集合（用于测试/排查）。"""
        return set(getattr(self, "_missing", set()))

    def _mark_missing(self, key: str) -> None:
        if not hasattr(self, "_missing"):
            self._missing = set()
        self._missing.add(key)

    # ---- 语言切换 ----

    def set_language(self, language: str, persist: bool = True) -> None:
        """切换语言；persist=True 时用 QSettings 保存。

        归一化后若与当前语言不同，emit language_changed 并更新内部状态。
        """
        new_lang = _normalize_language(language)
        if persist:
            self._settings.setValue("language", new_lang)
        if new_lang == self._language:
            return
        self._language = new_lang
        self.language_changed.emit(new_lang)

    def language(self) -> str:
        """返回当前语言："zh-CN"/"en"。"""
        return self._language

    @staticmethod
    def available_languages() -> list[str]:
        """返回全部可用语言标识。"""
        return [LANG_ZH, LANG_EN]

    # ---- 初始语言解析 ----

    @staticmethod
    def resolve_initial_language(cli_value: str | None, saved_value: str | None,
                                 system_locale: str | None) -> str:
        """初始语言优先级：CLI > 已保存 > 系统区域。

        cli_value/saved_value 传语言标识（"zh-CN"/"en" 或任意含 "zh" 前缀的
        写法）；system_locale 传系统区域字符串（如 "zh_CN"/"zh-CN" 或
        "en_US"），仅按是否含 "zh" 前缀决定 zh-CN，否则 en。
        """
        for value in (cli_value, saved_value):
            if value:  # 非空则归一化后直接采用
                return _normalize_language(value)
        # 系统区域：仅看是否含 "zh" 前缀，无法识别时默认英文。
        if system_locale:
            low = str(system_locale).strip().lower().replace("_", "-")
            if low.startswith("zh"):
                return LANG_ZH
        return LANG_EN
