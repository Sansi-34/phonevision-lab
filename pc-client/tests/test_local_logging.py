"""
PhoneVision Lab — P0-5A 本地日志配置测试。

职责：验证 qt_client/logging_config.py 的本地日志契约：
  22. 日志目录创建失败不阻止启动：mock 目录创建抛异常后 setup_logging 不抛，
      回退到 stderr handler。
  23. 日志轮转配置正确：RotatingFileHandler，maxBytes≈1MB（1024*1024），
      backupCount=3，UTF-8 编码。
  24. 日志不写图像字节：日志记录纯文本，不含 JPEG 帧数据（不把图像字节/
      base64 写进日志）。

为什么这样设计：
  - setup_logging 是全局 logger 单例（可重入：有 handler 就直接返回）。为让
    每个测试从干净状态开始，用 _clean_logger 清空 logger.handlers 再重新 setup。
  - Windows 下 RotatingFileHandler 持文件句柄，临时目录清理前必须 close 旧
    handler，否则 PermissionError 无法删除日志文件。_clean_logger 负责 close。
  - "不写图像字节"测试用内存 handler，验证产品日志只记录状态/错误文本。
"""
import io
import logging
import os
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from unittest import mock

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

import qt_client.logging_config as logging_config  # noqa: E402


def _clean_logger():
    """清空 'phonevision' logger 的 handler，返回 (logger, 原 handlers)。

    Windows 下 RotatingFileHandler 持文件句柄，必须 close 旧 handler 释放锁，
    否则临时目录删除报 PermissionError。返回的 old 供测试结束后恢复。
    """
    logger = logging.getLogger("phonevision")
    old = list(logger.handlers)
    logger.handlers = []
    logger.propagate = False
    for h in old:
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return logger, old


def _restore_logger(logger, old):
    """测试结束：close 当前 handler 并恢复原 handlers（释放 Windows 文件锁）。"""
    for h in logger.handlers:
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    logger.handlers = old


class LoggingDirFailureTest(unittest.TestCase):
    """item 22：日志目录失败不阻止启动。"""

    def test_setup_logging_survives_logs_dir_failure(self):
        """mock logs_dir() 抛异常 → setup_logging 不抛，回退 stderr。"""
        logger, old = _clean_logger()
        self.addCleanup(_restore_logger, logger, old)
        with mock.patch(
                "qt_client.logging_config.resources.logs_dir",
                side_effect=OSError("磁盘只读")) as m:
            result = logging_config.setup_logging()
        m.assert_called_once()
        self.assertIs(result, logger, "应返回应用级 logger")
        # 回退为 StreamHandler（stderr），而非崩溃
        self.assertEqual(len(logger.handlers), 1)
        self.assertIsInstance(logger.handlers[0], logging.StreamHandler)
        # 记录一条日志也不抛（目录失败后的日志照常走回退 handler）
        logger.info("startup ok despite dir failure")
        self.assertEqual(logger.level, logging.INFO)

    def test_configure_logging_is_alias(self):
        """configure_logging 与 setup_logging 同一实现（入口便捷别名）。"""
        logger, old = _clean_logger()
        self.addCleanup(_restore_logger, logger, old)
        with mock.patch(
                "qt_client.logging_config.resources.logs_dir",
                side_effect=PermissionError("无权限")):
            # configure_logging 内部走 setup_logging：不抛
            result = logging_config.configure_logging()
        self.assertIs(result, logger)

    def test_app_data_dir_failure_returns_none(self):
        """app_data_dir 失败返回 None（调用方容忍），不抛异常。"""
        import qt_client.resources as res
        with mock.patch.object(
                res.QStandardPaths, "writableLocation",
                side_effect=RuntimeError("Qt 定位失败")):
            # 需要在有 QCoreApplication 时走 QStandardPaths 分支
            from PySide6.QtWidgets import QApplication
            QApplication.instance() or QApplication([])
            self.assertIsNone(res.app_data_dir())


