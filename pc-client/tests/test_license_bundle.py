"""
PhoneVision Lab — 许可 bundle 契约测试（P0-5B 硬门禁）。

职责：验证 Windows 便携包许可 bundle 的契约：
  23. licenses/ 含 LGPL-3.0 与 GPL-3.0 适用文本（LGPL 引用 GPL），
      且为完整版（含关键章节标记），不是占位文件。
  24. 不把 Commercial 授权冒充当前授权：THIRD_PARTY_NOTICES.md 明确
      标注 Commercial 文本"非当前采用路径"，且声明采用 LGPL-3.0。
  25. Qt 源码获取说明含精确版本（6.11.1），与 requirements-windows.lock
      锁定的 PySide6 版本一致。

为什么这样设计：
  - 全部静态检查（读文件/解析文本），不依赖网络，不构建。
  - LGPL-3.0 文本较长（约 7.8KB）且按条款并入 GPL-3.0，因此同时断言
    LGPL 自带关键章节标记（0/2/4/6 节）与 GPL-3.0 全文存在。
  - 用"关键章节标记 + 最小长度"判断完整版，避免误把标题截断文件当全文。
  - Commercial 检查抓两类违规：把 Commercial 当"采用许可"的措辞，
    以及 THIRD_PARTY_NOTICES 缺失 LGPL 声明。
"""
import os
import re
import unittest

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIC = os.path.join(_PC_CLIENT, "packaging", "licenses")
_NOTICES = os.path.join(_PC_CLIENT, "packaging", "THIRD_PARTY_NOTICES.md")
_LOCK = os.path.join(_PC_CLIENT, "packaging", "requirements-windows.lock")
_COMPLIANCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs", "qt-lgpl-compliance.md")

# 关键章节标记：LGPL-3.0 有 0/2/4/6 节；GPL-3.0 有 TERMS AND CONDITIONS。
_LGPL_MARKERS = [
    "Version 3, 29 June 2007",
    "0. Additional Definitions.",
    "2. Conveying Modified Versions.",
    "4. Combined Works.",
    "6. Revised Versions of the GNU Lesser General Public License.",
]
_GPL_MARKERS = [
    "Version 3, 29 June 2007",
    "TERMS AND CONDITIONS",
    "END OF TERMS AND CONDITIONS",
]

# LGPL-3.0 文本量级（~7.8KB）；GPL-3.0 文本量级（~36KB）。
_LGPL_MIN_BYTES = 6000
_GPL_MIN_BYTES = 30000


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class LgplGplTextTest(unittest.TestCase):
    """item 23：licenses/ 含 LGPL-3.0 与 GPL-3.0 完整适用文本。"""

    def test_lgpl_file_exists_and_is_full(self):
        path = os.path.join(_LIC, "lgpl-3.0.txt")
        self.assertTrue(os.path.exists(path), f"缺少 lgpl-3.0.txt（{path}）")
        text = _read(path)
        self.assertGreater(os.path.getsize(path), _LGPL_MIN_BYTES,
                           "lgpl-3.0.txt 疑似被截断（过小）")
        for marker in _LGPL_MARKERS:
            self.assertIn(marker, text, f"lgpl-3.0.txt 缺关键章节: {marker!r}")

    def test_gpl_file_exists_and_is_full(self):
        path = os.path.join(_LIC, "gpl-3.0.txt")
        self.assertTrue(os.path.exists(path), f"缺少 gpl-3.0.txt（{path}）")
        text = _read(path)
        self.assertGreater(os.path.getsize(path), _GPL_MIN_BYTES,
                           "gpl-3.0.txt 疑似被截断（过小）")
        for marker in _GPL_MARKERS:
            self.assertIn(marker, text, f"gpl-3.0.txt 缺关键章节: {marker!r}")

    def test_licenses_dir_no_surprise_custom_copies(self):
        """除 LGPL/GPL 文本外，不应出现无关的 lgpl/gpl 变体文件。"""
        names = {n for n in os.listdir(_LIC)
                 if re.match(r"^(lgpl|gpl)-", n, re.I)}
        self.assertTrue(names.issubset({"lgpl-3.0.txt", "gpl-3.0.txt"}),
                        f"licenses/ 出现未预期的 LGPL/GPL 变体: {names}")


