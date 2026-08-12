"""
PhoneVision Lab — 仓库健康契约测试（P0-5B 公开化门禁）。

职责：静态检查公开化相关的仓库文档契约：
   9. 根 README 无本机绝对路径（D:\\、用户名、用户主目录）。
  10. 根 README 无虚假 Release URL / 下载按钮 / CI badge（声称 CI 通过）。
  11. .github/ISSUE_TEMPLATE 与 PR 模板无虚假 label/assignee。
  12. SECURITY.md 无占位邮箱（不编造安全邮箱）。
  13. 双语 README（README.md / README.zh-CN.md）关键章节一致。

为什么这样设计：
  - 全部静态检查（读文本），不联网、不 import 应用代码。
  - 占位邮箱检测覆盖常见占位形态（@example.com/@example.org/@domain/
    security@… 等），同时要求 SECURITY 存在且声明私有漏洞报告机制。
  - 双语一致性只校验"关键章节锚点"（标题、警告、许可），避免逐字比较
    导致测试脆弱（翻译允许措辞不同）。
"""
import os
import re
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_README = os.path.join(_REPO, "README.md")
_README_ZH = os.path.join(_REPO, "README.zh-CN.md")
_SECURITY = os.path.join(_REPO, "SECURITY.md")
_ISSUE_DIR = os.path.join(_REPO, ".github", "ISSUE_TEMPLATE")
_PR_TEMPLATE = os.path.join(_REPO, ".github", "pull_request_template.md")

# 本机用户名（测试进程所见）与已知开发机名。
_LOCAL_USER = os.environ.get("USERNAME") or os.environ.get("USER") or ""

# 占位/示例邮箱形态（无真实域名时视为占位）。
_PLACEHOLDER_EMAIL = re.compile(
    r"[\w.+-]+@(example\.com|example\.org|example\.net|domain\.com|"
    r"yourdomain|your\.email|example\.io)\b", re.I)

_FAKE_BADGE = re.compile(
    r"\[!\[[^\]]*\]\([^)]*badge[^)]*\)\]\([^)]*\)", re.I)
_FAKE_RELEASE_URL = re.compile(
    r"https?://[^)\s]*releases/download[^)\s]*", re.I)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _collect_yaml_files():
    return [os.path.join(_ISSUE_DIR, n)
            for n in os.listdir(_ISSUE_DIR)
            if n.endswith((".yml", ".yaml"))] if os.path.isdir(_ISSUE_DIR) else []


class ReadmeHealthTest(unittest.TestCase):
    """item 9/10：README 无本机路径、虚假 URL/badge。"""

    def test_readme_no_local_paths(self):
        for name in ("README.md", "README.zh-CN.md"):
            text = _read(os.path.join(_REPO, name))
            # 盘符绝对路径：单字母盘符 + 冒号 + 斜杠，且盘符前不是字母
            # （排除 http:// 这类 scheme 中的 "p:/"）。
            self.assertIsNone(re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text),
                              f"{name} 不应含盘符绝对路径")
            self.assertNotIn("22917", text, f"{name} 不应含本机用户名")
            self.assertNotIn("Sansi", text, f"{name} 不应含本机用户名")
            home = os.path.expanduser("~").lower()
            if home:
                self.assertNotIn(home, text.lower(),
                                 f"{name} 不应含用户主目录路径")

    def test_readme_no_fake_release_downloads(self):
        for name in ("README.md", "README.zh-CN.md"):
            text = _read(os.path.join(_REPO, name))
            self.assertIsNone(_FAKE_RELEASE_URL.search(text),
                              f"{name} 不应含虚假 Release 下载 URL")
            # 不得有"立即下载"按钮式链接到不存在的发布页
            self.assertNotIn("download", text.lower(),
                             f"{name} 不应出现 download 字样")
            self.assertNotIn("下载", text, f"{name} 不应出现下载按钮措辞")

    def test_readme_no_ci_badges(self):
        for name in ("README.md", "README.zh-CN.md"):
            text = _read(os.path.join(_REPO, name))
            self.assertIsNone(_FAKE_BADGE.search(text),
                              f"{name} 不应含 CI badge（未声称 CI 通过）")
            for bad in ("ci passing", "build passing", "coverage"):
                self.assertNotIn(bad, text.lower(),
                                 f"{name} 不应声称 {bad}")

    def test_readme_marks_prerelease(self):
        for name, markers in (("README.md", ("Pre-release", "Not ready")),
                              ("README.zh-CN.md", ("Pre-release", "尚未达到"))):
            text = _read(os.path.join(_REPO, name))
            for marker in markers:
                self.assertIn(marker, text,
                              f"{name} 应标注 Pre-release/尚未达到 v1.0")


