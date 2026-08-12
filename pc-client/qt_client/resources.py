"""
PhoneVision Lab — 资源路径解析（源码 / PyInstaller frozen 通用）。

职责：统一解决"打包后资源在哪、用户数据写在哪个目录"两个问题：
  - 打包资源（style.qss、图标）：frozen 时在 sys._MEIPASS 下的 qt_client/
    子目录（与源码 qt_client/ 布局镜像，见 packaging/PhoneVisionLab.spec），
    源码时在 qt_client/ 包目录。
  - 用户数据（日志、最近连接配置）：用 Qt 的 QStandardPaths 定位"应用本地
    数据目录"，不硬编码 Windows 路径，源码与 frozen 行为一致。

资源解析方式（文档）：
  1. 打包资源通过 resource_path() 解析。frozen（PyInstaller）时基于
     sys._MEIPASS + qt_client/；源码时基于本文件 __file__ 所在目录（qt_client/）。
  2. 用户数据目录通过 app_data_dir() 解析，基于
     QStandardPaths.AppLocalDataLocation（%LOCALAPPDATA%/<Org>/<App>）。
     要求：调用前 QApplication 已创建；若在无 QApplication 的极早期调用，
     自动回退到源码目录下 .appdata 子目录，绝不抛异常。
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QCoreApplication, QStandardPaths

from qt_client.version import APP_NAME

# 本包目录（源码布局下资源所在位置）：qt_client/
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(relative: str) -> str:
    """返回打包资源（style.qss / 图标等）的绝对路径。

    frozen（PyInstaller）时资源在 sys._MEIPASS 下，且保持与源码包一致的
    相对布局（style.qss 与 assets/ 都放在 bundle 的 qt_client/ 下，与源码
    qt_client/ 目录镜像，见 packaging/PhoneVisionLab.spec 的 datas）；
    源码时在 qt_client/ 包目录下。relative 用相对路径（如 "style.qss"、
    "assets/app.png"），禁止以 "D:\\" 等绝对路径开头。
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", "")
        return os.path.join(base, "qt_client", relative)
    return os.path.join(_PKG_DIR, relative)


def style_qss_path() -> str:
    """返回 style.qss 的绝对路径（给 QApplication.setStyleSheet 用）。"""
    return resource_path("style.qss")


def icon_path() -> str:
    """返回应用图标的绝对路径。

    返回包装内实际使用的 PNG（Windows 任务栏/Alt+Tab 用 PNG 即可清晰显示）；
    生成 EXE 图标的 ICO 由打包脚本从 assets/ 取用。
    """
    return resource_path(os.path.join("assets", "app.png"))


def app_data_dir() -> str:
    """返回应用本地数据目录（日志、最近连接等用户数据写入处）。

    基于 QStandardPaths.AppLocalDataLocation（Windows 通常为
    %LOCALAPPDATA%/<Org>/<App>；Qt 会按已设置的 Organization/Application
    名拼完整路径）。目录不存在时自动创建。
    若目录创建失败（只读/异常环境），返回 None，调用方必须能容忍 None。
    """
    # QStandardPaths 需要 QCoreApplication 已存在；极早期（应用对象创建前）
    # 调用会定位到解释器名拼的路径，回退到源码目录下的 .appdata，保证
    # 日志/配置写入永不因调用时机崩溃。
    try:
        if QCoreApplication.instance() is None:
            fallback = os.path.join(_PKG_DIR, ".appdata")
            os.makedirs(fallback, exist_ok=True)
            return fallback
        base = QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation)
        if not base:
            return None
        os.makedirs(base, exist_ok=True)
        return base
    except Exception:  # noqa: BLE001 - 定位失败绝不能拖垮启动
        return None


def logs_dir() -> str:
    """返回日志目录绝对路径；无法定位时返回 None（调用方容忍）。"""
    data = app_data_dir()
    if not data:
        return None
    try:
        path = os.path.join(data, "logs")
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:  # noqa: BLE001
        return None
