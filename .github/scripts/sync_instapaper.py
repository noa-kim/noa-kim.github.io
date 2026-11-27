#!/usr/bin/env python3
"""Pull Noa's public Instapaper folder into the Articles list on /reading/.

Reads the RSS feed, then rewrites only the lines between
<!-- INSTAPAPER:START --> and <!-- INSTAPAPER:END --> in reading/index.html.
Hand-written picks outside those markers are never touched.

Usage:  python3 .github/scripts/sync_instapaper.py [FEED_URL_OR_FILE]
Standard library only, so it runs on any GitHub runner without installs.
"""
import email.utils
import html
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FEED_URL = "https://instapaper.com/rss/folder/4965738/872230/wUmh3decxsV6HcPwhrmPo5jvlx4"
PAGE = Path(__file__).resolve().parents[2] / "reading" / "index.html"
MAX_ITEMS = 12          # newest first; older saves drop off the page
MAX_NOTE_CHARS = 280    # trim long descriptions to a sentence or two
START, END = "<!-- INSTAPAPER:START -->", "<!-- INSTAPAPER:END -->"
INDENT = " " * 10


def load(src):
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "noa-kim.github.io feed sync"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    return Path(src).read_bytes()


def clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def trim(text, n=MAX_NOTE_CHARS):
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def month_year(pub):
    try:
        return email.utils.parsedate_to_datetime(pub).strftime("%B %Y")
    except (TypeError, ValueError):
        return ""


def source(link):
    host = urllib.parse.urlparse(link).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def render(item):
    title = clean(item.findtext("title")) or "Untitled"
    link = (item.findtext("link") or "").strip()
    if not re.match(r"https?://", link):
        return None
    when = month_year(item.findtext("pubDate"))
    note = trim(clean(item.findtext("description")))
    e = lambda s: html.escape(s, quote=True)
    lines = [f'<li class="pick pick--saved">',
             f'  <p class="pick-meta"><span class="pick-when">{e(when)}</span><span>Saved on Instapaper</span></p>' if when
             else f'  <p class="pick-meta"><span>Saved on Instapaper</span></p>',
             f'  <h3 class="pick-title">{e(title)}</h3>',
             f'  <p class="pick-by">{e(source(link))}</p>']
    if note:
        lines.append(f'  <p class="pick-note">{e(note)}</p>')
    lines += [f'  <a class="pick-link" href="{e(link)}">Read</a>', "</li>"]
    return "\n".join(INDENT + l for l in lines)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else FEED_URL
    root = ET.fromstring(load(src))
    items = root.findall("./channel/item")
    if not items:
        sys.exit("Feed has no items; leaving the page unchanged.")
    blocks = [b for b in (render(i) for i in items[:MAX_ITEMS]) if b]

    page = PAGE.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(page):
        sys.exit(f"Markers not found in {PAGE}")
    body = "\n\n".join(blocks)
    new = pattern.sub(lambda _: f"{START}\n{body}\n{INDENT}{END}", page, count=1)
    if new != page:
        PAGE.write_text(new, encoding="utf-8")
        print(f"Updated {len(blocks)} saved articles.")
    else:
        print("No changes.")


if __name__ == "__main__":
    main()
