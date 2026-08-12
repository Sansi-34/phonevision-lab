# -*- mode: python ; coding: utf-8 -*-
# =====================================================================
# PhoneVision Lab — PyInstaller onedir spec (Windows x64 便携打包)
#
# 用法（由 build_windows.ps1 调用，通常不手工运行）：
#   pyinstaller --noconfirm --clean packaging/PhoneVisionLab.spec
#
# 设计要点：
#   - onedir（目录形态）：比 onefile 启动快、便于增量更新与杀软友好。
#   - console=False：windowed EXE，双击不弹终端。
#   - 不盲目 collect 整个 PySide6：PySide6 6.x 自带官方 hook
#     （pyinstaller-hooks-contrib），会自动收集用到的 Qt 库与插件；
#     运行期若报缺插件（如 imageformats），等构建 warnings 后再按
#     需补充 hiddenimports / collect，不要无脑全量打包。
#   - 本 spec 不含任何本机绝对路径：一切用相对路径 + sys.path 推导。
#     SPECPATH 由 PyInstaller 注入为本文件所在目录（packaging/）。
#
# 注意：PyInstaller 在本仓库开发机上未安装（由 build_windows.ps1 在干净
# venv 内安装），因此本 spec 在提交时未经本地运行验证。语法基于
# PyInstaller 6.x 标准 spec API，构建时若遇 warnings 在此补充。
# =====================================================================

import os
import sys

# --- 路径推导（全部相对，无本机绝对路径）-------------------------------
# SPECPATH = packaging/ 目录（PyInstaller 注入）。
_HERE = os.path.abspath(SPECPATH)
# pc-client 根目录 = packaging/ 的上一级。
_PC_CLIENT = os.path.dirname(_HERE)
# qt_client 包目录。
_QT_CLIENT = os.path.join(_PC_CLIENT, "qt_client")
# 打包资源目录。
_PKG = os.path.join(_HERE, "assets")

# 让 import 能解析 pc-client 根目录下的模块（version.py 等）。
sys.path.insert(0, _PC_CLIENT)

from qt_client.version import APP_NAME, APP_SLUG, VERSION_STR, VERSION_TUPLE  # noqa: E402

# --- 产物命名 -----------------------------------------------------------
_dist_dir = os.path.join(_PC_CLIENT, "dist")
_build_dir = os.path.join(_PC_CLIENT, "build")
_name = APP_SLUG  # PhoneVisionLab（无空格）

# --- 需要随包携带的数据文件（相对路径，PyInstaller 以 SPECPATH 为基准）--
_datas = [
    # QSS 主题：运行时由 resources.style_qss_path() 解析。
    (os.path.join(_QT_CLIENT, "style.qss"), "qt_client"),
    # 应用图标 PNG（任务栏/Alt+Tab 用）：运行时由 resources.icon_path() 解析。
    (os.path.join(_PKG, "app.png"), os.path.join("qt_client", "assets")),
]

# --- 图标（EXE 图标，PyInstaller 用 ICO）--------------------------------
_icon = os.path.join(_PKG, "app.ico")

# --- 排除清单 ------------------------------------------------------------
# 排除测试、截图目录、文档与源码杂项，减小体积并避免把开发者文件打进包。
_excludes = [
    "tests",
    "captures",
    "artifacts",
    "legacy_main",
    "app_gui",          # Tkinter 旧链（PySide6 正式客户端不需要）
    "theme",            # Tkinter 旧主题模块（保留源码，不进包）
    "tkinter",
    "pydoc",
    "test",
]

# --- 版本资源（Version resource）------------------------------------------
def _version_resource():
    """构造 Windows 版本资源对象。

    说明：VERSION_TUPLE=0.1.0.1 是 __version__="0.1.0-alpha.1" 的数字映射
    （alpha 后缀在 PE 文件版本中不合法，见 qt_client/version.py 注释）。
    """
    try:
        from PyInstaller.utils.win32.versioninfo import (
            FixedFileInfo, StringFileInfo, StringStruct, StringTable,
            VarFileInfo, VarStruct, VSVersionInfo,
        )
    except ImportError:  # 非 Windows 或旧版 PyInstaller：不附加版本资源
        return None

    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=VERSION_TUPLE,
            prodvers=VERSION_TUPLE,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,        # VOS_NT_WINDOWS32
            fileType=0x1,      # VFT_APP
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable(
                    "040904B0",  # 0409=English(US), 04B0=UTF-16LE
                    [
                        StringStruct("CompanyName", "PhoneVision Lab"),
                        StringStruct(
                            "FileDescription",
                            "PhoneVision Lab — 旧手机 IP 摄像头视觉工作台"),
                        StringStruct("FileVersion", VERSION_STR),
                        StringStruct("InternalName", APP_SLUG),
                        StringStruct("OriginalFilename", f"{APP_SLUG}.exe"),
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("ProductVersion", VERSION_STR),
                        StringStruct("LegalCopyright",
                                     "Copyright (c) 2026 PhoneVision Lab contributors"),
                    ],
                )
            ]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


_version_res = _version_resource()

# --- PyInstaller 配置 ------------------------------------------------------
a = Analysis(
    [os.path.join(_QT_CLIENT, "main.py")],
    pathex=[_PC_CLIENT, _QT_CLIENT],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        # PySide6 6.x 官方 hook 已覆盖大部分模块；若构建 warnings 指出
        # 缺模块（例如某个 Qt 组件），在此按需补充，不要全量 collect。
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX 无益且可能触发杀软，保持关闭
    console=False,      # windowed：不弹终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
    version=_version_res,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=_name,
)