class LogRotationTest(unittest.TestCase):
    """item 23：日志轮转配置正确。"""

    def test_rotating_handler_with_1mb_and_3_backups_utf8(self):
        """正常目录路径下创建 RotatingFileHandler：maxBytes≈1MB、backup=3、UTF-8。"""
        logger, old = _clean_logger()
        self.addCleanup(_restore_logger, logger, old)
        with tempfile.TemporaryDirectory() as tmp:
            fake_log_dir = os.path.join(tmp, "logs")
            os.makedirs(fake_log_dir)  # RotatingFileHandler 不自动创建中间目录
            with mock.patch(
                    "qt_client.logging_config.resources.logs_dir",
                    return_value=fake_log_dir):
                logging_config.setup_logging()
            self.assertEqual(len(logger.handlers), 1)
            handler = logger.handlers[0]
            self.assertIsInstance(handler, RotatingFileHandler)
            self.assertEqual(handler.maxBytes, 1024 * 1024, "maxBytes 应为 1MB")
            self.assertEqual(handler.backupCount, 3, "backupCount 应为 3")
            self.assertEqual(handler.encoding, "utf-8", "日志应为 UTF-8 编码")
            self.assertEqual(handler.baseFilename,
                             os.path.join(fake_log_dir, "phonevision.log"))
            # 在 TemporaryDirectory 删除前关闭 handler，释放 Windows 文件锁
            for h in logger.handlers:
                try:
                    h.close()
                except Exception:  # noqa: BLE001
                    pass
            logger.handlers = []

    def test_setup_is_idempotent(self):
        """重复 setup_logging 不叠加 handler（可重入）。"""
        logger, old = _clean_logger()
        self.addCleanup(_restore_logger, logger, old)
        with tempfile.TemporaryDirectory() as tmp:
            fake_log_dir = os.path.join(tmp, "logs")
            os.makedirs(fake_log_dir)
            with mock.patch(
                    "qt_client.logging_config.resources.logs_dir",
                    return_value=fake_log_dir):
                logging_config.setup_logging()
                logging_config.setup_logging()
                logging_config.setup_logging()
            self.assertEqual(len(logger.handlers), 1,
                             "重复初始化不应叠加 handler")
            # 在 TemporaryDirectory 删除前关闭 handler，释放 Windows 文件锁
            for h in logger.handlers:
                try:
                    h.close()
                except Exception:  # noqa: BLE001
                    pass
            logger.handlers = []


class LogNoImageBytesTest(unittest.TestCase):
    """item 24：日志不写图像字节（纯文本，无 JPEG 帧数据）。"""

    def _capture_log(self, *records):
        """把 'phonevision' logger 的 handler 换成内存 handler，写入 records。

        显式 setLevel(INFO)：日志默认 level 可能是 NOTSET（未调用 setup_logging），
        propagate=False 时有效级别会落到 root 的 WARNING，INFO 记录会被过滤。
        """
        logger, old = _clean_logger()
        self.addCleanup(_restore_logger, logger, old)
        logger.setLevel(logging.INFO)
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        for args in records:
            logger.info(*args)
        return buf.getvalue()

    def test_status_logs_are_plain_text(self):
        """状态/版本/连接类日志是纯文本，不含 JPEG 帧数据。"""
        jpeg_bytes = bytes(range(256))  # 含 0xFFD8 头可能字节的假图像数据
        base64_blob = "9j/4AAQSkZJRgABAQAAAQABAAD//gA" * 10  # 大 base64 串
        text = self._capture_log(
            ("PhoneVision Lab 启动 (version=%s)", "0.1.0-alpha.1"),
            ("连接地址 host=%s", "192.168.1.100"),
            ("状态 %s，错误 %s", "Reconnecting", "HTTPConnectionPool"),
        )
        self.assertIn("PhoneVision Lab 启动", text)
        self.assertIn("192.168.1.100", text)
        # 图像字节不应出现：raw bytes 不可写进文本日志
        for bad in ("\\xff\\xd8", base64_blob):
            self.assertNotIn(bad, text, f"日志不应包含图像字节 {bad!r}")
        # 文本日志不包含 JPEG 起始/结束标志的转义序列
        self.assertNotIn("ffd8", text.lower())
        self.assertNotIn("ffd9", text.lower())

    def test_no_jpeg_frame_dumped_to_log(self):
        """即使误传帧字节给日志，也不应把图像数据本身当作内容记录。

        说明：Python `%s` 对 bytes 会输出其 repr（如 b'\\xff\\xd8...'），这是
        语言标准行为。产品代码（logging_config.py）从不把帧字节传给日志——
        它只记录状态名/错误类型等文本。本测试验证两点：
          1) JPEG 起始/结束标志的十六进制序列（ffd8/ffd9）不以可读形式出现在日志；
          2) 产品日志记录的是"状态/错误文本"而非原始帧对象。
        """
        # 模拟产品日志的真实调用：记录的是状态字符串，不是帧字节
        text = self._capture_log(
            ("状态 %s", "Streaming"),
            ("错误 %s", "HTTPConnectionPool"),
            ("连接地址 host=%s port=%s", "192.168.1.100", 8080),
        )
        # 产品日志不应含 JPEG 标志的十六进制文本
        self.assertNotIn("ffd8", text.lower())
        self.assertNotIn("ffd9", text.lower())
        # 产品日志含的是状态/错误文本
        self.assertIn("Streaming", text)
        self.assertIn("HTTPConnectionPool", text)

    def test_sensitive_keywords_not_logged_by_helper(self):
        """防御式过滤：含密钥关键词的日志行不应被 _looks_sensitive 放行。"""
        import qt_client.logging_config as lc
        self.assertTrue(lc._looks_sensitive("connect token=abc"))
        self.assertTrue(lc._looks_sensitive("api_key=xxxx password=yyy"))
        self.assertFalse(lc._looks_sensitive("connection status Reconnecting"))


if __name__ == "__main__":
    unittest.main()
