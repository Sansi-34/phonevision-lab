# -*- mode: python ; coding: utf-8 -*-
# =====================================================================
# PhoneVision Lab Web — PyInstaller onedir spec (Windows x64)
#
# 用法（由 web/scripts/build_windows.ps1 调用，通常不手工运行）：
#   pyinstaller --noconfirm --clean packaging/PhoneVisionLabWeb.spec
#
# 与桌面端 spec（pc-client/packaging/PhoneVisionLab.spec）的差异：
#   - 入口是 web/launcher.py：启动本地 HTTP 服务并打开系统默认浏览器；
#   - 不需要 PySide6（网页后端只依赖 cv2/numpy/requests），体积小一半以上；
#   - static/ 整个目录作为数据文件打进包（前端零构建，原样拷贝即可）；
#   - console=False：双击不弹终端；服务日志写到 %LOCALAPPDATA% 便于排查。
#
# 路径全部由 SPECPATH 相对推导，不含任何本机绝对路径。
# =====================================================================

import os
import sys

# --- 路径推导（全部相对，无本机绝对路径）-------------------------------
# SPECPATH = web/packaging/ 目录（PyInstaller 注入）。
_HERE = os.path.abspath(SPECPATH)
# web/ 根目录 = packaging/ 的上一级。
_WEB = os.path.dirname(_HERE)
# 仓库根目录。
_REPO = os.path.dirname(_WEB)
# pc-client/ 目录：网页后端要 import 它的 connection / mjpeg_reader / pvl_* 模块。
_PC_CLIENT = os.path.join(_REPO, "pc-client")
# 前端静态资源目录。
_STATIC = os.path.join(_WEB, "static")

# 让 import 能解析 pc-client 与 web/server。
sys.path.insert(0, _PC_CLIENT)
sys.path.insert(0, _WEB)

# --- 版本来源：复用桌面端 version.py（唯一事实来源）--------------------
try:
    sys.path.insert(0, _PC_CLIENT)
    from qt_client.version import APP_NAME, VERSION_STR, VERSION_TUPLE
except Exception:  # noqa: BLE001 - version.py 缺失时用保守默认值
    APP_NAME = "PhoneVision Lab"
    VERSION_STR = "0.1.0-alpha.1"
    VERSION_TUPLE = (0, 1, 0, 1)

APP_SLUG = "PhoneVisionLabWeb"

# --- 产物目录 -----------------------------------------------------------
_dist_dir = os.path.join(_WEB, "dist")
_build_dir = os.path.join(_WEB, "build")

# --- 随包携带的数据文件 --------------------------------------------------
# static/ 下所有文件按原相对路径打进包：launcher 用 _resource_path() 定位。
_datas = []
for _base, _dirs, _files in os.walk(_STATIC):
    for _name in _files:
        _src = os.path.join(_base, _name)
        _rel = os.path.relpath(_base, _STATIC)
        _dest = os.path.join("static", _rel) if _rel != "." else "static"
        _datas.append((_src, _dest))

# 应用图标（若存在则用作 EXE 图标）。
_icon = os.path.join(_HERE, "assets", "app.ico")
if not os.path.isfile(_icon):
    _icon = None

# --- 排除清单 ------------------------------------------------------------
# 网页后端不碰 PySide6 / tkinter / 训练框架（TensorFlow 按需在用户环境安装，
# 不打进包：它约 500 MB，且多数用户只做学习与预览）。
_excludes = [
    "PySide6",
    "tkinter",
    "tests",
    "captures",
    "artifacts",
    "legacy_main",
    "app_gui",
    "theme",
    "tensorflow",
    "torch",
    "matplotlib",
    "pandas",
    "pydoc",
    "test",
]

# --- 版本资源 -----------------------------------------------------------
def _version_resource():
    try:
        from PyInstaller.utils.win32.versioninfo import (
            FixedFileInfo, StringFileInfo, StringStruct, StringTable,
            VarFileInfo, VarStruct, VSVersionInfo,
        )
    except ImportError:
        return None

    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=VERSION_TUPLE,
            prodvers=VERSION_TUPLE,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "PhoneVision Lab"),
                        StringStruct(
                            "FileDescription",
                            "PhoneVision Lab Web — 视觉 AI 学习与实践平台"),
                        StringStruct("FileVersion", VERSION_STR),
                        StringStruct("InternalName", APP_SLUG),
                        StringStruct("OriginalFilename", f"{APP_SLUG}.exe"),
                        StringStruct("ProductName", "PhoneVision Lab Web"),
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
    [os.path.join(_WEB, "launcher.py")],
    pathex=[_REPO, _WEB, _PC_CLIENT],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        # cv2 由官方 hook 收集；web.server 是普通包，按 pathex 解析。
        "server",
        "server.app",
        "server.device",
        "server.dataset",
        "server.training",
        "server.hardware",
        "server.performance",
        "server.util",
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
    name=APP_SLUG,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,      # windowed：双击不弹终端
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
    name=APP_SLUG,
)