class CommercialNotCurrentTest(unittest.TestCase):
    """item 24：不把 Commercial 冒充当前授权。"""

    COMMERCIAL_FILES = [
        "PySide6_LicenseRef-Qt-Commercial.txt",
        "PySide6_Essentials_LicenseRef-Qt-Commercial.txt",
        "PySide6_Addons_LicenseRef-Qt-Commercial.txt",
        "shiboken6_LicenseRef-Qt-Commercial.txt",
    ]

    def test_commercial_files_kept_but_not_current(self):
        notices = _read(_NOTICES)
        # THIRD_PARTY_NOTICES 明确声明采用 LGPL-3.0。
        self.assertIn("LGPL-3.0", notices)
        # 明确标注 Commercial 非当前采用路径。
        for phrase in ("非当前采用路径", "Commercial", "非当前采用"):
            self.assertIn(phrase, notices,
                          f"THIRD_PARTY_NOTICES.md 应含 {phrase!r}")
        # 同时出现否定句：明确说"不/未"采用商业 Qt 授权（不能只留"参考"）。
        self.assertIn("未持有商业", notices,
                      "THIRD_PARTY_NOTICES.md 应明确否定采用商业 Qt 授权")

    def test_qt_compliance_marks_commercial_reference(self):
        """qt-lgpl-compliance.md 声明采用 LGPL-3.0 且标注 Commercial 为参考。"""
        self.assertTrue(os.path.exists(_COMPLIANCE),
                        f"缺少 docs/qt-lgpl-compliance.md（{_COMPLIANCE}）")
        text = _read(_COMPLIANCE)
        self.assertIn("LGPL-3.0", text)
        for phrase in ("非当前采用路径", "不构成法律意见"):
            self.assertIn(phrase, text, f"合规文档应含 {phrase!r}")
        # 明确否定采用商业 Qt 授权（不能只留"参考"措辞）。
        self.assertIn("不代表本项目采用商业", text,
                      "合规文档应否定采用商业 Qt 授权")


class QtVersionDocTest(unittest.TestCase):
    """item 25：Qt 源码获取说明含精确版本（与锁文件一致）。"""

    def test_qt_source_doc_has_exact_version(self):
        """合规文档与 THIRD_PARTY_NOTICES 均含 6.11.1。"""
        self.assertTrue(os.path.exists(_COMPLIANCE))
        for text_name, text in (("qt-lgpl-compliance.md", _read(_COMPLIANCE)),
                                ("THIRD_PARTY_NOTICES.md", _read(_NOTICES))):
            self.assertIn("6.11.1", text,
                          f"{text_name} 应含精确版本 6.11.1")

    def test_version_matches_lockfile(self):
        """锁文件中的 PySide6 版本即文档引用的版本。"""
        self.assertTrue(os.path.exists(_LOCK))
        lock = _read(_LOCK)
        m = re.search(r"^PySide6==([0-9.]+)", lock, re.M)
        self.assertIsNotNone(m, "requirements-windows.lock 应锁定 PySide6==版本")
        locked = m.group(1)
        self.assertEqual(locked, "6.11.1",
                         f"锁文件 PySide6=={locked} 与文档版本 6.11.1 不一致")

    def test_qt_source_url_mentions_download_qt_io(self):
        """源码获取 URL 指向官方 Qt 下载源。"""
        text = _read(_COMPLIANCE)
        self.assertIn("download.qt.io", text)
        self.assertIn("6.11", text)


if __name__ == "__main__":
    unittest.main()
