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
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Guia de treinamento de ações personalizadas · Microduck Studio</title>
  <link rel="icon" href="/duck.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/styles.css">
  <link rel="stylesheet" href="/guide.css">
</head>
<body class="guide-page">
  <a class="skip-guide" href="#guide-content">Ir para o conteúdo</a>
  <header class="guide-top">
    <a class="brand" href="/#/workspace"><img src="/duck.svg" width="26" height="26" alt=""><span>Studio<small>Guia de treinamento</small></span></a>
    <a class="btn small" href="/#/workspace">Voltar ao Training Studio</a>
  </header>
  <div class="guide-layout">
    <aside class="guide-index"><nav aria-label="Índice do guia"><b>Ações personalizadas</b>__TOC__</nav><a class="guide-source" href="/custom-actions.md" download>Baixar documento Markdown ↓</a></aside>
    <main id="guide-content" class="guide-content"><div class="guide-kicker">MICRODUCK / Da ideia ao movimento</div>__CONTENT__</main>
  </div>
  <footer class="guide-bottom">Estas instruções se baseiam no ambiente de treinamento fixado neste repositório. Novos movimentos só podem entrar nas receitas após adaptação e validação.</footer>
</body>
</html>
""".replace("__TOC__", parser.toc).replace("__CONTENT__", content)
(WEB / "guide.html").write_text(page, encoding="utf-8")
print("Generated web/guide.html from web/custom-actions.md")
