"""
PhoneVision Lab — 正式入口切换测试（P0-4B）。

职责：验证"正式入口"改造：
  1. root main.py 委托 PySide6：import main 后加载 qt_client.main，且不加载
     app_gui / tkinter（Tkinter 旧链完全交给 legacy_main.py）。
  2. legacy_main.py 可解析原启动参数（--host / --stream-url / --port）。
  3. 三个 --help 都正常：main.py / qt_client.main / legacy_main.py 的 parse_args
     不抛异常，且 --help 打印 usage 并以 0 退出。
  4. qt_client.main 支持 main(argv=None) / parse_args(argv=None) / --lang。

为什么这样设计：
  - import 图断言用子进程 + 全新解释器验证（`import main` 后查 sys.modules）：
    同一个 unittest 进程里其他测试模块可能先 import 了 app_gui/legacy_main，
    共享 sys.modules 会误报；子进程隔离最可靠。
  - 关于 requests：旧版 root main.py 直接 `import requests` 自己实现 ping；
    新薄入口把它交给 connection.py（shared 连接层，legacy/PySide6 共用）。
    因此运行时 requests 必然经 connection 出现在 sys.modules 里，这不算泄漏。
    真正的契约是：main.py 源码自身不再 import requests/app_gui/tkinter——
    所以用"源码检查"断言薄入口不重复实现 ping、不碰 Tkinter 旧链。
  - --help 用 subprocess 验证真实 CLI：argparse 对 --help 打印 usage 后以 0 退出。
  - 不连网、不显示窗口：只测参数解析与 import 图，不触发 /ping 与 GUI 启动。
"""
import os
import subprocess
import sys
import unittest

_PC_CLIENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PC_CLIENT not in sys.path:
    sys.path.insert(0, _PC_CLIENT)

_MAIN_SOURCE = None


def _read_main_source() -> str:
    global _MAIN_SOURCE
    if _MAIN_SOURCE is None:
        with open(os.path.join(_PC_CLIENT, "main.py"), encoding="utf-8") as fh:
            _MAIN_SOURCE = fh.read()
    return _MAIN_SOURCE


def _run(args: list, cwd=_PC_CLIENT) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    # 子进程会打印中文。中文 Windows 的控制台默认是 GBK，父进程用 text=True
    # 按 locale 解码时会在读取线程里抛 UnicodeDecodeError，stdout 直接变成 None
    # （断言里随即报 "unsupported operand type(s) for +: 'NoneType' and 'str'"）。
    # 因此两侧都固定 UTF-8：子进程用 PYTHONIOENCODING，父进程显式 encoding。
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable] + args, cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)


def _run_help(argv: list) -> subprocess.CompletedProcess:
    """在 pc-client 下运行 `python <module> --help`，捕获 stdout/stderr。"""
    return _run(argv + ["--help"])


def _import_main_in_fresh_process() -> dict:
    """全新解释器 `import main`，返回关键模块是否被加载的标志字典。

    隔离性：不共享本进程 sys.modules，避免其他测试模块的预导入污染断言。
    """
    code = (
        "import sys; import main; import qt_client.main; "
        "mods = set(sys.modules); "
        "print('HAS_QT', 'qt_client.main' in mods); "
        "print('HAS_APP_GUI', 'app_gui' in mods); "
        "print('HAS_TK', 'tkinter' in mods); "
        "print('MAIN_CALLABLE', callable(main.main)); "
        "print('QT_IS_MAIN', qt_client.main.main is main.main)"
    )
    cp = _run(["-c", code])
    assert cp.returncode == 0, f"import main 失败: {cp.stderr}"
    flags = {}
    for line in cp.stdout.strip().splitlines():
        key, _, val = line.partition(" ")
        flags[key] = val == "True"
    return flags


@unittest.skipUnless(os.path.exists(os.path.join(_PC_CLIENT, "main.py")),
                     "root main.py 不存在")
