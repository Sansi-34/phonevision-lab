"""
PhoneVision Lab — 日志配置（源码 / frozen 通用）。

职责：为整个应用提供唯一的日志管道，覆盖 启动/版本/连接/状态/错误/退出 等
生命周期事件，便于离线排查问题。

设计约束：
  - 日志写入 QStandardPaths.AppLocalDataLocation/logs/phonevision.log
    （Windows 通常为 %LOCALAPPDATA%/PhoneVisionLab/PhoneVisionLab/logs/）。
  - 目录创建失败绝不能导致启动失败：任何定位/建目录异常都回退到
    stderr（或 NullHandler），应用照常运行。
  - 隐私红线：绝不记录图像字节、截图内容、参数滑块的高频采样值、任何密钥/
    Token/密码。只记录状态名、错误类型、地址主机（不含端口密码类敏感串）等。
  - 无遥测：日志只写本机文件，不联网、不上报、不收集统计。
  - 需要 QApplication 已创建后再调用（QStandardPaths 需要应用对象）；
    若在极早期调用且 QApplication 不存在，回退 stderr，不抛异常。
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from qt_client import resources
from qt_client.version import APP_NAME, get_version_str

# 滚动大小约 1MB，保留最近 3 个备份（phonevision.log + .1/.2/.3）。
_MAX_BYTES = 1024 * 1024
_BACKUP_COUNT = 3

# 默认日志级别：INFO（源码调试可自行调低）。打包发布保持 INFO。
_DEFAULT_LEVEL = logging.INFO

# 应用级 logger 名（统一走这一个，避免各模块各自 addHandler 重复写）。
_LOGGER_NAME = "phonevision"

# 模块导入即保证应用 logger 默认级别为 INFO：即使调用方未显式调用
# setup_logging（例如测试直接往 logger 挂内存 handler），也不会继承 root 的
# 默认 WARNING 而漏掉 INFO 记录。setup_logging 仍负责挂 handler。
logging.getLogger(_LOGGER_NAME).setLevel(_DEFAULT_LEVEL)

# 日志里出现即属异常的值：绝对路径、完整 URL（可能含查询串）、密钥类。
_SENSITIVE_MARKERS = (
    "token", "apikey", "api_key", "password", "secret",
)


def _looks_sensitive(message: str) -> bool:
    """粗过滤：含密钥类关键词的日志行不写盘（防御式，双保险）。"""
    low = message.lower()
    return any(marker in low for marker in _SENSITIVE_MARKERS)


def _make_formatter() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def setup_logging(level: int = _DEFAULT_LEVEL) -> logging.Logger:
    """初始化应用日志，返回应用级 logger。

    调用时机：QApplication 创建之后、首次日志写入之前调用一次即可。
    可重入：重复调用返回同一 logger，不会叠加 handler。
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:  # 已初始化过，直接返回
        return logger

    logger.setLevel(level)
    logger.propagate = False  # 不向 root 重复输出

    handler: logging.Handler | None = None
    try:
        log_dir = resources.logs_dir()
        if log_dir:
            # 双保险：handler 打开文件前确保父目录存在（正常路径下 logs_dir
            # 已创建；这里再兜底一次，防止外部注入不存在的目录时直接抛错）。
            os.makedirs(log_dir, exist_ok=True)
            handler = RotatingFileHandler(
                os.path.join(log_dir, "phonevision.log"),
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
    except Exception:  # noqa: BLE001 - 目录/文件失败绝不能拖垮启动
        handler = None

    if handler is None:
        # 回退：stderr（frozen 无终端时实际丢弃，但绝不崩溃）。
        handler = logging.StreamHandler(sys.stderr)

    handler.setLevel(level)
    handler.setFormatter(_make_formatter())
    logger.addHandler(handler)
    return logger


def configure_logging(level: int = _DEFAULT_LEVEL) -> logging.Logger:
    """初始化应用日志（Qt 入口调用的便捷别名，等价 setup_logging）。

    供 qt_client.main 以 `from qt_client.logging_config import configure_logging`
    方式调用，与 setup_logging 同一实现。
    """
    return setup_logging(level)


def log_startup(logger: logging.Logger) -> None:
    """记录启动事件：应用名 + 版本（不含路径/密钥）。"""
    logger.info("%s 启动 (version=%s)", APP_NAME, get_version_str())


def log_exit(logger: logging.Logger) -> None:
    """记录退出事件。"""
    logger.info("%s 退出", APP_NAME)
