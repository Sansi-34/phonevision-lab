"""
PhoneVision Lab — P0-5A 打包配置测试（version / spec / build 脚本）。

职责：验证 Windows 便携包打包相关配置的契约：
  15. main.py 的 --version 打印 0.1.0-alpha.1（尚未接入时 skip）。
  16. qt_client/version.py：VERSION_TUPLE == (0,1,0,1)，__version__ == "0.1.0-alpha.1"。
  17. PhoneVisionLab.spec 的 datas 包含 style.qss / 应用图标（app.png / app.ico）。
  18. spec 不包含本机绝对路径（不匹配 r"D:\\" 或用户名）。
  19. build_windows.ps1 的删除目标严格受限（只允许 pc-client\\build、
      pc-client\\dist、artifacts\\windows）。

为什么这样设计：
  - 全部静态检查（读文件/解析源码），不运行 PyInstaller（本机未安装，且
    构建应在干净 venv 内由 ps1 完成）。
  - 用 AST 解析 version.py，比 import 更稳：测试进程 import qt_client.version
    没有副作用，但 AST 还能额外断言"常量确实按字面写死"（防被别处 import
    绕过而测试误过）。
  - spec 的 datas 是 Python 列表字面量：用 AST 取出并求值，检查资源条目。
  - ps1 删除目标的检查：正则提取 Remove-Item 路径与"允许名"守卫，确认脚本
    只会删除 build/dist 且限定在 pc-client 仓库根之下，绝不碰仓库外目录。

依赖源码状态：
  - version.py / spec / ps1 / resources.py 均已落地（另一 agent）→ 可跑。
  - qt_client.main 的 --version 参数尚未接入 → item 15 用 skipUnless 门控。
"""
import ast
import os
import re
import sys
import unittest

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

_SPEC_PATH = os.path.join(_PC_CLIENT, "packaging", "PhoneVisionLab.spec")
_PS1_PATH = os.path.join(_PC_CLIENT, "scripts", "build_windows.ps1")
_VERSION_PATH = os.path.join(_PC_CLIENT, "qt_client", "version.py")


def _spec_source() -> str:
    with open(_SPEC_PATH, encoding="utf-8") as fh:
        return fh.read()


def _spec_datas() -> list:
    """AST 取出 spec 中 _datas 列表并求值（含 os.path.join 拼接）。

    依次求值 spec 顶层的简单 Name 赋值（_HERE/_PC_CLIENT/_QT_CLIENT/_PKG），
    遇到 _datas 时在累积的 env 中求值列表字面量。SPECPATH 是 PyInstaller
    注入的常量，测试中模拟为真实 spec 所在目录（packaging/），使求值结果
    与真实构建一致。
    """
    tree = ast.parse(_spec_source())
    env = {"os": os, "sys": sys,
           "SPECPATH": os.path.join(_PC_CLIENT, "packaging")}

    def safe_eval(node):
        return eval(compile(ast.Expression(node), "<spec>", "eval"), env)

    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
            if name == "_datas":
                return [
                    (os.path.normpath(s), d)
                    for s, d in safe_eval(node.value)
                ]
            if name in ("_HERE", "_PC_CLIENT", "_QT_CLIENT", "_PKG",
                        "_name", "_dist_dir", "_build_dir"):
                try:
                    env[name] = safe_eval(node.value)
                except Exception:  # noqa: BLE001 - 求值失败跳过，交给后续断言
                    pass
    raise AssertionError("spec 中未找到 _datas 列表")


