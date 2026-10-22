"""Rebuild the checked-in guide HTML. Authoring only: requires Python-Markdown.

    python -m pip install Markdown
    python dev/build-guide.py

The running application serves the generated file without this dependency.
"""
from pathlib import Path

import markdown


WEB = Path(__file__).resolve().parents[1] / "web"
source = (WEB / "custom-actions.md").read_text(encoding="utf-8")
parser = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"])
content = parser.convert(source)
page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>自定义动作训练指南 · Microduck Studio</title>
  <link rel="icon" href="/duck.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/styles.css">
  <link rel="stylesheet" href="/guide.css">
</head>
<body class="guide-page">
  <a class="skip-guide" href="#guide-content">跳到正文</a>
  <header class="guide-top">
    <a class="brand" href="/#/workspace"><img src="/duck.svg" width="26" height="26" alt=""><span>Studio<small>训练指南</small></span></a>
    <a class="btn small" href="/#/workspace">返回训练台</a>
  </header>
  <div class="guide-layout">
    <aside class="guide-index"><nav aria-label="指南目录"><b>自定义动作</b>__TOC__</nav><a class="guide-source" href="/custom-actions.md" download>下载 Markdown 文档 ↓</a></aside>
    <main id="guide-content" class="guide-content"><div class="guide-kicker">MICRODUCK / 从想法到动作</div>__CONTENT__</main>
  </div>
  <footer class="guide-bottom">说明基于本仓库冻结训练环境。新增动作须完成适配与验证后才能加入训练配方。</footer>
</body>
</html>
""".replace("__TOC__", parser.toc).replace("__CONTENT__", content)
(WEB / "guide.html").write_text(page, encoding="utf-8")
print("Generated web/guide.html from web/custom-actions.md")
