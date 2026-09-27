"""Speeches and appearances from bankofcanada.ca (/press/speeches/, 1995-).

Every text item on the listing becomes one record, typed by what it is:

  Press-conference opening statements (Monetary Policy Report release, and since
  2023 every rate decision) -> ST_STATEMENT, speaker "BoC Governing Council". The
  Governor reads them with the Senior Deputy Governor beside him, on the Council's
  behalf; the site's press-conference toggle can re-attribute them to the Governor.
  Opening statements to a House of Commons or Senate committee -> ST_TESTIMONY,
  attributed to the (first) official who delivered them.
  Speech summaries -> dropped when the full speech is also published (it almost
  always is, the same day); kept as the speech when it is the only text.
  Everything else (remarks, presentations, lectures) -> ST_SPEECH.

Webcasts are video only and are skipped.
"""
from __future__ import annotations

import datetime as _dt
import re
from concurrent.futures import ThreadPoolExecutor

from ..roster_gc import BOC_GC, canon
from ..schema import ST_SPEECH, ST_STATEMENT, ST_TESTIMONY, Speech
from . import boc_site

INSTITUTION = "Bank of Canada"
LISTING = "press/speeches"

_PRESS_CONF_RE = re.compile(r"press conference|release of the monetary policy report", re.I)
_COMMITTEE_RE = re.compile(r"committee|senate|house of commons", re.I)
_SUMMARY = "Speech summary"


def kind(item: dict) -> str:
    t, title, venue = item["type"], item["title"], item["venue"]
    if t.startswith("Opening statement") or t.startswith("Opening Statement"):
        if _PRESS_CONF_RE.search(title):
            return ST_STATEMENT
        if _COMMITTEE_RE.search(title) or _COMMITTEE_RE.search(venue):
            return ST_TESTIMONY
    return ST_SPEECH


def _near(a: str, b: str, days: int = 2) -> bool:
    return abs((_dt.date.fromisoformat(a) - _dt.date.fromisoformat(b)).days) <= days


def select(items: list[dict]) -> list[dict]:
    """Drop webcasts, undated items, and summaries of speeches published in full."""
    # (a few items link off-site, e.g. to an IMF panel video: nothing to extract)
    items = [x for x in items if x["url"] and x["url"].startswith(boc_site.BASE)
             and "/multimedia/" not in x["url"] and x["date"]]
    full = [x for x in items if x["type"] != _SUMMARY]
    keep = []
    for x in items:
        if x["type"] == _SUMMARY and x["authors"]:
            who = canon(x["authors"][0][0])
            if any(y["authors"] and canon(y["authors"][0][0]) == who and _near(x["date"], y["date"])
                   for y in full):
                continue
        keep.append(x)
    return keep


def to_record(item: dict, use_cache: bool = True) -> Speech | None:
    h = boc_site.get(item["url"], use_cache=use_cache)
    if not h:
        return None
    text = boc_site.page_text(h)
    if len(text.split()) < 200:
        # a handful of older items are a short abstract with the speech as a PDF
        for pdf in boc_site.pdf_links(h)[:1]:
            alt = boc_site.pdf_text(pdf, use_cache=use_cache)
            if len(alt.split()) > len(text.split()):
                text = alt
    if len(text.split()) < 80:
        return None
    st = kind(item)
    authors = [canon(n) for n, _ in item["authors"]]
    if st == ST_STATEMENT:
        speaker = BOC_GC
    elif authors:
        speaker = authors[0]
    else:
        return None
    title = item["title"]
    if st == ST_STATEMENT and not re.search(r"\d{4}", title):
        title = f"{title} — {item['date']}"
    if st == ST_TESTIMONY and item["venue"] and item["venue"].lower() not in title.lower():
        title = f"{title} ({item['venue']})"
    return Speech(date=item["date"], speaker=speaker, title=title[:220], text=text,
                  source_type=st, institution=INSTITUTION, source_url=item["url"])


def load(use_cache: bool = True, items: list[dict] | None = None, skip_urls: set | None = None,
         max_pages: int | None = None, concurrency: int = 6, verbose: bool = True,
         start_year: int | None = None, end_year: int | None = None) -> list[Speech]:
    if items is None:
        items = boc_site.listing(LISTING, max_pages=max_pages, verbose=verbose)
    items = select(items)
    if start_year:
        items = [x for x in items if int(x["date"][:4]) >= start_year]
    if end_year:
        items = [x for x in items if int(x["date"][:4]) <= end_year]
    if skip_urls:
        items = [x for x in items if x["url"] not in skip_urls]

    def work(x):
        try:
            return to_record(x, use_cache=use_cache)
        except Exception as e:  # noqa: BLE001 - one bad page is one lost speech
            print(f"    [warn] {x['url']}: {type(e).__name__}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        out = [s for s in ex.map(work, items) if s]
    if verbose:
        import collections
        print(f"  BoC speeches: {len(items)} items -> {len(out)} records "
              f"{dict(collections.Counter(s.source_type for s in out))}")
    return out
