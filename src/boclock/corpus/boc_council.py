"""The "BoC Governing Council" composite: the Council's own monetary-policy output.

  Rate announcements   the press release on every fixed announcement date (eight a
                       year since December 2000) and the earlier unscheduled ones;
                       found on /press/press-releases/ by title.
  Monetary Policy      every Report since the first in May 1995 (semi-annual to
  Reports              2000, then quarterly; the January and July issues were
                       shorter "Updates" until 2013). The landing page holds only a
                       teaser, so the full text comes from the Report's PDF.
  Summaries of         published two weeks after each decision since January 2023.
  deliberations        The listing page for them cannot be paginated, so they are
                       found in the WordPress sitemap by slug, and dated by the
                       decision they describe (the slug names it).

The press-conference opening statements belong to the composite too, but they are
published among the speeches and are picked up by boc_speeches.
"""
from __future__ import annotations

import datetime as _dt
import re
from concurrent.futures import ThreadPoolExecutor

from ..roster_gc import BOC_GC
from ..schema import ST_ACCOUNT, ST_ANNOUNCE, ST_REPORT, Speech
from . import boc_site

INSTITUTION = "Bank of Canada"

_RATE_TITLE_RE = re.compile(
    r"\b(maintains|lowers|raises|increases|reduces|cuts|holds|leaves|keeps|lower|raise)\b"
    r".*\b(rate|rates|target)\b", re.I)
_NOT_RATE_RE = re.compile(r"schedule|publishes|consultation|mortgage|prime|renewal|framework", re.I)


def is_rate_announcement(title: str) -> bool:
    return bool(_RATE_TITLE_RE.search(title)) and not _NOT_RATE_RE.search(title)


def _record(item: dict, st: str, text: str, title: str | None = None,
            date: str | None = None) -> Speech | None:
    if len(text.split()) < 80:
        return None
    return Speech(date=date or item["date"], speaker=BOC_GC, title=(title or item["title"])[:220],
                  text=text, source_type=st, institution=INSTITUTION, source_url=item["url"])


def _pmap(fn, items, concurrency=6):
    def work(x):
        try:
            return fn(x)
        except Exception as e:  # noqa: BLE001 - one bad page is one lost document
            print(f"    [warn] {x.get('url')}: {type(e).__name__}: {e}")
            return None
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        return [s for s in ex.map(work, items) if s]


# --- rate announcements ------------------------------------------------------
def rate_announcements(use_cache: bool = True, max_pages: int | None = None,
                       skip_urls: set | None = None, verbose: bool = True) -> list[Speech]:
    items = boc_site.listing("press/press-releases", max_pages=max_pages, verbose=verbose)
    items = [x for x in items if x["url"] and x["date"] and is_rate_announcement(x["title"])
             and x["url"] not in (skip_urls or set())]

    def one(x):
        h = boc_site.get(x["url"], use_cache=use_cache)
        return _record(x, ST_ANNOUNCE, boc_site.page_text(h)) if h else None
    out = _pmap(one, items)
    if verbose:
        print(f"  rate announcements: {len(items)} -> {len(out)}")
    return out


# --- Monetary Policy Reports -------------------------------------------------
_MPR_BOILER_RE = re.compile(r"^.*?(?=\n(?:Overview|Summary|Canadian economy|Global economy)\b)",
                            re.S)


def _mpr_pdf(h: str) -> str | None:
    pdfs = boc_site.pdf_links(h)
    # the Report itself, not a chart pack, technical box or French edition
    main = [p for p in pdfs if re.search(r"mpr|rpm|/\d{4}/\d\d/[^/]*(report|update)", p, re.I)
            and not re.search(r"chart|graph|fr\.pdf|-fr-|_fr", p, re.I)]
    return (main or pdfs or [None])[0]