class TemplateHealthTest(unittest.TestCase):
    """item 11：Issue/PR 模板无虚假 label/assignee。"""

    def test_issue_templates_exist(self):
        files = _collect_yaml_files()
        self.assertTrue(files, ".github/ISSUE_TEMPLATE/ 下应有 yml/yaml 模板")

    def test_templates_have_no_fake_labels_or_assignees(self):
        targets = _collect_yaml_files() + [_PR_TEMPLATE]
        for path in targets:
            if not os.path.exists(path):
                continue
            text = _read(path)
            # 不得声明不存在/占位的 label 或 assignee
            for bad in ("label: bug", "assignee", "assignees"):
                self.assertNotIn(bad.lower(), text.lower(),
                                 f"{os.path.basename(path)} 不应含 {bad!r}")

    def test_pr_template_covers_privacy_and_license(self):
        if not os.path.exists(_PR_TEMPLATE):
            self.skipTest("pull_request_template.md 尚不存在")
        text = _read(_PR_TEMPLATE)
        # 覆盖隐私与许可（英文 PR 模板，检查英文关键词）。
        for keyword in ("privacy", "no telemetry", "license"):
            self.assertIn(keyword, text.lower(),
                          f"PR 模板应覆盖 {keyword!r}")


class SecurityDocTest(unittest.TestCase):
    """item 12：SECURITY.md 无占位邮箱，声明私有漏洞报告。"""

    def test_security_exists(self):
        self.assertTrue(os.path.exists(_SECURITY),
                        f"缺少 SECURITY.md（{_SECURITY}）")

    def test_no_placeholder_email(self):
        text = _read(_SECURITY)
        m = _PLACEHOLDER_EMAIL.search(text)
        self.assertIsNone(m, f"SECURITY.md 不应含占位邮箱: {m.group(0) if m else ''}")
        # 通用 "security@" 本地部分若无真实域名也判为占位
        self.assertNotIn("security@", text,
                         "SECURITY.md 不应含 security@… 占位邮箱")

    def test_security_mentions_private_vulnerability_reporting(self):
        text = _read(_SECURITY)
        self.assertIn("Private Vulnerability Reporting", text)
        self.assertIn("private vulnerability reporting", text.lower())
        self.assertIn("Report a vulnerability", text)


class BilingualConsistencyTest(unittest.TestCase):
    """item 13：双语 README 关键章节一致。"""

    ANCHORS_EN = [
        "License", "MIT", "Status: Pre-release",
        "Windows portable", "Getting started",
        "no telemetry",
    ]
    ANCHORS_ZH = [
        "开源许可证", "MIT", "状态：Pre-release",
        "Windows 便携包", "快速开始",
        "无遥测", "尚未达到 v1.0",
    ]

    def test_both_readmes_exist(self):
        self.assertTrue(os.path.exists(_README))
        self.assertTrue(os.path.exists(_README_ZH))

    def test_key_sections_present_in_both(self):
        en = _read(_README)
        zh = _read(_README_ZH)
        for anchor in self.ANCHORS_EN:
            self.assertIn(anchor, en, f"README.md 缺关键章节: {anchor!r}")
        for anchor in self.ANCHORS_ZH:
            self.assertIn(anchor, zh, f"README.zh-CN.md 缺关键章节: {anchor!r}")
        # 大小写不敏感补充：英文声明 pre-release。
        self.assertIn("not ready", en.lower())

    def test_license_and_warning_consistent(self):
        en = _read(_README)
        zh = _read(_README_ZH)
        # 许可一致：都为 MIT。
        self.assertIn("MIT", en)
        self.assertIn("MIT", zh)
        # 安全警告一致：都警告无认证/仅可信局域网。
        for kw in ("no authentication", "trusted network", "same lan"):
            self.assertIn(kw, en.lower(), f"README.md 缺警告: {kw!r}")
        for kw in ("没有身份认证", "可信的本地网络"):
            self.assertIn(kw, zh, f"README.zh-CN.md 缺警告: {kw!r}")


if __name__ == "__main__":
    unittest.main()
