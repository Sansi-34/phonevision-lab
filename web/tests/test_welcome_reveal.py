"""
宣传页「滚动浮现」动效的静态契约测试（无浏览器、无 Node）。

为什么需要这组断言：
  动效最危险的失败模式不是"不好看"，而是**内容看不见**——
  一旦 CSS 直接 `[data-reveal]{opacity:0}` 而没有 JS 兜底，脚本失败/被拦截/
  用户禁用 JS 时，整页文字会永久隐形。这里把三条安全网钉死：
    1. 隐藏只在 <html class="js-reveal"> 下生效；
    2. 减少动效（prefers-reduced-motion）与打印时不隐藏；
    3. 页面确实引用了 reveal 的 CSS/JS，且 head 里有关闭开关的内联脚本。
"""
import os
import re
import unittest

_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC = os.path.join(_WEB, "static")


def _read(name):
    with open(os.path.join(_STATIC, name), encoding="utf-8") as fh:
        return fh.read()


class WelcomeRevealContractTest(unittest.TestCase):
    """宣传页动效必须"默认可见、渐进增强"。"""

    def test_page_links_reveal_assets(self):
        html = _read("welcome.html")
        self.assertIn('href="/welcome-reveal.css"', html,
                      "welcome.html 应引用 welcome-reveal.css")
        self.assertIn('src="/welcome-reveal.js"', html,
                      "welcome.html 应引用 welcome-reveal.js")

    def test_inline_switch_runs_before_paint(self):
        """开关脚本必须在 <head> 内、且在样式表之后仍有同步执行机会。"""
        html = _read("welcome.html")
        head = html.split("</head>")[0]
        self.assertIn("js-reveal", head,
                      "head 内应有添加 js-reveal 的开关脚本（否则首帧会先显示再隐藏）")
        self.assertIn("prefers-reduced-motion", head,
                      "开关脚本必须尊重 prefers-reduced-motion")
        self.assertIn("IntersectionObserver", head,
                      "开关脚本必须检测 IntersectionObserver 支持")

    def test_css_hides_only_under_js_reveal(self):
        css = _read("welcome-reveal.css")
        # 必须有 .js-reveal 前缀的隐藏规则
        self.assertRegex(
            css, r"\.js-reveal\s+\[data-reveal\]\s*\{[^}]*opacity:\s*0",
            "隐藏规则必须以 .js-reveal 为前缀")
        # 不允许出现"裸"的 [data-reveal] 隐藏规则（无 .js-reveal 前缀）
        bare = re.findall(r"(?<!\.js-reveal )\[data-reveal\][^{]*\{[^}]*opacity:\s*0", css)
        self.assertEqual([], bare,
                         "不允许无条件隐藏 [data-reveal]：脚本失效时内容会永久不可见")

    def test_css_has_reduced_motion_and_print_fallbacks(self):
        css = _read("welcome-reveal.css")
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("@media print", css)
        # 两处兜底都必须把 opacity 恢复为 1
        reduced = css.split("prefers-reduced-motion", 1)[1]
        self.assertIn("opacity: 1", reduced.split("}", 2)[0] + "}", 
                      "减少动效分支必须让元素直接可见")
        printed = css.split("@media print", 1)[1]
        self.assertIn("opacity: 1", printed, "打印分支必须让元素直接可见")

    def test_reveal_targets_and_groups_exist(self):
        html = _read("welcome.html")
        targets = len(re.findall(r"data-reveal(?=[\s>])", html))
        groups = len(re.findall(r"data-reveal-group", html))
        self.assertGreaterEqual(targets, 20,
                                f"浮现目标过少（{targets}），页面大部分文字不会动")
        self.assertGreaterEqual(groups, 5,
                                f"分组过少（{groups}），错峰效果无法覆盖各章节")

    def test_js_unobserves_after_reveal(self):
        """浮现后必须 unobserve：否则来回滚动会反复闪，也浪费观察器。"""
        js = _read("welcome-reveal.js")
        self.assertIn("unobserve", js)
        self.assertIn("is-visible", js)
        # 必须有兜底：即使观察器被节流，也不能让内容一直隐藏
        self.assertIn("setTimeout", js, "应有兜底定时器，避免内容永久隐藏")


if __name__ == "__main__":
    unittest.main()
