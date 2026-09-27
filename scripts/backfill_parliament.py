"""Ingest every parliamentary hearing (House FINA + Senate BANC, all sessions) into the corpus.

The daily run reads only the current session; this reads them all, for a first
build or after a gap. New hearing documents are classified and merged, and each
supersedes the separately published opening statement of the same hearing. Scoring
is left to the next daily_update.py run, which tops up every unscored document.

  python scripts/backfill_parliament.py                 # House and Senate
  python scripts/backfill_parliament.py --senate-only   # e.g. after a Senate block
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from boclock.config import PROCESSED
from boclock.corpus import parliament
from boclock.process.classify import Classifier
from boclock.schema import load_corpus, save_corpus

CORPUS = PROCESSED / "corpus.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--senate-only", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    corpus = load_corpus(CORPUS)
    have_urls = {s.source_url for s in corpus if s.institution in (parliament.HOUSE, parliament.SENATE)}
    dates = {s.date for s in corpus if s.source_type == "testimony"}
    if args.senate_only:
        parliament.house_meetings = lambda *a, **k: []      # Senate side only
    got = parliament.load(use_cache=not args.no_cache, statement_dates=dates,
                          skip_urls=have_urls)
    ids = {s.id for s in corpus}
    new = [s for s in got if s.id not in ids]
    print(f"{len(new)} new hearing documents")
    if new:
        Classifier().classify_all(new)
        corpus = parliament.supersede(corpus + new)
        save_corpus(corpus, CORPUS)
        print(f"saved {len(corpus)} records "
              f"({sum(1 for s in new if s.is_policy)} new policy-relevant hearing documents)")
    from boclock.corpus import boc_site
    if any(n >= 2 for n in boc_site._timeouts.values()):
        # keep the request so the next run tries again; whatever was fetched is saved
        sys.exit("sencanada.ca stopped answering part-way; backfill incomplete")


if __name__ == "__main__":
    main()
