"""
PhoneVision Lab — 应用版本（唯一来源）。

职责：集中定义应用版本号与程序名，供运行时（about / 日志 / 窗口标题）与
打包脚本（Version resource、产物命名、build-info）共用，避免版本号散落多处。

约定：
  - 本项目只有一个版本事实来源：本文件的 __version__。
  - 改动版本只改本文件，其余一律 import 这里。
"""
from __future__ import annotations

# 唯一版本事实来源（语义化版本，可能含 -alpha/-beta 等预发布后缀）。
__version__ = "0.1.0-alpha.1"

# 完整版本字符串（同 __version__，用于日志与显示）。
VERSION_STR = __version__

# Windows 数字版本（用于 PE 文件版本资源 / ProductVersion 等）。
#
# 说明：Windows 文件版本只接受数字点分四元组（major.minor.build.revision），
# 语义化版本里的预发布后缀（"-alpha.1"）不合法。这里把 0.1.0-alpha.1 映射为
# 0.1.0.1：前三段对应 0.1.0，第四段取预发布编号 1。正式版 0.1.0 则映射为
# 0.1.0.0。此映射只影响 PE 版本资源，不改变 __version__ 语义。
VERSION_TUPLE = (0, 1, 0, 1)

# 应用显示名（窗口标题 / 安装产物 / 包内说明统一使用）。
APP_NAME = "PhoneVision Lab"

# 短程序名：用于生成可执行文件名 / ZIP 前缀 / 配置文件目录名（避免空格）。
APP_SLUG = "PhoneVisionLab"


def get_version_str() -> str:
    """返回语义化版本字符串（等价于 __version__，供显式调用）。"""
    return VERSION_STR


def get_version_tuple() -> tuple[int, int, int, int]:
    """返回 Windows 数字版本四元组 (major, minor, build, revision)。"""
    return VERSION_TUPLE
