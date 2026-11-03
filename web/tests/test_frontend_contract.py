"""
PhoneVision Lab Web — 前端契约测试（无浏览器，验证 JS 模块可加载与注册）。

职责：用 Node + 最小 DOM 桩（tests/stub-render.js）验证：
  - 每个页面文件都向 window.PVL_PAGES 注册了 render 函数，并能在桩上跑完一次渲染；
  - courses.js 导出 8 课且字段完整（学习中心依赖这些字段）；
  - index.html 引用了全部脚本与样式，且 app.js 最后加载；
  - 交付目录没有残留临时调试脚本。

为什么不引入 Playwright/Puppeteer：
  - 前端是零构建的纯静态文件，项目不为测试拉一个几百 MB 的浏览器；
  - 这里拦住最常见的一类事故："整个文件语法错误 → 模块未注册 → 路由显示页面不存在"
    （本项目开发中真实发生过，由 lab.js/dataset.js 的多余 `);` 引起）；
  - 真实浏览器联调由开发者在本地完成，见 docs/web-platform.zh-CN.md。

桩的边界（诚实说明）：最小 DOM 桩只保证"能加载、能注册、render 不抛异常"，
不验证真实渲染结果、不联网、不模拟真实设备。
"""
import json
import os
import subprocess
import unittest

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC = os.path.join(_WEB, "static")
_TESTS = os.path.join(_WEB, "tests")
_STUB = os.path.join(_TESTS, "stub-render.js")

# 页面文件名 -> 期望注册的路由名（一个文件可注册多个路由）
PAGE_MODULES = {
    "home.js": ["home"],
    "learn.js": ["learn", "lesson"],
    "lab.js": ["lab"],
    "dataset.js": ["dataset"],
    "train.js": ["train"],
    "deploy.js": ["deploy"],
    "hardware.js": ["hardware"],
    "performance.js": ["performance"],
    "misc.js": ["progress", "help", "about"],
}


def _node(args, timeout=120):
    # encoding="utf-8" 必须显式指定：Windows 下 subprocess 默认用 GBK 解码，
    # 而 Node 输出的是 UTF-8（课程标题是中文），默认解码会抛 UnicodeDecodeError。
    return subprocess.run(["node"] + args, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout, cwd=_STATIC)