class VersionModuleTest(unittest.TestCase):
    """item 16：version.py 的版本常量契约。"""

    def test_version_tuple_is_0101(self):
        import qt_client.version as v
        self.assertEqual(v.VERSION_TUPLE, (0, 1, 0, 1))
        self.assertEqual(v.get_version_tuple(), (0, 1, 0, 1))

    def test_version_string_is_alpha1(self):
        import qt_client.version as v
        self.assertEqual(v.__version__, "0.1.0-alpha.1")
        self.assertEqual(v.get_version_str(), "0.1.0-alpha.1")
        self.assertEqual(v.VERSION_STR, "0.1.0-alpha.1")

    def test_version_tuple_is_written_literal_in_source(self):
        """VERSION_TUPLE 在源码里按字面写死 (0,1,0,1)（防被别处 import 绕过）。"""
        with open(_VERSION_PATH, encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source)
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", "") == "VERSION_TUPLE"
                            for t in node.targets)):
                value = ast.literal_eval(node.value)
                self.assertEqual(value, (0, 1, 0, 1))
                break
        else:
            self.fail("version.py 中未找到 VERSION_TUPLE 赋值")

    def test_app_slug_no_spaces(self):
        """APP_SLUG 无空格（用于 EXE/ZIP 文件名）。"""
        import qt_client.version as v
        self.assertNotIn(" ", v.APP_SLUG)
        self.assertTrue(v.APP_SLUG.isalnum() or
                        re.fullmatch(r"[A-Za-z0-9_-]+", v.APP_SLUG) is not None)


@unittest.skipUnless(os.path.exists(_SPEC_PATH), "PhoneVisionLab.spec 尚不存在")
class SpecConfigTest(unittest.TestCase):
    """item 17/18：spec 的资源携带与"无本机绝对路径"。"""

    def test_spec_datas_include_qss(self):
        """datas 应携带 style.qss。"""
        datas = _spec_datas()
        qss_src = [s for s, _ in datas if s.endswith("style.qss")]
        self.assertTrue(qss_src, f"datas 应包含 style.qss，实得 {datas}")
        self.assertTrue(os.path.basename(qss_src[0]) == "style.qss")
        # 目标布局为 qt_client/（与源码包镜像，resources.resource_path 解析依赖它）
        dest = [d for s, d in datas if s.endswith("style.qss")]
        self.assertTrue(all(d == "qt_client" for d in dest),
                        f"style.qss 目标应为 qt_client/，实得 {dest}")

    def test_spec_datas_include_icon_and_assets(self):
        """datas 应携带应用图标 PNG（resources.icon_path 用）。"""
        datas = _spec_datas()
        png_src = [s for s, _ in datas if s.endswith("app.png")]
        self.assertTrue(png_src, f"datas 应包含 app.png，实得 {datas}")
        dest = [d for s, d in datas if s.endswith("app.png")]
        self.assertTrue(all(d == os.path.join("qt_client", "assets")
                            for d in dest),
                        f"app.png 目标应为 qt_client/assets，实得 {dest}")

    def test_spec_icon_points_to_assets(self):
        """spec 的 EXE 图标指向 packaging/assets/app.ico。"""
        src = _spec_source()
        self.assertIn("app.ico", src)
        self.assertRegex(
            src, r"_icon\s*=\s*os\.path\.join\(\s*_PKG\s*,\s*[\"']app\.ico[\"']\s*\)")

    def test_spec_has_no_absolute_drive_paths(self):
        """spec 不含本机绝对路径（D:\\、D:/ 等盘符）。

        SPECPATH 是 PyInstaller 注入的仓库无关常量（合法），只检查盘符路径与
        本机用户名/主目录泄漏。
        """
        src = _spec_source()
        self.assertIsNone(re.search(r"[A-Za-z]:[\\\\/]", src),
                          "spec 不应包含盘符绝对路径")
        self.assertNotIn("22917", src, "spec 不应含本机用户名")
        self.assertNotIn("Sansi", src, "spec 不应含本机用户名")
        self.assertNotIn(os.path.expanduser("~").lower(), src.lower(),
                         "spec 不应含用户主目录路径")

    def test_spec_console_false(self):
        """windowed EXE：console=False（双击不弹终端）。"""
        self.assertIn("console=False", _spec_source())

    def test_spec_excludes_tkinter_legacy(self):
        """spec 排除 Tkinter 旧链与测试/截图目录。"""
        src = _spec_source()
        for token in ("app_gui", "legacy_main", "tests", "captures", "tkinter"):
            self.assertIn(f'"{token}"', src, f"spec 应排除 {token}")


