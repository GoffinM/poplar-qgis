"""Convert the help pages (docs/aide/*.md) into HTML for the plugin (plugin/poplar/help/<language>/).

A small Markdown subset is enough for these pages: headings, paragraphs,
lists, tables, code blocks, quotes, bold, italic, inline code and links.
Run it after editing the help: python tools/build_help.py
"""

import html
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = {"fr": os.path.join(REPO, "docs", "aide")}
TARGET = os.path.join(REPO, "plugin", "poplar", "help")

STYLE = """<style>
body { font-family: sans-serif; font-size: 13px; line-height: 1.5; margin: 12px 16px; }
h1 { font-size: 20px; } h2 { font-size: 16px; margin-top: 18px; } h3 { font-size: 14px; }
table { border-collapse: collapse; margin: 6px 0; } th, td { border: 1px solid #b9c6c4; padding: 3px 6px; }
th { background: #e7ecea; } code, pre { font-family: monospace; background: #eef2f1; }
pre { padding: 6px 8px; } blockquote { border-left: 3px solid #1f6f6a; margin: 6px 0; padding: 2px 10px; background: #eef6f5; }
</style>"""


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*([^*]+)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def convert(markdown: str) -> str:
    out, lines, i = [], markdown.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
        elif stripped.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            i += 1
        elif stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            out.append(f"<h{level}>{inline(stripped[level:].strip())}</h{level}>")
            i += 1
        elif stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            table = ["<table>"]
            for n, cells in enumerate(rows):
                tag = "th" if n == 0 else "td"
                table.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            out.append("\n".join(table + ["</table>"]))
        elif re.match(r"^(\s*)([-*]|\d+\.)\s", line):
            ordered = bool(re.match(r"^\s*\d+\.", line))
            items = []
            while i < len(lines) and (re.match(r"^\s*([-*]|\d+\.)\s", lines[i]) or
                                      (lines[i].startswith("  ") and lines[i].strip())):
                if re.match(r"^\s*([-*]|\d+\.)\s", lines[i]):
                    items.append(re.sub(r"^\s*([-*]|\d+\.)\s", "", lines[i]))
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(item)}</li>" for item in items) + f"</{tag}>")
        elif stripped.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(quote)) + "</blockquote>")
        else:
            paragraph = []
            while i < len(lines) and lines[i].strip() and not re.match(r"^\s*(#|\||```|>|[-*]\s|\d+\.\s)", lines[i]):
                paragraph.append(lines[i].strip())
                i += 1
            out.append("<p>" + inline(" ".join(paragraph)) + "</p>")
    return "\n".join(out)


def main() -> int:
    for language, folder in SOURCES.items():
        target = os.path.join(TARGET, language)
        os.makedirs(target, exist_ok=True)
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".md"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                body = convert(handle.read())
            page = f'<!DOCTYPE html>\n<html lang="{language}"><head><meta charset="utf-8">{STYLE}</head><body>\n{body}\n</body></html>\n'
            with open(os.path.join(target, name[:-3] + ".html"), "w", encoding="utf-8") as handle:
                handle.write(page)
            print(f"{language}/{name[:-3]}.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