class RootMainDelegateTest(unittest.TestCase):
    """root main.py 必须委托 PySide6，不碰 Tkinter 旧链。"""

    @classmethod
    def setUpClass(cls):
        cls.flags = _import_main_in_fresh_process()

    def test_root_main_delegates_to_qt_client(self):
        """import main 应加载 qt_client.main，且 main.main 就是 qt_client.main.main。"""
        self.assertTrue(self.flags["HAS_QT"], "import main 后 qt_client.main 应被加载")
        self.assertTrue(self.flags["QT_IS_MAIN"],
                        "root main.main 应就是 qt_client.main.main（薄委托）")

    def test_root_main_does_not_import_tkinter_chain(self):
        """import main 不加载 app_gui / tkinter（Tkinter 旧链留给 legacy_main）。"""
        self.assertFalse(self.flags["HAS_APP_GUI"], "import main 不应加载 app_gui")
        self.assertFalse(self.flags["HAS_TK"], "import main 不应加载 tkinter")

    def test_root_main_exposes_callable_main(self):
        """root main.py 暴露可调用的 main()（由 qt_client.main.main 转发）。"""
        self.assertTrue(self.flags["MAIN_CALLABLE"])

    def test_root_main_source_does_not_import_requests_or_app_gui(self):
        """main.py 实际代码（不含 docstring/注释）不 import requests/app_gui/tkinter。

        薄入口语义：URL/ping/GUI 全部交给 qt_client.main（经 connection.py）。
        docstring 里提到这些模块名（说明设计）不算真正 import，这里用"仅执行代码"
        判定，避免把注释文字误判为依赖。
        """
        source = _read_main_source()
        # 剥掉模块 docstring 与注释，只留实际执行的 import 语句
        code = source.split('"""', 2)[2]
        code = "\n".join(line for line in code.splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertNotIn("import requests", code,
                         "薄入口不应再直接 import requests（交给 connection.py）")
        self.assertNotIn("import app_gui", code, "薄入口不应 import app_gui")
        self.assertNotIn("import tkinter", code, "薄入口不应 import tkinter")
        self.assertNotIn("from app_gui", code, "薄入口不应 from app_gui import")

    def test_root_main_help_prints_usage(self):
        """root main.py 直接跑 --help 打印 usage（委托的 qt_client.main.parse_args）。"""
        cp = _run_help(["main.py"])
        self.assertEqual(cp.returncode, 0, f"main.py --help 退出码应为 0: {cp.stderr}")
        self.assertIn("--host", cp.stdout + cp.stderr)


class LegacyMainTest(unittest.TestCase):
    """legacy_main.py 保留原 Tkinter 入口语义。"""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(_PC_CLIENT, "legacy_main.py")):
            raise unittest.SkipTest("legacy_main.py 尚不存在（等待源码 agent）")
        import legacy_main
        cls.legacy = legacy_main

    def test_parses_host_and_port(self):
        args = self.legacy.parse_args(["--host", "192.168.2.14", "--port", "9090"])
        self.assertEqual(args.host, "192.168.2.14")
        self.assertEqual(args.port, 9090)

    def test_parses_stream_url(self):
        args = self.legacy.parse_args(["--stream-url", "http://192.168.2.14:8080/stream"])
        self.assertEqual(args.stream_url, "http://192.168.2.14:8080/stream")
        self.assertIsNone(args.host)

    def test_default_port_is_8080(self):
        args = self.legacy.parse_args(["--host", "192.168.2.14"])
        self.assertEqual(args.port, 8080)

    def test_host_and_stream_url_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self.legacy.parse_args(["--host", "1.2.3.4",
                                    "--stream-url", "http://x/stream"])

    def test_missing_connection_raises_system_exit(self):
        """互斥组 required：两者都不传时 argparse 应拒绝（SystemExit）。"""
        with self.assertRaises(SystemExit):
            self.legacy.parse_args([])

    def test_help_prints_usage(self):
        cp = _run_help(["legacy_main.py"])
        self.assertEqual(cp.returncode, 0)
        self.assertIn("--stream-url", cp.stdout + cp.stderr)


class QtClientMainTest(unittest.TestCase):
    """qt_client.main 正式入口：parse_args(argv)/main(argv)/--lang。"""

    def setUp(self):
        import qt_client.main
        self.qm = qt_client.main

    def test_parse_args_accepts_argv(self):
        args = self.qm.parse_args(["--host", "192.168.2.14"])
        self.assertEqual(args.host, "192.168.2.14")
        self.assertEqual(args.port, 8080)
        self.assertIsNone(args.lang)

    def test_parse_args_supports_lang(self):
        args = self.qm.parse_args(["--host", "1.2.3.4", "--lang", "en"])
        self.assertEqual(args.lang, "en")
        args2 = self.qm.parse_args(["--stream-url", "http://x/stream", "--lang", "zh-CN"])
        self.assertEqual(args2.lang, "zh-CN")

    def test_main_signature_accepts_argv(self):
        """main(argv=None) 可被 root main.py 直接转发调用。"""
        sig = self.qm.main.__code__.co_varnames
        self.assertIn("argv", sig)

    def test_help_prints_usage(self):
        cp = _run_help(["-m", "qt_client.main"])
        self.assertEqual(cp.returncode, 0)
        self.assertIn("--lang", cp.stdout + cp.stderr)

    def test_help_exit_codes_all_zero(self):
        """三个入口 --help 都以 0 退出（可被脚本/用户正常调用）。"""
        for argv in (["main.py"], ["legacy_main.py"], ["-m", "qt_client.main"]):
            with self.subTest(argv=argv):
                cp = _run_help(argv)
                self.assertEqual(cp.returncode, 0,
                                 f"{argv} --help 应正常退出 0: {cp.stderr}")
                out = cp.stdout + cp.stderr
                self.assertIn("--host", out, f"{argv} 应打印 usage")


if __name__ == "__main__":
    unittest.main()