class FrontendModuleRegistrationTest(unittest.TestCase):
    """每个页面文件必须注册 render 函数，并能在桩上跑完一次渲染。"""

    def test_all_pages_register_and_render(self):
        for filename, expected_routes in PAGE_MODULES.items():
            with self.subTest(page=filename):
                path = os.path.join(_STATIC, "pages", filename)
                self.assertTrue(os.path.isfile(path), f"缺少页面文件: {filename}")
                result = _node([_STUB, filename])
                self.assertEqual(result.returncode, 0,
                                 f"{filename} 在桩环境执行失败: "
                                 f"{result.stderr[-500:]}")
                lines = [ln for ln in result.stdout.splitlines()
                         if ln.startswith("RESULTS:")]
                self.assertTrue(lines, f"{filename} 未输出渲染结果")
                results = json.loads(lines[-1][len("RESULTS:"):])
                registered = [item["page"] for item in results]
                for route in expected_routes:
                    self.assertIn(route, registered,
                                  f"{filename} 未注册路由 {route}（实际: {registered}）")
                for item in results:
                    self.assertTrue(item["ok"],
                                    f"{filename} 渲染 {item['page']} 失败: "
                                    f"{item.get('error')}")

    def test_app_and_courses_load_without_syntax_error(self):
        """app.js / courses.js 必须能加载（语法错误会连带整个前端失效）。"""
        for filename in ("app.js", "courses.js"):
            with self.subTest(file=filename):
                result = _node(["--check", os.path.join(_STATIC, filename)])
                self.assertEqual(result.returncode, 0,
                                 f"{filename} 语法检查失败: {result.stderr[-400:]}")

    def test_index_html_references_all_scripts_and_loads_app_last(self):
        with open(os.path.join(_STATIC, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        for filename in ("courses.js", "app.js", "styles.css", "pages.css"):
            self.assertIn(filename, html, f"index.html 未引用 {filename}")
        for filename in PAGE_MODULES:
            self.assertIn(f"pages/{filename}", html,
                          f"index.html 未引用 pages/{filename}")
        # app.js 必须最后加载：页面模块先注册，内核后启动
        app_pos = html.rindex("/app.js")
        for filename in PAGE_MODULES:
            self.assertLess(html.index(f"pages/{filename}"), app_pos,
                            f"pages/{filename} 必须在 app.js 之前加载")

    def test_no_temp_files_left_in_static(self):
        """交付目录不得残留临时调试脚本（开发中多次出现，故设为门禁）。"""
        leftovers = []
        for base, _dirs, files in os.walk(_STATIC):
            for name in files:
                lowered = name.lower()
                if ("tmp" in lowered or lowered.startswith("zz-")
                        or name.startswith(".")):
                    leftovers.append(os.path.join(base, name))
        self.assertEqual(leftovers, [], f"发现临时/隐藏文件: {leftovers}")

    def test_courses_and_pages_do_not_import_modules(self):
        """前端零构建：不得出现 import/export（浏览器 script 标签直接加载）。"""
        for base, _dirs, files in os.walk(_STATIC):
            for name in files:
                if not name.endswith(".js"):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        stripped = line.strip()
                        if stripped.startswith("import ") or \
                                stripped.startswith("export "):
                            self.fail(f"{path}:{lineno} 不允许使用 ES 模块语法")


class CoursesContractTest(unittest.TestCase):
    """课程数据契约（学习中心与课程详情页依赖这些字段）。"""

    @classmethod
    def setUpClass(cls):
        # 用独立脚本文件而不是 node -e 内联：内联字符串在 Windows/PowerShell 下
        # 容易被引号转义搞坏（本项目实际踩过），独立文件可单独 node --check 自检。
        script = os.path.join(_TESTS, "stub-courses.js")
        result = subprocess.run(["node", script], capture_output=True, text=True,
                                encoding="utf-8", timeout=60, cwd=_STATIC)
        assert result.returncode == 0, f"courses.js 读取失败: {result.stderr}"
        cls.data = json.loads(result.stdout.strip().splitlines()[-1])

    def test_eight_lessons_in_order(self):
        self.assertEqual(self.data["count"], 8)
        self.assertEqual(self.data["order"],
                         ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"])

    def test_course_map_points_to_same_objects(self):
        self.assertTrue(self.data["mapMatches"],
                        "PVL_COURSE_MAP 必须与 PVL_COURSES 指向同一批对象")

    def test_every_lesson_has_required_sections(self):
        for index, count in enumerate(self.data["goals"]):
            self.assertGreaterEqual(count, 3, f"第 {index + 1} 课学习目标不足")
        for index, count in enumerate(self.data["sections"]):
            self.assertGreaterEqual(count, 2, f"第 {index + 1} 课章节不足")
        for index, count in enumerate(self.data["checklists"]):
            self.assertGreaterEqual(count, 2, f"第 {index + 1} 课完成标志不足")
        for index, count in enumerate(self.data["prereqs"]):
            self.assertGreaterEqual(count, 1, f"第 {index + 1} 课缺少准备说明")

    def test_demo_types_map_to_real_routes(self):
        allowed = {"none", "image-processing", "dataset", "training", "deploy",
                   "hardware", "performance"}
        for index, demo in enumerate(self.data["demos"]):
            self.assertIn(demo, allowed, f"第 {index + 1} 课 demo.type 非法: {demo}")

    def test_minutes_are_reading_estimates(self):
        """minutes 是预计阅读时长，不能与性能指标混淆。"""
        for index, minutes in enumerate(self.data["minutes"]):
            self.assertIsInstance(minutes, int)
            self.assertGreater(minutes, 0)
            self.assertLess(minutes, 60, "单课阅读时长不应超过 60 分钟")


if __name__ == "__main__":
    unittest.main()
