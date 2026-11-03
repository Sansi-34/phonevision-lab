"""P0-5B — GitHub Actions 工作流静态测试。

职责：在不依赖真实 GitHub 仓库/runner 的前提下，静态验证 .github/workflows/
下的工作流符合 P0-5B 安全与结构约束：
  1. 所有 `uses:` 外部 Action 固定完整 40 位 commit SHA。
  2. 每个 SHA 旁有 # vX.Y.Z 版本注释。
  3. 顶层默认 permissions 为 contents: read。
  4. 不使用 pull_request_target。
  5. PR 触发的工作流不引用 secret。
  6. windows-package 仅 workflow_dispatch 手动触发。
  7. android-candidate 不创建 GitHub Release。
  8. workflow 引用的脚本/文件路径都存在。

说明：本测试是"本地静态验证"，不声称 GitHub-hosted CI 已执行
（当前仓库无 remote；真实 Actions 验收在 P0-5C 首次 push 后进行）。
"""
import os
import re
import sys
import unittest
import glob
import yaml

# 仓库根 = pc-client/tests/ 向上三级
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS_DIR = os.path.join(_REPO, ".github", "workflows")

# 已知外部 Action 及其官方 40 位 SHA（从官方仓库 release 验证，非猜测）。
# 若版本升级需从对应官方仓库重新取 SHA，勿随手改。
KNOWN_ACTION_SHA = {
    "actions/checkout": "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/setup-java": "b6effb05e454b25005698d916606bdc6ffcbf961",
    "gradle/actions/setup-gradle": "0723195856401067f7a2779048b490ace7a47d7c",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(r"^uses:\s*([^\s@]+)@([0-9a-f]{40}|[^\s]+)\s*(#.*)?$")


def _load_workflow(name):
    path = os.path.join(WORKFLOWS_DIR, name)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class CiWorkflowTest(unittest.TestCase):

    def test_workflows_exist(self):
        for name in ("ci.yml", "windows-package.yml", "android-candidate.yml"):
            self.assertTrue(os.path.exists(os.path.join(WORKFLOWS_DIR, name)),
                            f"缺失 workflow: {name}")

    def test_all_uses_pinned_to_40_sha_with_comment(self):
        """所有外部 uses: 固定 40 位 SHA 且带版本注释。"""
        for wf in glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml")):
            with open(wf, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("uses:"):
                        continue
                    m = USES_RE.match(line)
                    self.assertIsNotNone(m, f"{wf}: 无法解析 uses 行: {line}")
                    action, ref, comment = m.groups()
                    self.assertTrue(SHA_RE.match(ref),
                                    f"{wf}: {action} 未固定 40 位 SHA: {ref}")
                    self.assertTrue(comment and comment.startswith("#"),
                                    f"{wf}: {action} 缺版本注释")

    def test_known_action_shas_match(self):
        """KNOWN_ACTION_SHA 与 workflow 中使用的 SHA 一致（防升级改乱）。"""
        for wf in glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml")):
            with open(wf, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("uses:"):
                        continue
                    m = USES_RE.match(line)
                    if not m:
                        continue
                    action, ref, _ = m.groups()
                    if action in KNOWN_ACTION_SHA:
                        self.assertEqual(
                            ref, KNOWN_ACTION_SHA[action],
                            f"{wf}: {action} SHA 与 KNOWN_ACTION_SHA 不符")

    def test_top_level_permissions_read(self):
        """每个 workflow 顶层 permissions 为 contents: read。"""
        for name in ("ci.yml", "windows-package.yml", "android-candidate.yml"):
            wf = _load_workflow(name)
            perms = wf.get("permissions", {})
            self.assertEqual(perms.get("contents"), "read",
                             f"{name}: 顶层 permissions 非 contents: read")

    def test_no_pull_request_target(self):
        """不使用 pull_request_target（安全）。"""
        for wf in glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml")):
            with open(wf, encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("pull_request_target", content,
                             f"{wf}: 使用了 pull_request_target")

    def test_pr_workflow_no_secret(self):
        """ci.yml 在 pull_request 触发路径不引用 secret。"""
        wf = _load_workflow("ci.yml")
        # 序列化后全文找 ${{ secrets. }}
        import json
        text = json.dumps(wf)
        # 若 ci.yml 同时被 push/pull_request 触发，其步骤不得引用 secret
        if "pull_request" in str(wf.get("on", {})):
            self.assertNotIn("secrets.", text,
                             "ci.yml 在 PR 路径引用了 secret")

    def test_windows_package_manual_only(self):
        """windows-package.yml 仅 workflow_dispatch 触发。

        PyYAML 把 `on:` 键按 YAML 1.1 解析为 None/True，因此从原始文本检查
        `on:` 段的内容，避免误判。
        """
        path = os.path.join(WORKFLOWS_DIR, "windows-package.yml")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        # on: 后紧跟 workflow_dispatch，且不含 push/pull_request
        self.assertIn("workflow_dispatch", content)
        self.assertNotIn("push:", content)
        self.assertNotIn("pull_request:", content)

    def test_android_candidate_no_release(self):
        """android-candidate.yml 不创建 GitHub Release。"""
        with open(os.path.join(WORKFLOWS_DIR, "android-candidate.yml"),
                  encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("softprops/action-gh-release", content)
        self.assertNotIn("gh release create", content)
        self.assertNotIn("github.ref", content)  # 不依赖 tag 触发

    def test_workflow_referenced_paths_exist(self):
        """workflow 引用的脚本/文件路径存在。"""
        # windows-package 引用 pc-client/scripts/build_windows.ps1
        self.assertTrue(
            os.path.exists(os.path.join(_REPO, "pc-client", "scripts",
                                        "build_windows.ps1")))
        # android-candidate 引用 android/scripts/build_release_candidate.ps1
        self.assertTrue(
            os.path.exists(os.path.join(_REPO, "android", "scripts",
                                        "build_release_candidate.ps1")))

    def test_yaml_syntax_valid(self):
        for wf in glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml")):
            try:
                with open(wf, encoding="utf-8") as fh:
                    yaml.safe_load(fh)
            except yaml.YAMLError as e:
                self.fail(f"{wf}: YAML 语法错误: {e}")

    def test_no_local_paths_in_workflows(self):
        """workflow 不含本机绝对路径/用户名。

        注：ci.yml 的 repository-checks 步骤本身含 git grep 泄漏检查命令
        （含 D:\\\\ 字面用于扫描仓库），属"检查泄漏的命令"，不是泄漏本身。
        """
        for wf in glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml")):
            with open(wf, encoding="utf-8") as f:
                lines = f.readlines()
            for lineno, line in enumerate(lines, 1):
                for bad in (r"D:\\", r"C:\\Users", "22917"):
                    # 跳过 ci.yml 泄漏检查命令行（grep 模式本身）
                    if "git grep" in line and bad in line:
                        continue
                    self.assertNotIn(bad, line,
                                     f"{os.path.basename(wf)}:{lineno} 含 {bad}")


if __name__ == "__main__":
    unittest.main()
