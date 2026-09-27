"""Assemble the BoCLock corpus from the Bank of Canada.

  boc_speeches -> every text item under /press/speeches/ on bankofcanada.ca
                  (1995-present): speeches, lectures, presentations, the opening
                  statements of the monetary-policy press conferences (to the
                  composite) and of parliamentary committee appearances.
  boc_council  -> the "BoC Governing Council" composite: every rate announcement,
                  every Monetary Policy Report (full PDF text), and the Summaries of
                  Governing Council deliberations (2023-).
  bis_boc      -> the BIS central bankers' speeches archive, used to cross-check
                  the scrape year by year and to backfill speeches the Bank's site
                  lacks (mostly 1997-2001, when its archive is thin).

Everything is taken in English (the Bank publishes both official languages), so
there is no translation step. Records are de-duplicated by Speech.id and written
as JSONL to data/processed/corpus.jsonl.
"""
from __future__ import annotations

import collections

from ..config import PROCESSED
from ..schema import Speech, save_corpus
from . import boc_council, boc_speeches

CORPUS_PATH = PROCESSED / "corpus.jsonl"


def load_all(use_cache: bool = True, skip: tuple = (),
             start_year: int | None = None, end_year: int | None = None,
             concurrency: int = 6) -> list[Speech]:
    speeches: list[Speech] = []
    site: list[Speech] = []

    if "speeches" not in skip:
        print("[1/3] Bank of Canada speeches and appearances...")
        try:
            site = boc_speeches.load(use_cache=use_cache, start_year=start_year,
                                     end_year=end_year, concurrency=concurrency)
            speeches += site
        except Exception as e:  # noqa: BLE001 - one bad source must not kill the run
            print(f"    [warn] BoC speeches failed: {type(e).__name__}: {e}")

    if "council" not in skip:
        print("[2/3] Governing Council composite (rate announcements / MPR / deliberations)...")
        try:
            speeches += boc_council.load(use_cache=use_cache)
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] Council composite failed: {type(e).__name__}: {e}")

    if "bis" not in skip:
        print("[3/3] BIS cross-check...")
        try:
            from . import bis_boc
            bis = bis_boc.load(use_cache=use_cache, start_year=start_year, end_year=end_year)
            speeches += bis_boc.crosscheck(site or speeches, bis)
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] BIS cross-check failed: {type(e).__name__}: {e}")

    seen: dict[str, Speech] = {}
    for s in speeches:
        seen.setdefault(s.id, s)
    deduped = drop_duplicates(list(seen.values()))
    print(f"Combined {len(speeches)} -> {len(deduped)} after de-dup")
    return deduped


def merge(existing: list[Speech], incoming: list[Speech]) -> list[Speech]:
    """Add new records to an existing corpus, keeping what is already scored.

    Existing records win on id collision so classifier verdicts, anonymised text
    and tournament ratings survive a re-ingest.
    """
    by_id = {s.id: s for s in existing}
    added = 0
    for s in incoming:
        if s.id not in by_id:
            by_id[s.id] = s
            added += 1
    print(f"Merged {added} new records into {len(existing)} existing "
          f"-> {len(by_id)} total")
    return list(by_id.values())


def _overlap(a: str, b: str, n: int = 8) -> float:
    """Share of the shorter text's word 8-grams that also occur in the other:
    about 1 for two transcriptions of one speech, near 0 for two different talks."""
    def grams(t: str) -> set:
        w = t.lower().split()[:4000]
        return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def drop_duplicates(corpus: list[Speech], verbose: bool = True) -> list[Speech]:
    """Remove the second copy of a speech held twice under different URLs.

    Two cases: a BIS backfill record for a speech the Bank's site now also yields
    (the BIS copy was only added because the site page used to fail to parse), and
    the same speech filed twice by the Bank itself (a speech and its paper
    version). Same speaker, within two days, and texts of similar length count as
    one speech; the Bank's own copy is kept, else the longer one.
    """
    from ..roster_gc import canon
    import datetime as _dt

    def day(s): return _dt.date.fromisoformat(s.date)
    by_speaker: dict[str, list[Speech]] = {}
    for s in corpus:
        if s.source_type in ("speech", "interview") and s.word_count:
            by_speaker.setdefault(canon(s.speaker), []).append(s)
    drop: set[str] = set()
    for docs in by_speaker.values():
        docs.sort(key=lambda s: s.date)
        for i, a in enumerate(docs):
            for b in docs[i + 1:]:
                if (day(b) - day(a)).days > 2:
                    break
                if a.id in drop or b.id in drop:
                    continue
                if min(a.word_count, b.word_count) / max(a.word_count, b.word_count) < 0.8:
                    continue            # two different talks on consecutive days
                if _overlap(a.text, b.text) < 0.5:
                    continue            # similar length, different words: two talks
                site_a = "(BIS)" not in a.institution
                site_b = "(BIS)" not in b.institution
                if site_a != site_b:
                    drop.add(b.id if site_a else a.id)
                else:
                    drop.add(a.id if a.word_count < b.word_count else b.id)
    if verbose and drop:
        print(f"de-duplicated {len(drop)} speeches held twice under different URLs")
    return [s for s in corpus if s.id not in drop]


def build(use_cache: bool = True, out_path=CORPUS_PATH, **kw) -> list[Speech]:
    corpus = load_all(use_cache=use_cache, **kw)
    save_corpus(corpus, out_path)
    print(f"Saved {len(corpus)} records to {out_path}")
    return corpus


def _summary(corpus: list[Speech]) -> None:
    by_type = collections.Counter(s.source_type for s in corpus)
    print("\nBy source type:", dict(by_type))
    print("Date range:", min(s.date for s in corpus), "..", max(s.date for s in corpus))
    print("Distinct speakers:", len({s.speaker for s in corpus}))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--skip", default="",
                    help="comma-separated source keys to skip (speeches, council, bis)")
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()
    corpus = build(use_cache=not args.no_cache, skip=tuple(x for x in args.skip.split(",") if x),
                   concurrency=args.concurrency)
    _summary(corpus)
