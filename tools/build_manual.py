"""docs/manual/src/*.html を連結して docs/manual/index.html を作る。目次は h2/h3 から自動生成。

    python tools/build_manual.py
"""

import glob
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(REPO, "docs", "manual", "src")
OUT = os.path.join(REPO, "docs", "manual", "index.html")
IMG = os.path.join(REPO, "docs", "manual", "img")

parts = sorted(glob.glob(os.path.join(SRC, "[0-9][0-9]*.html")))
head = open(parts[0], encoding="utf-8").read()
foot = open(parts[-1], encoding="utf-8").read()
body = "".join(open(p, encoding="utf-8").read() for p in parts[1:-1])

# 目次生成
toc = ["<ul>"]
open_h2 = False
for m in re.finditer(r"<h([23]) id=\"([^\"]+)\"[^>]*>(.*?)</h\1>", body, re.S):
    level, hid, text = m.group(1), m.group(2), m.group(3)
    text = re.sub(r"<span class=\"num\">.*?</span>", "", text)
    text = re.sub(r"<[^>]+>", "", text).strip()
    if level == "2":
        if open_h2:
            toc.append("</ul></li>")
        toc.append(f'<li><a href="#{hid}">{text}</a><ul>')
        open_h2 = True
    else:
        toc.append(f'<li><a href="#{hid}">{text}</a></li>')
if open_h2:
    toc.append("</ul></li>")
toc.append("</ul>")
html = head.replace("<!--TOC-->", "\n".join(toc)) + body + foot

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

# 画像参照チェック
missing = []
for m in re.finditer(r"<img[^>]+src=\"([^\"]+)\"", html):
    src = m.group(1)
    if not os.path.exists(os.path.join(os.path.dirname(OUT), src)):
        missing.append(src)
# アンカーチェック
ids = set(re.findall(r"id=\"([^\"]+)\"", html))
badlinks = sorted({h for h in re.findall(r"href=\"#([^\"]+)\"", html) if h not in ids})
print(f"wrote {OUT} ({len(html)//1024} KB), h2/h3 = {len(toc)-2}")
print("missing images:", missing or "none")
print("broken anchors:", badlinks or "none")
sys.exit(1 if (missing or badlinks) else 0)
