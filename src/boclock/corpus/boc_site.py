"""Shared access to bankofcanada.ca: listing crawler, page and PDF text, caching.

The site is WordPress, but its REST API is closed to anonymous users, so content is
discovered from the server-rendered listing pages, which paginate with
`?mt_page=N` and render each item as `<article class="media" id='post-N'>` (or a
`<div class="media">` for webcasts, which have no text and are skipped):

  /press/speeches/          speeches and appearances (remarks, opening statements,
                            presentations, lectures, speech summaries) 1995-
  /press/press-releases/    press releases, including every rate announcement
  /publications/mpr/        Monetary Policy Reports, 1995-
  /content_type/publications/summary-of-deliberations/   2023-

Each item's own page carries the full text in `<div class='post-content'>`; the
Monetary Policy Report pages hold only a teaser and link the full report as a PDF.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import html as _html
import io
import re
import time

import requests

from ..config import RAW

BASE = "https://www.bankofcanada.ca"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
CACHE = RAW / "boc_cache"

_session = requests.Session()
_session.headers["User-Agent"] = UA


def get(url: str, use_cache: bool = True, binary: bool = False, tries: int = 4):
    """GET with a disk cache (keyed by URL) and polite retries."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + (".bin" if binary else ".html"))
    if use_cache and f.exists():
        return f.read_bytes() if binary else f.read_text(encoding="utf-8")
    last = None
    for i in range(tries):
        try:
            r = _session.get(url, timeout=90)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            if binary:
                f.write_bytes(r.content)
                return r.content
            r.encoding = "utf-8"
            f.write_text(r.text, encoding="utf-8")
            return r.text
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


_ITEM_SPLIT = re.compile(r"<(?:article|div) class=\"media\" id='post-")


def _g(pat: str, s: str) -> str | None:
    m = re.search(pat, s, re.S)
    return m.group(1) if m else None


def parse_date(text: str | None) -> str | None:
    if not text:
        return None
    try:
        return _dt.datetime.strptime(" ".join(text.split()), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def listing(path: str, max_pages: int | None = None, use_cache: bool = False,
            verbose: bool = True) -> list[dict]:
    """Every item of a listing, newest first: id, date, url, title, type, authors
    (with their title attribute, e.g. "Governor - Executive"), venue, subjects."""
    out, seen, page = [], set(), 1
    while max_pages is None or page <= max_pages:
        h = get(f"{BASE}/{path.strip('/')}/?mt_page={page}", use_cache=use_cache)
        if not h:
            break
        new = 0
        for b in _ITEM_SPLIT.split(h)[1:]:
            pid = b[:b.find("'")]
            if pid in seen:
                continue
            seen.add(pid)
            new += 1
            authors_html = _g(r"media-authors\">(.*?)</span>", b) or ""
            out.append({
                "id": pid,
                "date": parse_date(_g(r"media-date[^>]*>([^<]+)", b)),
                "url": _g(r'media-heading">\s*<a href="([^"]+)"', b),
                "title": " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", _g(
                    r'media-heading">\s*<a [^>]*>(.*?)</a>', b) or "")).split()),
                "type": (_g(r'media-type">([^<]+)', b) or "").strip(),
                "authors": [(_html.unescape(n).strip(), _html.unescape(t))
                            for t, n in re.findall(r'title="([^"]*)">([^<]+)</a>', authors_html)],
                "venue": _html.unescape(_g(r"media-venue'>([^<]+)", b) or "").strip(),
                "subjects": re.findall(r"subject\[\]=([\w-]+)", b),
            })
        if not new:
            break
        if verbose and page % 20 == 0:
            print(f"    {path}: page {page}, {len(out)} items")
        page += 1
        time.sleep(0.3)
    return out


_DROP_TAIL = re.compile(
    r"\n(?:Related (?:information|content|webcasts?)|Webcasts?\b|Media Availability|"
    r"Footnotes?\b|Content Type\(s\)|Available as:)", re.I)


def _blocks(el) -> list[str]:
    for tag in el.select("script, style, figure, .post-callout-wrapper, .bocss-footnotes, "
                         "sup, .share-buttons, table"):
        tag.decompose()
    out = []
    for b in el.find_all(["p", "h2", "h3", "h4", "li", "blockquote"]):
        if b.name == "p" and b.find_parent(["li", "blockquote"]):
            continue
        t = " ".join(b.get_text(" ", strip=True).split())
        if t:
            out.append(t)
    return out or [t for t in el.get_text("\n", strip=True).splitlines() if t.strip()]


def page_text(h: str) -> str:
    """Body text of an item page, paragraphs kept apart.

    Older pages hold it in `<div class='post-content'>`. Newer ones leave that div
    empty and put the text in a `bochtml` content module after it — the same
    module type as the site's navigation menus, which are told apart by length
    (a menu block is under 50 words).
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(h, "lxml")
    pc = soup.select_one("div.post-content")
    if not pc:
        return ""
    blocks = _blocks(pc)
    for mod in pc.find_all_next("div", class_="cfct-widget-module-bochtml"):
        if len(mod.get_text(" ", strip=True).split()) > 60:
            blocks += _blocks(mod)
    text = "\n".join(blocks)
    m = _DROP_TAIL.search(text)
    if m and m.start() > 0.5 * len(text):
        text = text[:m.start()]
    return text.strip()


def pdf_links(h: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r'href="(https://www\.bankofcanada\.ca/[^"]+\.pdf)"', h)))


def pdf_text(url: str, use_cache: bool = True) -> str:
    from pypdf import PdfReader
    data = get(url, use_cache=use_cache, binary=True)
    if not data:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:  # noqa: BLE001 - a corrupt PDF is one lost document
        print(f"    [warn] unreadable PDF {url}: {type(e).__name__}")
        return ""
    text = "\n".join(pages)
    text = re.sub(r"-\n(?=[a-z])", "", text)          # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