@unittest.skipUnless(os.path.exists(_PS1_PATH), "build_windows.ps1 尚不存在")
class BuildScriptTest(unittest.TestCase):
    """item 19：build_windows.ps1 的删除目标严格受限。"""

    def test_cleanup_targets_strictly_limited(self):
        """清理只允许删除 pc-client\\build 与 pc-client\\dist，且限定在仓库根之下。

        静态检查两层守卫：
          1. 清理目标列表只含 $BuildDir 与 $DistDir（都是 pc-client 根下的
             build/dist，见脚本第 150-162 行）；
          2. 删除前校验 isUnderRepo + isAllowedName，超出即 throw。
        """
        src = _ps1_source()
        # 清理循环只遍历两个目标
        self.assertIn("foreach ($target in @($BuildDir, $DistDir))", src)
        # 双保险守卫存在且同时要求"位于仓库根下"与"名字是 build/dist"
        self.assertIn("$isUnderRepo", src)
        self.assertIn("$isAllowedName", src)
        self.assertIn("Remove-Item -Recurse -Force $target", src)
        # 不允许删除任意目标：仅通过白名单组合
        self.assertIn('EndsWith("\\build")', src)
        self.assertIn('EndsWith("\\dist")', src)

    def test_no_delete_outside_build_dist(self):
        """ps1 中所有 Remove-Item 目录删除都只指向 build/dist/artifacts\\windows。"""
        src = _ps1_source()
        # 收集所有 -Recurse 强制删除的目标变量/路径
        removed = re.findall(
            r"Remove-Item\s+-Recurse\s+-Force\s+(\S+)", src)
        for target in removed:
            self.assertIn(target, ("$target", "$BuildDir", "$DistDir"),
                          f"禁止递归删除非 build/dist 目标: {target}")
        # artifacts\\windows 只做 ZIP/哈希写入，不允许递归删除
        self.assertNotIn("-Recurse -Force $Artifacts", src)
        # ZIP 清理是单文件，明确仅限 $ZipPath
        zip_removes = re.findall(
            r"Remove-Item\s+(-Force\s+)?\$ZipPath", src)
        self.assertTrue(zip_removes, "ps1 应清理旧的 $ZipPath")

    def test_script_has_no_absolute_paths(self):
        """ps1 不含本机绝对路径/用户名。"""
        src = _ps1_source()
        self.assertIsNone(re.search(r"[A-Za-z]:[\\\\/]", src),
                          "ps1 不应包含盘符绝对路径")
        self.assertNotIn("22917", src)
        self.assertNotIn("Sansi", src)
        self.assertNotIn("C:\\Users", src)

    def test_artifacts_path_is_repo_relative(self):
        """artifacts 指向仓库根下 artifacts\\windows（相对推导）。"""
        src = _ps1_source()
        self.assertIn('"artifacts\\windows"', src)


class VersionFlagTest(unittest.TestCase):
    """item 15：main.py 的 --version 打印 0.1.0-alpha.1。

    依赖 qt_client.main 已接入 --version（另一 agent 合入）→ 未接入时 skip。
    """

    def _wired(self):
        import qt_client.main as qm
        parser = qm.parse_args(["--help"]) if False else None
        del parser
        # 直接检查 parse_args 是否注册了 --version：解析 [--version] 应触发
        # 打印并以 0 退出（argparse action='version'）。
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                self.qm.parse_args(["--version"])
            return False, ""  # 未抛 SystemExit → 未接入 version action
        except SystemExit as e:
            return (e.code == 0), buf.getvalue()

    def setUp(self):
        import qt_client.main as qm
        self.qm = qm

    def test_version_flag_prints_alpha1(self):
        """--version 打印 0.1.0-alpha.1 并以 0 退出。"""
        wired, out = self._wired()
        if not wired:
            self.skipTest("qt_client.main 未接入 --version（等待源码 agent）")
        self.assertIn("0.1.0-alpha.1", out,
                      f"--version 输出应含版本号，实得 {out!r}")


def _ps1_source() -> str:
    with open(_PS1_PATH, encoding="utf-8") as fh:
        return fh.read()


if __name__ == "__main__":
    unittest.main()
