"""Web 原型静态检查：链接、锚点、重复 id、未定义 class。

用法：python tools/check_prototype.py
"""
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ["index.html", "learn.html", "lesson.html", "lab.html", "projects.html"]


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.classes, self.links, self.stack = [], set(), [], []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("id"):
            self.ids.append(d["id"])
        for c in (d.get("class") or "").split():
            self.classes.add(c)
        if tag == "a" and d.get("href"):
            self.links.append(d["href"])
        if tag not in ("meta", "link", "img", "br", "hr", "input", "source"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main():
    css = ""
    for base, _dirs, files in os.walk(os.path.join(ROOT, "assets", "css")):
        for name in files:
            if name.endswith(".css"):
                css += read(os.path.join(base, name))
    defined = set(re.findall(r"\.([A-Za-z][\w-]*)", css))

    pages, errors, warns = {}, [], []
    for page in PAGES:
        path = os.path.join(ROOT, page)
        if not os.path.exists(path):
            errors.append(f"缺页面：{page}")
            continue
        p = Page()
        p.feed(read(path))
        pages[page] = p
        dup = {i for i in p.ids if p.ids.count(i) > 1}
        if dup:
            errors.append(f"{page} 重复 id：{sorted(dup)}")
        if p.stack:
            warns.append(f"{page} 可能未闭合标签：{p.stack[-4:]}")

    for page, p in pages.items():
        for href in p.links:
            if href.startswith(("http://", "https://", "mailto:", "javascript:")):
                continue
            if href.startswith("#"):
                if href != "#" and href[1:] not in p.ids:
                    errors.append(f"{page} 页内锚点不存在：{href}")
                continue
            target, _, frag = href.partition("#")
            tpath = os.path.join(ROOT, target)
            if not os.path.exists(tpath):
                errors.append(f"{page} 链接目标不存在：{href}")
                continue
            if frag and target in pages:
                if frag not in pages[target].ids:
                    errors.append(f"{page} 跨页锚点不存在：{href}")
            elif frag:
                tp = Page()
                tp.feed(read(tpath))
                if frag not in tp.ids:
                    errors.append(f"{page} 跨页锚点不存在：{href}")

    for page, p in pages.items():
        unknown = sorted(c for c in p.classes if c not in defined)
        if unknown:
            warns.append(f"{page} 未在 CSS 中定义的 class：{unknown}")

    print(f"页面：{', '.join(sorted(pages))}")
    print(f"CSS class 定义数：{len(defined)}")
    for w in warns:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print(f"\n结果：{len(errors)} 个错误 / {len(warns)} 个警告")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