def mprs(use_cache: bool = True, max_pages: int | None = None, skip_urls: set | None = None,
         verbose: bool = True) -> list[Speech]:
    items = boc_site.listing("publications/mpr", max_pages=max_pages, verbose=verbose)
    # the listing also carries a few items about the Report (e.g. focus-group research)
    items = [x for x in items if x["url"] and x["date"] and x["url"] not in (skip_urls or set())
             and x["title"].startswith("Monetary Policy Report")]

    def one(x):
        h = boc_site.get(x["url"], use_cache=use_cache)
        if not h:
            return None
        pdf = _mpr_pdf(h)
        text = boc_site.pdf_text(pdf, use_cache=use_cache) if pdf else ""
        if len(text.split()) < 1000:        # no PDF: whatever the page itself holds
            alt = boc_site.page_text(h)
            text = alt if len(alt.split()) > len(text.split()) else text
        title = " ".join(x["title"].replace("—", " — ").split())
        return _record(x, ST_REPORT, text, title=title)
    out = _pmap(one, items, concurrency=4)
    # a few Reports are listed twice (an old and a new landing page): keep the fuller
    best: dict[str, Speech] = {}
    for s in out:
        if s.title not in best or s.word_count > best[s.title].word_count:
            best[s.title] = s
    out = list(best.values())
    if verbose:
        print(f"  Monetary Policy Reports: {len(items)} -> {len(out)}")
    return out


# --- Summaries of Governing Council deliberations ----------------------------
_DELIB_RE = re.compile(r"/(\d{4})/(\d\d)/summary-(?:of-)?(?:governing-council-)?deliberations"
                       r"(?:-governing-council)?(?:-fixed-announcement-date-(?:of-)?"
                       r"([a-z]+)-(\d{1,2})-(\d{4}))?/?$")


def sitemap_urls(use_cache: bool = False) -> list[str]:
    idx = boc_site.get(f"{boc_site.BASE}/wp-sitemap.xml", use_cache=use_cache) or ""
    urls = []
    for sm in re.findall(r"<loc>([^<]*wp-sitemap-posts-post-\d+\.xml)</loc>", idx):
        urls += re.findall(r"<loc>([^<]+)</loc>", boc_site.get(sm, use_cache=use_cache) or "")
    return urls


def deliberation_urls(use_cache: bool = False) -> list[tuple[str, str]]:
    """(url, decision date) for every summary of deliberations in the sitemap."""
    out = []
    for u in sitemap_urls(use_cache):
        m = _DELIB_RE.search(u)
        if not m:
            continue
        if m.group(3):
            try:
                d = _dt.datetime.strptime(f"{m.group(3)} {m.group(4)} {m.group(5)}",
                                          "%B %d %Y").date().isoformat()
            except ValueError:
                continue
        else:
            d = None                  # dated from the page itself
        out.append((u, d))
    return out


def deliberations(use_cache: bool = True, skip_urls: set | None = None,
                  verbose: bool = True) -> list[Speech]:
    found = [(u, d) for u, d in deliberation_urls(use_cache=False)
             if u not in (skip_urls or set())]

    def one(ud):
        u, d = ud
        h = boc_site.get(u, use_cache=use_cache)
        if not h:
            return None
        if d is None:
            m = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d\d-\d\d)', h) or \
                re.search(r'article:published_time" content="(\d{4}-\d\d-\d\d)', h)
            d = m.group(1) if m else u.split("/")[3] + "-" + u.split("/")[4] + "-15"
        text = boc_site.page_text(h)
        title = f"Summary of Governing Council deliberations — decision of {d}"
        return _record({"url": u, "date": d}, ST_ACCOUNT, text, title=title, date=d)
    out = _pmap(one, found)
    if verbose:
        print(f"  summaries of deliberations: {len(found)} -> {len(out)}")
    return out


def load(use_cache: bool = True, verbose: bool = True, **kw) -> list[Speech]:
    return (rate_announcements(use_cache=use_cache, verbose=verbose)
            + mprs(use_cache=use_cache, verbose=verbose)
            + deliberations(use_cache=use_cache, verbose=verbose))
