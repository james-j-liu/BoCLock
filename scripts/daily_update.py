"""Daily incremental update — ingest new Bank of Canada documents and score only those.

Reads the newest pages of the Bank's listings (speeches and appearances, press
releases, Monetary Policy Reports) and the sitemap (summaries of deliberations),
scrapes and classifies whatever is not in the corpus yet, then scores ONLY the new
records:
  - pairwise: resume the TrueSkill tournament; the new high-uncertainty documents
    draw the comparisons while existing ratings are replayed from the log,
  - direct: score only documents that don't have a direct score yet.
Finally rebuilds site/data.json and site/macro.json.

State (data/processed/corpus.jsonl with classifications + scores, and
tournament_log.jsonl) is the persistent memory between runs, so in CI it is
committed back to the repo after each run. Cost is a few cents a day.
"""
from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from boclock.config import PROCESSED, cfg
from boclock.corpus import assemble, boc_council, boc_speeches
from boclock.macro.ca_macro import MacroContext
from boclock.output.build_data import era_adjust, write_data_json
from boclock.process.anonymize import Anonymizer
from boclock.process.classify import Classifier
from boclock.process.roster import build_roster
from boclock.roster_gc import is_gc
from boclock.schema import load_corpus, save_corpus
from boclock.tenure import for_corpus
from boclock.tournament.runner import run_tournament

CORPUS = PROCESSED / "corpus.jsonl"
SINCE = "1995-01-01"
PAGES = 3          # listing pages read each morning (10 items a page, newest first)


def main():
    ap = argparse.ArgumentParser()
    # default: config.yaml tournament.target_appearances_per_speech, so new documents
    # get the same number of comparisons the rest of the pool was rated on
    ap.add_argument("--appearances", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="use mock scorers (no API spend)")
    ap.add_argument("--no-score", action="store_true",
                    help="ingest and classify new records, then stop (no scoring spend)")
    ap.add_argument("--out", default="site/data.json")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    existing = load_corpus(CORPUS) if CORPUS.exists() else []
    have_urls = {s.source_url for s in existing}
    have_ids = {s.id for s in existing}

    # 1) newest listing pages + sitemap: only URLs not already held. (Listings show
    #    only published items, so there are no placeholder pages to back off from.)
    new = []
    try:
        skip = have_urls
        got = boc_speeches.load(use_cache=False, max_pages=PAGES, skip_urls=skip, verbose=False)
        got += boc_council.rate_announcements(use_cache=False, max_pages=PAGES,
                                              skip_urls=skip, verbose=False)
        got += boc_council.mprs(use_cache=False, max_pages=1, skip_urls=skip, verbose=False)
        got += boc_council.deliberations(use_cache=False, skip_urls=skip, verbose=False)
        # a few items are listed under two URLs (the July 2024 Report has an old and a
        # new landing page), so a new URL alone does not make a new document
        have_keys = {(s.source_type, s.date, s.title) for s in existing}
        new = [s for s in got if s.id not in have_ids
               and (s.source_type, s.date, s.title) not in have_keys]
        print(f"new documents: {len(new)}")
        for s in new:
            print(f"  + {s.date} {s.source_type:12} {s.speaker[:24]:24} {s.title[:60]}")
    except Exception as e:  # noqa: BLE001 - a blocked scrape must not stop the deploy
        print(f"[warn] ingest failed: {type(e).__name__}: {e}; scoring what we have")

    def make_pool(c):
        # Governing Council members only, and only while they sat on it
        tenure = for_corpus(c)
        return [s for s in c if s.is_policy and is_gc(s.speaker) and SINCE <= s.date <= today
                and tenure.active(s.speaker, s.date)]

    # 2-4) classify + score the new documents. Wrapped so an API failure (e.g.
    #      OpenRouter out of credits -> 402, or a network blip) does NOT fail the job:
    #      we log it and fall back to redeploying the existing scored data.
    corpus, scored_ok = existing, True
    try:
        pending = new + [s for s in existing if s.is_policy is None and is_gc(s.speaker)]
        pending = [s for s in pending if is_gc(s.speaker)]
        if pending:
            Classifier().classify_all(pending)      # is_policy (composite types auto-pass)
        if new:
            corpus = assemble.drop_duplicates(existing + new)
            save_corpus(corpus, CORPUS)

        pool = make_pool(corpus)
        anon = Anonymizer(build_roster([s.speaker for s in corpus]))
        macro = MacroContext()
        new_ids = {s.id for s in new}
        n_new_pool = sum(1 for s in pool if s.id in new_ids or s.mu is None)
        floor = cfg()["tournament"].get("min_appearances", 10)
        n_thin = sum(1 for s in pool if s.mu is not None and s.id not in new_ids
                     and (s.n_comparisons or 0) < floor)
        print(f"pool {len(pool)} Council policy records | {n_new_pool} new to score"
              + (f" | {n_thin} under {floor} comparisons to top up" if n_thin else ""))
        if args.no_score:
            print("--no-score: ingested and classified only")
            raise SystemExit(0)

        if args.dry_run:
            from run_full import MockDirectScorer
            from run_poc import MockJudge
            judge, scorer = MockJudge(), MockDirectScorer()
        else:
            from boclock.judge.factory import make_direct_scorer, make_pairwise_judge
            judge, scorer = make_pairwise_judge(), make_direct_scorer()
            print(f"judges: pairwise={judge.model} direct={scorer.model}")

        if n_new_pool or n_thin:
            run_tournament(pool, judge, appearances_per_speech=args.appearances,
                           macro=macro, resume=True, anonymizer=anon)
        to_direct = [s for s in pool if s.direct_score is None]
        if to_direct:
            scorer.score_all(to_direct, macro, concurrency=6, anonymizer=anon)
        spent = getattr(judge, "cost", 0) + getattr(scorer, "cost", 0)
        if spent:
            print(f"model spend this run: ${spent:.4f}")
        save_corpus(corpus, CORPUS)   # persist classifications, ratings, direct scores
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        scored_ok = False
        print(f"[warn] update/scoring failed: {type(e).__name__}: {e}")
        print("[warn] redeploying existing scored data; new documents retried next run")
        corpus = load_corpus(CORPUS)

    # 5) always rebuild outputs so the site redeploys (even on a degraded run)
    pool = make_pool(corpus)
    era_adjust(pool)
    meta = write_data_json(pool, args.out)
    print(f"wrote {args.out}: {meta['n_speeches']} documents (scored_ok={scored_ok})")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_macro.py")], check=False)
    print("daily update complete")


if __name__ == "__main__":
    main()
