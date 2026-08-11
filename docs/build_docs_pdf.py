"""Render the project Markdown docs to PDF using PyMuPDF's Story engine.

No external tools (pandoc/wkhtmltopdf) required. Converts a known-subset of
Markdown -> HTML -> paginated A4 PDF. Run:  python docs/build_docs_pdf.py
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

import fitz  # PyMuPDF

DOCS = Path(__file__).resolve().parent
SOURCES = ["PROJECT_SUMMARY.md", "USER_GUIDE.md"]

CSS = """
* { font-family: sans-serif; }
h1 { font-size: 20pt; color: #0b3d66; margin: 0 0 6pt 0; }
h2 { font-size: 14pt; color: #0e5aa7; margin: 14pt 0 4pt 0; }
h3 { font-size: 11.5pt; color: #143b5e; margin: 10pt 0 3pt 0; }
p  { font-size: 10pt; color: #1f2933; margin: 4pt 0; line-height: 1.4; }
li { font-size: 10pt; color: #1f2933; margin: 2pt 0; line-height: 1.35; }
b, strong { color: #0b2540; }
code { font-family: monospace; font-size: 9pt; background: #eef2f6; color: #0b3d66; }
pre { font-family: monospace; font-size: 8.5pt; background: #0f1720; color: #d6e2f0;
      padding: 8pt; margin: 6pt 0; }
blockquote { color: #475569; background: #f1f5f9; padding: 6pt 10pt; margin: 6pt 0; }
hr { margin: 10pt 0; }
table { border: 1px solid #cbd5e1; }
th { background: #0e5aa7; color: #ffffff; font-size: 9pt; padding: 4pt 6pt; text-align: left; }
td { border: 1px solid #cbd5e1; font-size: 9pt; padding: 4pt 6pt; color: #1f2933; }
"""


def _inline(text: str) -> str:
    text = _html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    return text


def _table(rows: list[str]) -> str:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ["<table>", "<tr>"]
    out += [f"<th>{_inline(h)}</th>" for h in head]
    out.append("</tr>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
    out.append("</table>")
    return "".join(out)


def md_to_html(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # fenced code
        if line.strip().startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(_html.escape(lines[i]))
                i += 1
            out.append("<pre>" + "\n".join(block) + "</pre>")
            i += 1
            continue

        # table (needs header + separator)
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            block = [line]
            i += 1
            block.append(lines[i])
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block))
            continue

        if not line.strip():
            i += 1
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        if re.match(r"^---+\s*$", line):
            out.append("<hr/>")
            i += 1
            continue

        if line.strip().startswith(">"):
            out.append(f"<blockquote>{_inline(line.strip().lstrip('>').strip())}</blockquote>")
            i += 1
            continue

        # unordered list
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                content = re.sub(r"^\s*[-*]\s+", "", lines[i])
                items.append("<li>" + _inline(content) + "</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        # ordered list
        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                content = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                items.append("<li>" + _inline(content) + "</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        out.append(f"<p>{_inline(line)}</p>")
        i += 1

    return "<html><body>" + "".join(out) + "</body></html>"


def render(md_path: Path, pdf_path: Path) -> None:
    html_doc = md_to_html(md_path.read_text(encoding="utf-8"))
    story = fitz.Story(html=html_doc, user_css=CSS)
    writer = fitz.DocumentWriter(str(pdf_path))
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (40, 46, -40, -46)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()


if __name__ == "__main__":
    for name in SOURCES:
        src = DOCS / name
        pdf = DOCS / (src.stem + ".pdf")
        render(src, pdf)
        print(f"OK  {src.name}  ->  {pdf.name}  ({pdf.stat().st_size // 1024} KB)")
