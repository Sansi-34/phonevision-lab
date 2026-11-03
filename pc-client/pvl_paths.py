"""
PhoneVision Lab — 用户数据目录约定。

职责：把"数据集、训练产物、日志、导入的模型"统一放到一个明确的用户目录下，
绝不混入源码目录，也绝不自动提交到 Git。

为什么这样设计：
  - 训练/采集会产生几十上百 MB 的图片与模型文件，放源码目录会污染仓库、
    拖慢 diff 与检索。这里集中到 %LOCALAPPDATA%/PhoneVisionLab（可移植到
    其他平台：Linux/macOS 下用 ~/.local/share/PhoneVisionLab）。
  - 目录名可被环境变量 PVL_DATA_DIR 覆盖，方便测试与多工作区隔离；
    测试用临时目录，不会写进真实用户数据。
  - 路径全部由代码推导，绝不在仓库里写死本机绝对路径（仓库健康测试会检查）。

初学者调试观察点：
  - 找不到数据时先看 user_data_dir() 指向哪里。
  - 测试通过 PVL_DATA_DIR 指向 tmp 目录，跑完即弃，不污染真实数据。
"""
from __future__ import annotations

import os
import tempfile

# 应用名（用于组织目录名，与 QSettings 的组织名一致）。
APP_DIR_NAME = "PhoneVisionLab"

# 环境变量名：显式覆盖数据根目录（测试/多工作区用）。
ENV_DATA_DIR = "PVL_DATA_DIR"


def user_data_dir() -> str:
    """返回用户数据根目录（不存在则创建）。

    优先级：
      1. 环境变量 PVL_DATA_DIR（测试与高级用户覆盖）。
      2. Windows: %LOCALAPPDATA%/PhoneVisionLab。
      3. 其他平台: ~/.local/share/PhoneVisionLab。
    """
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        root = os.path.abspath(override)
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        root = os.path.join(local, APP_DIR_NAME)
    else:
        root = os.path.join(os.path.expanduser("~"), ".local", "share", APP_DIR_NAME)
    os.makedirs(root, exist_ok=True)
    return root


def datasets_dir() -> str:
    """数据集根目录（每个子目录是一个数据集）。"""
    path = os.path.join(user_data_dir(), "datasets")
    os.makedirs(path, exist_ok=True)
    return path


def runs_dir() -> str:
    """训练运行产物根目录（每次训练一个子目录）。"""
    path = os.path.join(user_data_dir(), "runs")
    os.makedirs(path, exist_ok=True)
    return path


def models_dir() -> str:
    """导出的模型包根目录（供拷贝到手机）。"""
    path = os.path.join(user_data_dir(), "models")
    os.makedirs(path, exist_ok=True)
    return path


def logs_dir() -> str:
    """日志目录（应用日志与训练日志）。"""
    path = os.path.join(user_data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def exports_dir() -> str:
    """性能报告 / CSV 导出目录。"""
    path = os.path.join(user_data_dir(), "exports")
    os.makedirs(path, exist_ok=True)
    return path


def temp_dir(prefix: str = "pvl-") -> str:
    """临时目录（默认跟随用户数据根，便于集中清理）。"""
    path = os.path.join(tempfile.gettempdir(), prefix + "work")
    os.makedirs(path, exist_ok=True)
    return path
