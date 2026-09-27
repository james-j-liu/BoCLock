"""Does the text move markets? Announcement-day 2-year yield changes vs hawkishness.

Since December 2000 the Bank has announced its decisions on fixed dates, before
markets close, which gives ~200 clean events. For each one:

  dy2   change in the 2-year Government of Canada benchmark yield, in bp, from the
        close before the announcement to the close of the day (Valet BD.CDN.2YR.DQ.YLD)
  move  the decision itself, in 25bp units (macro.boc_decisions)
  hawk  the pairwise hawkishness of the Council's text that day, on the site's
        -10..+10 scale: the announcement alone, and the average of the
        announcement with any same-day opening statement and Monetary Policy Report

The question is whether the text explains the market reaction beyond the decision.
Much of each decision is priced in beforehand, so `move` alone is a weak proxy for
the surprise; if the words carry information the market did not already have, hawk
should add explanatory power on top of it. Standard errors are HC1 (heteroskedasticity
robust). Results are printed and written to site/analysis.json for the Methodology tab.

    python scripts/announcement_reaction.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from boclock.config import PROCESSED
from boclock.macro.boc_decisions import decisions
from boclock.macro.ca_macro import valet_series
from boclock.schema import load_corpus

OUT = ROOT / "site" / "analysis.json"


def _norm(mu):
    return None if mu is None else (mu - 50) / 5


def events() -> pd.DataFrame:
    corpus = load_corpus(PROCESSED / "corpus.jsonl")
    by_day: dict[str, list] = {}
    for s in corpus:
        if s.source_type in ("mp_announce", "mp_statement", "mp_report") and s.mu is not None:
            by_day.setdefault(s.date, []).append(s)
    y2 = valet_series("BD.CDN.2YR.DQ.YLD", start="2000-01-01")
    rows = []
    for d in decisions(corpus):
        if d["units"] is None:
            continue
        t = pd.Timestamp(d["date"])
        on = y2[y2.index == t]
        before = y2[y2.index < t]
        if not len(on) or not len(before):
            continue
        docs = by_day.get(d["date"], [])
        ann = [s for s in docs if s.source_type == "mp_announce"]
        if not ann:
            continue
        rows.append({
            "date": d["date"], "move": d["units"],
            "dy2": (float(on.iloc[-1]) - float(before.iloc[-1])) * 100,
            "hawk_ann": _norm(ann[0].mu),
            "hawk_all": float(np.mean([_norm(s.mu) for s in docs])),
            "n_docs": len(docs),
        })
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    # the change in tone since the previous announcement, as well as its level
    df["dhawk_ann"] = df["hawk_ann"].diff()
    return df


def fit(df: pd.DataFrame, cols: list[str]) -> dict:
    d = df.dropna(subset=["dy2"] + cols)
    X = sm.add_constant(d[cols])
    m = sm.OLS(d["dy2"], X).fit(cov_type="HC1")
    return {"vars": cols, "n": int(m.nobs), "r2": round(float(m.rsquared), 3),
            "coef": {c: round(float(m.params[c]), 2) for c in cols},
            "t": {c: round(float(m.tvalues[c]), 2) for c in cols},
            "p": {c: round(float(m.pvalues[c]), 4) for c in cols}}


def main():
    df = events()
    models = {
        "decision only": fit(df, ["move"]),
        "decision + announcement tone": fit(df, ["move", "hawk_ann"]),
        "decision + all same-day Council text": fit(df, ["move", "hawk_all"]),
        "decision + change in announcement tone": fit(df, ["move", "dhawk_ann"]),
        "holds only: announcement tone": fit(df[df["move"] == 0], ["hawk_ann"]),
    }
    print(f"{len(df)} announcement days, {df['date'].min()}..{df['date'].max()}")
    for name, r in models.items():
        terms = "  ".join(f"{c}={r['coef'][c]:+.2f}bp (t={r['t'][c]:+.2f}, p={r['p'][c]:.3f})"
                          for c in r["vars"])
        print(f"  {name:40} n={r['n']:3}  R2={r['r2']:.3f}  {terms}")
    corr = df[["dy2", "move", "hawk_ann", "hawk_all"]].corr().round(3)
    print("\ncorrelations:\n", corr)
    OUT.write_text(json.dumps({"n_events": len(df), "first": df["date"].min(),
                               "last": df["date"].max(), "models": models},
                              indent=1), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
