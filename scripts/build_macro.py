"""Build site/macro.json: macro/market series to overlay on the Timeline tab.

Series (Canadian analogues of the FedLock overlay):
  decision      each rate announcement's move, 25bp units   parsed from the announcements
  policy_rate   target for the overnight rate (%)          Valet V39079 (daily, 2009-)
                spliced onto Bank Rate − 25bp before 2009  Valet V122530 (monthly)
  cpi_headline  total CPI, y/y %                           Valet STATIC_TOTALCPICHANGE
  cpi_trim      CPI-trim, y/y %                            Valet CPI_TRIM
  cpi_median    CPI-median, y/y %                          Valet CPI_MEDIAN
  goc_10y       10-year Government of Canada bond yield    Valet BD.CDN.10YR.DQ.YLD
                (daily -> month-end, 2001-)

Since February 1996 the Bank Rate has been set at the top of the 50bp operating
band, i.e. 25bp above the overnight target, so Bank Rate − 25bp recovers the
target for the years before the daily series begins.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from boclock.macro.ca_macro import valet_series

START = "1995-01-01"
TODAY = date.today().isoformat()
OUT = Path(__file__).resolve().parents[1] / "site" / "macro.json"

# name: (valet code, label, shape)
SPEC = {
    "cpi_headline": ("STATIC_TOTALCPICHANGE", "CPI total (YoY)", "line"),
    "cpi_trim":     ("CPI_TRIM", "CPI-trim (YoY)", "line"),
    "cpi_median":   ("CPI_MEDIAN", "CPI-median (YoY)", "line"),
    "goc_10y":      ("BD.CDN.10YR.DQ.YLD", "10Y Government of Canada yield", "line"),
}


def policy_rate() -> pd.Series | None:
    daily = valet_series("V39079", start="2009-01-01")
    monthly = valet_series("V122530", start="1994-01-01")
    parts = []
    if monthly is not None:
        cut = daily.index.min() if daily is not None and len(daily) else pd.Timestamp(TODAY)
        parts.append(monthly[monthly.index < cut] - 0.25)
    if daily is not None:
        parts.append(daily)
    if not parts:
        return None
    return pd.concat(parts).sort_index()


def _step(data: list) -> list:
    """Keep only the points where a step series changes."""
    if not data:
        return data
    comp = [data[0]]
    for p in data[1:]:
        if p[1] != comp[-1][1]:
            comp.append(p)
    if comp[-1] != data[-1]:
        comp.append(data[-1])
    return comp


def decision_series() -> dict:
    """Each rate announcement's decision in 25bp units (0 hold, +1 a quarter-point
    hike, -3 a 75bp cut), read from the announcement text itself (macro.boc_decisions).
    The Council decides by consensus and publishes no votes, so there is no dissent
    to add: this is the Bank of Canada's whole "vote"."""
    from boclock.config import PROCESSED
    from boclock.macro.boc_decisions import decisions
    from boclock.schema import load_corpus
    rows = [d for d in decisions(load_corpus(PROCESSED / "corpus.jsonl"))
            if d["units"] is not None]
    if not rows:
        return {}
    data = [[d["date"], d["units"]] for d in rows]
    print(f"[ok]   decision: {len(data)} announcements, {data[0][0]}..{data[-1][0]}")
    return {"decision": {"label": "BoC decision (25bp units)", "unit": "",
                         "shape": "marker", "data": data}}


def main():
    out = {}
    s = policy_rate()
    if s is not None:
        s = s[s.index >= pd.Timestamp(START)]
        data = _step([[d.strftime("%Y-%m-%d"), round(float(v), 3)] for d, v in s.items()])
        if data and data[-1][0] < TODAY:
            data.append([TODAY, data[-1][1]])
        out["policy_rate"] = {"label": "BoC policy rate", "unit": "%", "shape": "step", "data": data}
        print(f"[ok]   policy_rate: {len(data)} points, last={data[-1]}")
    for name, (code, label, shape) in SPEC.items():
        s = valet_series(code, start=START)
        if s is None or not len(s):
            print(f"[skip] {name}: no data")
            continue
        if name == "goc_10y":
            s = s.resample("ME").last().dropna()
        data = [[d.strftime("%Y-%m-%d"), round(float(v), 3)] for d, v in s.items()]
        out[name] = {"label": label, "unit": "%", "shape": shape, "data": data}
        print(f"[ok]   {name}: {len(data)} points, {data[0][0]}..{data[-1][0]}, last={data[-1][1]}")
    try:
        out.update(decision_series())
    except Exception as e:  # noqa: BLE001 - the corpus-derived series is a bonus
        print(f"[warn] decision series failed: {type(e).__name__}: {e}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"series": out}, ensure_ascii=False), encoding="utf-8")
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
