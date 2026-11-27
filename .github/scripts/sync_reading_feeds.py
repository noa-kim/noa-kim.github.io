#!/usr/bin/env python3
"""Pull Noa's public reading feeds into /reading/.

· Goodreads "currently reading" shelf  → Books section
· Instapaper public folder             → Articles section

Each feed rewrites only the lines between its own pair of markers in
reading/index.html, e.g. <!-- GOODREADS:START --> … <!-- GOODREADS:END -->.
Hand-written picks outside the markers are never touched.

Usage:
  python3 .github/scripts/sync_reading_feeds.py
  python3 .github/scripts/sync_reading_feeds.py --goodreads FILE --instapaper FILE   (test with saved feeds)

Standard library only. A feed that fails to load is skipped with a warning
so one outage doesn't block the other; the job fails only if both fail.
"""
import argparse
import email.utils
import html
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# Goodreads ended public RSS feeds in Nov 2026, so this source is paused and the
# "On my nightstand" group on the page is hidden. To restore: set this to True,
# update GOODREADS_URL if needed, and remove `hidden` from that group's div.
GOODREADS_ENABLED = False
GOODREADS_URL = "https://www.goodreads.com/review/list_rss/1278912?shelf=currently-reading"
INSTAPAPER_URL = "https://instapaper.com/rss/folder/4965738/872230/wUmh3decxsV6HcPwhrmPo5jvlx4"

PAGE = Path(__file__).resolve().parents[2] / "reading" / "index.html"
INDENT = " " * 10
MAX_BOOKS = 8
MAX_ARTICLES = 12
MAX_NOTE_CHARS = 280


def e(s):
    return html.escape(s or "", quote=True)


# ── helpers ────────────────────────────────────────────────────────
def load(src):
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "noa-kim.github.io reading sync"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    return Path(src).read_bytes()


def clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def trim(text, n=MAX_NOTE_CHARS):
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def month_year(pub):
    try:
        return email.utils.parsedate_to_datetime((pub or "").strip()).strftime("%B %Y")
    except (TypeError, ValueError, IndexError):
        return ""


def is_http(url):
    return bool(re.match(r"https?://", url or ""))


def block(lines):
    return "\n".join(INDENT + line for line in lines)


# ── Goodreads ──────────────────────────────────────────────────────
def render_book(item):
    title = clean(item.findtext("title"))
    if not title:
        return None
    author = clean(item.findtext("author_name"))
    link = (item.findtext("link") or "").strip()
    # Goodreads adds a tracking query to item links; the plain book page is enough
    book_id = (item.findtext("book_id") or "").strip()
    if book_id.isdigit():
        link = f"https://www.goodreads.com/book/show/{book_id}"
    cover = ""
    for tag in ("book_large_image_url", "book_medium_image_url", "book_image_url"):
        url = (item.findtext(tag) or "").strip()
        if is_http(url) and "nophoto" not in url:
            cover = url
            break
    started = month_year(item.findtext("user_date_added"))
    # The group label already says "On my nightstand", so only add the date
    meta = f'<span class="pick-when">Started {e(started)}</span>' if started else ""
    lines = ['<li class="pick pick--book pick--feed">']
    if cover:
        lines.append(f'  <img class="pick-cover" src="{e(cover)}" alt="" width="64" height="96" loading="lazy" />')
    if meta:
        lines.append(f'  <p class="pick-meta">{meta}</p>')
    lines.append(f'  <h3 class="pick-title">{e(title)}</h3>')
    if author:
        lines.append(f'  <p class="pick-by">{e(author)}</p>')
    if is_http(link):
        lines.append(f'  <a class="pick-link" href="{e(link)}">On Goodreads</a>')
    lines.append("</li>")
    return block(lines)


# ── Instapaper ─────────────────────────────────────────────────────
def render_article(item):
    title = clean(item.findtext("title")) or "Untitled"
    link = (item.findtext("link") or "").strip()
    if not is_http(link):
        return None
    host = urllib.parse.urlparse(link).netloc.lower().removeprefix("www.")
    when = month_year(item.findtext("pubDate"))
    note = trim(clean(item.findtext("description")))
    meta = (f'<span class="pick-when">{e(when)}</span>' if when else "") + "<span>Saved on Instapaper</span>"
    lines = ['<li class="pick pick--feed">',
             f'  <p class="pick-meta">{meta}</p>',
             f'  <h3 class="pick-title">{e(title)}</h3>',
             f'  <p class="pick-by">{e(host)}</p>']
    if note:
        lines.append(f'  <p class="pick-note">{e(note)}</p>')
    lines += [f'  <a class="pick-link" href="{e(link)}">Read</a>', "</li>"]
    return block(lines)


# ── page update ────────────────────────────────────────────────────
def replace_between(page, name, body):
    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(page):
        raise SystemExit(f"{name} markers not found in {PAGE}")
    inner = f"\n{body}\n{INDENT}" if body else f"\n{INDENT}"
    return pattern.sub(lambda _: f"{start}{inner}{end}", page, count=1)


def sync(page, name, src, render, limit, allow_empty):
    try:
        root = ET.fromstring(load(src))
    except Exception as err:  # network, HTTP or XML error
        print(f"::warning::{name}: could not read feed ({err}); leaving that list as is.")
        return page, False
    items = root.findall("./channel/item")
    if not items and not allow_empty:
        print(f"::warning::{name}: feed has no items; leaving that list as is.")
        return page, True
    blocks = [b for b in (render(i) for i in items[:limit]) if b]
    print(f"{name}: {len(blocks)} items")
    return replace_between(page, name, "\n\n".join(blocks)), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goodreads", default=GOODREADS_URL)
    ap.add_argument("--instapaper", default=INSTAPAPER_URL)
    args = ap.parse_args()

    page = original = PAGE.read_text(encoding="utf-8")
    # An empty "currently reading" shelf is real (between books), so allow it;
    # the page hides the group when the list is empty.
    if GOODREADS_ENABLED:
        page, ok_gr = sync(page, "GOODREADS", args.goodreads, render_book, MAX_BOOKS, allow_empty=True)
    else:
        print("GOODREADS: paused (see GOODREADS_ENABLED)")
        ok_gr = False
    page, ok_ip = sync(page, "INSTAPAPER", args.instapaper, render_article, MAX_ARTICLES, allow_empty=False)

    if page != original:
        PAGE.write_text(page, encoding="utf-8")
        print("Updated reading/index.html")
    else:
        print("No changes.")
    if not (ok_gr or ok_ip):
        sys.exit("No feed could be read.")


if __name__ == "__main__":
    main()
