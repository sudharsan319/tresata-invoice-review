"""Render the written brief to a four-page PDF using local LibreOffice."""
from pathlib import Path
import re
import subprocess

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "WRITTEN_BRIEF.md"
HTML = ROOT / "WRITTEN_BRIEF.html"

subprocess.run(["dot", "-Tpng", str(ROOT / "architecture.dot"), "-o", str(ROOT / "architecture.png")], check=True)
body = MarkdownIt("commonmark").enable("table").render(SOURCE.read_text())
body = re.sub(r'<pre><code class="language-mermaid">.*?</code></pre>',
              '<p class="diagram"><img src="architecture.png" alt="Invoice and PO review architecture"></p>',
              body, count=1, flags=re.S)
for heading in ("2. Solution design", "3. Prototype evidence, risks, and next questions", "Appendix: What I added beyond AI"):
    body = body.replace(f"<h2>{heading}</h2>", f'<h2 class="new-page">{heading}</h2>')

HTML.write_text("""<!doctype html>
<html><head><meta charset="utf-8"><title>Invoice and Purchase Order Review Written Brief</title>
<style>
@page { size: A4; margin: 13mm 15mm 13mm 15mm; }
body { font-family: 'Liberation Sans', Arial, sans-serif; color: #172331; font-size: 9.3pt; line-height: 1.28; }
h1 { color: #12364d; font-size: 17pt; margin: 0 0 4mm 0; }
h2 { color: #154963; font-size: 12pt; margin: 4mm 0 2mm 0; }
h2.new-page { page-break-before: always; margin-top: 0; }
p { margin: 0 0 2.8mm 0; }
strong { color: #102f45; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 3mm 0; font-size: 8.2pt; }
th { color: #143d55; background: #e8f2f7; text-align: left; }
td, th { border: 0.45pt solid #cad5dc; padding: 1.15mm 1.5mm; vertical-align: top; }
tr { page-break-inside: avoid; }
ol { margin: 1mm 0 2mm 5mm; padding-left: 3mm; }
li { margin-bottom: 1.6mm; }
code { font-family: 'Liberation Mono', monospace; font-size: 8.5pt; }
.diagram { text-align: center; margin: 3mm 0; }
.diagram img { width: 100%; max-height: 55mm; object-fit: contain; }
</style></head><body>""" + body + "</body></html>")
subprocess.run(["libreoffice", "-env:UserInstallation=file:///tmp/tresata-brief-lo-profile",
                "--headless", "--convert-to", "pdf", "--outdir", str(ROOT), str(HTML)], check=True)
