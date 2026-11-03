"""用 Playwright 对原型做自动验收：溢出、控制台错误、关键交互。

前置：在 web-prototype 目录启动静态服务器（本脚本自行处理）。
用法：python tools/verify_ui.py
"""
import contextlib
import http.server
import os
import socketserver
import sys
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8765
WIDTHS = [1440, 1280, 1024, 768, 390]
PAGES = ["index.html", "learn.html", "lesson.html", "lab.html", "projects.html"]

OVERFLOW_JS = """() => {
  const vw = document.documentElement.clientWidth;
  const bad = [];
  document.querySelectorAll('body *').forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed' || cs.display === 'none' || cs.visibility === 'hidden') return;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    if (r.right > vw + 1 || r.left < -1) {
      bad.push((el.tagName.toLowerCase()) + '.' + (el.className || '').toString().split(' ')[0]
        + ' [' + Math.round(r.left) + ',' + Math.round(r.right) + '] vw=' + vw);
    }
  });
  return { scrollW: document.documentElement.scrollWidth, vw, bad: bad.slice(0, 5) };
}"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    os.chdir(ROOT)
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    return httpd


def main():
    httpd = serve()
    problems, notes = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in WIDTHS:
                ctx = browser.new_context(viewport={"width": width, "height": 900})
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                        if m.type == "error" else None)
                for name in PAGES:
                    page.goto(f"http://127.0.0.1:{PORT}/{name}", wait_until="load")
                    res = page.evaluate(OVERFLOW_JS)
                    if res["scrollW"] > res["vw"] + 1:
                        problems.append(f"{name}@{width} 横向溢出 scrollW={res['scrollW']} vw={res['vw']} {res['bad']}")
                    elif res["bad"]:
                        notes.append(f"{name}@{width} 局部越界 {res['bad']}")
                if errors:
                    problems.append(f"@{width} 控制台错误 {errors[:3]}")
                ctx.close()

            # 交互验收
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{PORT}/index.html")

            page.click("[data-open-modal='connect-modal']")
            if not page.is_visible("#connect-modal"):
                problems.append("首页：连接弹窗未打开")
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
            if page.is_visible("#connect-modal"):
                problems.append("首页：Esc 未关闭弹窗")

            page.click("[data-nav='learn']")
            page.wait_for_load_state("load")
            if not page.url.endswith("learn.html"):
                problems.append("导航：点击「学习」未跳转")

            page.click("[data-filter='lab']")
            page.wait_for_timeout(120)
            lab_rows = page.eval_on_selector_all(
                "[data-course][data-course-type='lab']:not([hidden])", "els => els.length")
            know_rows = page.eval_on_selector_all(
                "[data-course][data-course-type='know']:not([hidden])", "els => els.length")
            notes.append(f"筛选：实验 {lab_rows} 条；关闭筛选前知识 {know_rows} 条（实验筛选应隐藏知识）")
            if lab_rows != 11:
                problems.append(f"筛选：实验课应为 11 条，实际 {lab_rows}")
            page.click("[data-filter='all']")

            page.goto(f"http://127.0.0.1:{PORT}/lesson.html")
            page.evaluate("localStorage.clear()")
            page.reload()
            label0 = page.inner_text("[data-mark-complete]")
            page.click("[data-mark-complete]")
            page.wait_for_timeout(120)
            label1 = page.inner_text("[data-mark-complete]")
            page.reload()
            label2 = page.inner_text("[data-mark-complete]")
            notes.append(f"课程完成：{label0} → {label1} → 刷新后 {label2}")
            if "已标记" not in label1 or "已标记" not in label2:
                problems.append("课程完成按钮状态未持久化")

            page.goto(f"http://127.0.0.1:{PORT}/lab.html")
            page.wait_for_timeout(400)
            page.click("[data-mode='canny']")
            page.wait_for_timeout(500)
            pressed = page.get_attribute("[data-mode='canny']", "aria-pressed")
            if pressed != "true":
                problems.append("实验台：Canny 模式未激活")
            blank = page.evaluate("""() => {
              const c = document.getElementById('lab-canvas');
              const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
              let nonBlack = 0;
              for (let i = 0; i < d.length; i += 4 * 97) { if (d[i] + d[i+1] + d[i+2] > 24) nonBlack++; }
              return nonBlack;
            }""")
            notes.append(f"实验台：Canny 画布非空采样点 {blank}")
            if blank < 20:
                problems.append("实验台：Canny 画布疑似空白")
            page.evaluate("""() => {
              const el = document.querySelector('#canny-low');
              el.value = 120;
              el.dispatchEvent(new Event('input', {bubbles: true}));
            }""")
            page.wait_for_timeout(200)
            out = page.inner_text("[data-output-for='canny-low']")
            if out.strip() != "120":
                problems.append(f"实验台：滑块数值未同步（{out}）")
            ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    print("== 备注 ==")
    for n in notes:
        print(" ·", n)
    print("\n== 问题 ==")
    if not problems:
        print(" 无")
    for p_ in problems:
        print(" !", p_)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
