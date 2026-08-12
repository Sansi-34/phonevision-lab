"""
PhoneVision Lab — 字体选择模块。

职责：根据界面语言选择合适字体族，并处理中文字形缺失问题：
  - select_ui_font：从候选字体里选第一个实际存在的字体族。
  - check_chinese_glyph_support：验证某字体族能否渲染中文字符（防方框字）。
  - apply_application_font：把选定的字体设为全局 QApplication 字体。

为什么这样设计：
  - Windows 上 Segoe UI 无中文字形，中文界面若强制 Segoe UI 会显示"方框字"
    （style.qss 默认 font-family: "Segoe UI", "Microsoft YaHei UI" 之所以能
    正常显示中文，是因为 QSS 给了 YaHei 兜底）。这里在语言层面显式决策：
    zh-CN 优先 YaHei，en 优先 Segoe UI。
  - 数字部分由 QSS 的 Consolas 覆盖（等宽数字），与本模块选定的全局字体
    不冲突：QSS 优先级高于 QApplication.setFont。
  - 不做字体下载、不联网、不加第三方依赖；只在系统已装字体中挑选。

注意：
  - select_ui_font 需要传入 QFontDatabase.families() 的结果（一次系统查询，
    调用方缓存即可），纯函数易测试。
  - check_chinese_glyph_support 需要 QApplication 已存在（QFontMetrics 依赖
    字体数据库）；测试可用 QT_QPA_PLATFORM=offscreen 创建 QApplication。
"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics

# 中文字体候选（按优先级）：首个在系统存在的被选中。
# 末尾的 "Segoe UI" 作为系统默认 UI 兜底（Windows 必装，保证返回值非空）。
CHINESE_FONT_CANDIDATES = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "PingFang SC",
    "Segoe UI",
]

# 英文字体：优先 Segoe UI（Windows 默认 UI 字体），否则交给系统默认。
ENGLISH_FONT_CANDIDATES = ["Segoe UI"]


def select_ui_font(language: str, installed_families: list[str] | set[str]) -> str | None:
    """按语言从候选字体里选第一个实际安装的字体族名。

    参数：
      language           语言标识（"zh-CN"/"en"，其余按英文处理）。
      installed_families QFontDatabase.families() 的结果（list 或 set）。

    返回：
      选中的字体族名（str）；候选全部不存在时返回 None。
    """
    candidates = (CHINESE_FONT_CANDIDATES if str(language).startswith("zh")
                  else ENGLISH_FONT_CANDIDATES)
    installed = set(installed_families)
    for family in candidates:
        if family in installed:
            return family
    return None


def check_chinese_glyph_support(font_family: str, sample_text: str = "视觉模式") -> bool:
    """验证某字体族能否渲染 sample_text 中所有字符（防方框字）。

    两层检查：
      1. QFontDatabase 确认字体族确实存在；
      2. 用 QFontMetrics.inFontUcs4 逐一确认每个字符在该字体都有字形。

    需要 QApplication 已创建（QFontMetrics 依赖系统字体数据库）。
    任一字符缺失字形即返回 False，保证返回 True 时整段中文都能显示。
    """
    families = QFontDatabase.families()
    if font_family not in families:
        return False
    # inFontUcs4 需要具体字号构造的 QFontMetrics；字号不影响字形判断。
    font = QFont(font_family, 10)
    metrics = QFontMetrics(font)
    return all(
        metrics.inFontUcs4(ord(ch))
        for ch in sample_text
    )


def apply_application_font(app, language: str) -> str | None:
    """按语言设置全局字体（QApplication.setFont），返回实际使用的字体族名。

    zh-CN 优先 YaHei 等中文字体；en 优先 Segoe UI。数字部分由 style.qss 的
    Consolas 覆盖，与本设置不冲突。
    若候选全部不存在（几乎不可能），不修改字体并返回 None。
    """
    family = select_ui_font(language, QFontDatabase.families())
    if family is None:
        return None
    app.setFont(QFont(family, 10))
    return family
