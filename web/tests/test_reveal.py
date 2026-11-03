"""
滚动浮现动效的静态契约测试（无浏览器、无 Node）。

为什么需要这组断言：
  动效最危险的失败模式不是"不好看"，而是**内容看不见**——
  一旦 CSS 直接 `[data-reveal]{opacity:0}` 而没有 JS 兜底，脚本失败/被拦截/
  用户禁用 JS 时，整页文字会永久隐形。这里把安全网钉死：
    1. 隐藏只在 <html class="js-reveal"> 下生效；
    2. 减少动效（prefers-reduced-motion）与打印时不隐藏；
    3. 宣传页与工作台都引用了 reveal 的 CSS/JS，且 head 里有关闭开关的内联脚本；
    4. 单页应用在切路由时 reset()、渲染后 scan()，否则观察器会持有已移除的 DOM。
"""
import os
import re
import unittest

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC = os.path.join(_WEB, "static")


def _read(name):
    with open(os.path.join(_STATIC, name), encoding="utf-8") as fh:
        return fh.read()


class RevealContractTest(unittest.TestCase):
    """动效必须"默认可见、渐进增强"。"""

    def test_static_page_links_reveal_assets(self):
        html = _read("welcome.html")
        self.assertIn('href="/reveal.css"', html,
                      "welcome.html 应引用 reveal.css")
        self.assertIn('src="/reveal.js"', html,
                      "welcome.html 应引用 reveal.js")

    def test_spa_shell_links_reveal_assets(self):
        html = _read("index.html")
        self.assertIn('href="/reveal.css"', html,
                      "index.html 应引用 reveal.css")
        self.assertIn('src="/reveal.js"', html,
                      "index.html 应引用 reveal.js")
        # reveal.js 必须在页面模块与 app.js 之前加载，否则 app.js 调用 scan 时还没有实现
        reveal_at = html.index('src="/reveal.js"')
        app_at = html.index('src="/app.js"')
        self.assertLess(reveal_at, app_at, "reveal.js 必须先于 app.js 加载")

    def test_inline_switch_runs_before_paint(self):
        """开关脚本必须在 <head> 内，且尊重减少动效与能力检测。"""
        for name in ("welcome.html", "index.html"):
            head = _read(name).split("</head>")[0]
            self.assertIn("js-reveal", head,
                          f"{name} 的 head 应有添加 js-reveal 的开关脚本")
            self.assertIn("prefers-reduced-motion", head,
                          f"{name} 的开关脚本必须尊重 prefers-reduced-motion")
            self.assertIn("IntersectionObserver", head,
                          f"{name} 的开关脚本必须检测 IntersectionObserver")

    def test_css_hides_only_under_js_reveal(self):
        css = _read("reveal.css")
        self.assertRegex(
            css, r"\.js-reveal\s+\[data-reveal\]\s*\{[^}]*opacity:\s*0",
            "隐藏规则必须以 .js-reveal 为前缀")
        bare = re.findall(
            r"(?<!\.js-reveal )\[data-reveal\][^{]*\{[^}]*opacity:\s*0", css)
        self.assertEqual([], bare,
                         "不允许无条件隐藏 [data-reveal]：脚本失效时内容会永久不可见")

    def test_css_has_reduced_motion_and_print_fallbacks(self):
        css = _read("reveal.css")
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("@media print", css)
        reduced = css.split("prefers-reduced-motion", 1)[1]
        self.assertIn("opacity: 1", reduced.split("}", 2)[0] + "}",
                      "减少动效分支必须让元素直接可见")
        printed = css.split("@media print", 1)[1]
        self.assertIn("opacity: 1", printed, "打印分支必须让元素直接可见")

    def test_static_page_targets_and_groups_exist(self):
        html = _read("welcome.html")
        targets = len(re.findall(r"data-reveal(?=[\s>])", html))
        groups = len(re.findall(r"data-reveal-group", html))
        self.assertGreaterEqual(targets, 20,
                                f"宣传页浮现目标过少（{targets}）")
        self.assertGreaterEqual(groups, 5,
                                f"宣传页分组过少（{groups}），错峰无法覆盖各章节")

    def test_spa_calls_scan_and_reset(self):
        app = _read("app.js")
        self.assertIn("PVL_REVEAL.scan(", app,
                      "app.js 应在每次 render 后调用 scan()，否则新页面不会有动效")
        self.assertIn("PVL_REVEAL.reset(", app,
                      "app.js 应在切路由时调用 reset()，否则观察器持有已移除的 DOM")

    def test_auto_mode_sets_attribute(self):
        """自动模式必须把 data-reveal 写到元素上，否则 CSS 不隐藏、动效是假的。"""
        js = _read("reveal.js")
        self.assertIn("setAttribute('data-reveal'", js)
        self.assertIn("unobserve", js)
        self.assertIn("setTimeout", js, "应有兜底定时器，避免内容永久隐藏")


if __name__ == "__main__":
    unittest.main()
