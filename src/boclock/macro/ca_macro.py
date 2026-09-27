"""Canadian macro context for the judge (analogue of FedLock's PCE/unemployment/GDP/VIX).

Two open APIs, no keys:
  Bank of Canada Valet   https://www.bankofcanada.ca/valet/observations/<series>/json
  Statistics Canada WDS  getDataFromVectorByReferencePeriodRange?vectorIds=<vector>

A series is addressed in config.yaml as "valet:<code>" or "statcan:<vector>", with
an optional ":yoy" suffix to turn a level into its year-on-year % change. For each
speech date the judge sees the most recent observation on or before that date.

Default series:
  core_cpi      CPI-trim, y/y %              (the Bank's preferred core measure)
  cpi           total CPI, y/y %             (the 2% target is on total CPI)
  unemployment  LFS unemployment rate, 15+   (StatCan v2062815)
  gdp_growth    real GDP, y/y %              (StatCan v62305752, quarterly)

Observations are dated by the period they describe (CPI for December is dated
December 1), so each series is shifted by its publication lag before it is read:
the judge sees only what had been published by the speech date, not the month in
progress. A series that cannot be fetched degrades to "n/a" rather than failing.
"""
from __future__ import annotations

import pandas as pd
import requests

from ..config import RAW, cfg

VALET = "https://www.bankofcanada.ca/valet/observations/{code}/json"
STATCAN = ("https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorByReferencePeriodRange"
           "?vectorIds=%22{vec}%22&startRefPeriod=1990-01-01&endReferencePeriod=2030-12-01")
UA = {"User-Agent": "Mozilla/5.0 (compatible; BoCLock/1.0)"}


def valet_series(code: str, start: str = "1990-01-01") -> pd.Series | None:
    try:
        r = requests.get(VALET.format(code=code), params={"start_date": start},
                         headers=UA, timeout=90)
        r.raise_for_status()
        obs = r.json().get("observations", [])
    except Exception as e:  # noqa: BLE001 - degrade gracefully
        print(f"[macro] valet {code} failed: {e}")
        return None
    rows = []
    for o in obs:
        try:
            rows.append((pd.Timestamp(o["d"]), float(o[code]["v"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        return None
    return pd.Series([v for _, v in rows], index=[d for d, _ in rows]).sort_index()


def statcan_series(vec: str) -> pd.Series | None:
    try:
        r = requests.get(STATCAN.format(vec=vec), headers=UA, timeout=90)
        r.raise_for_status()
        pts = r.json()[0]["object"]["vectorDataPoint"]
    except Exception as e:  # noqa: BLE001
        print(f"[macro] statcan v{vec} failed: {e}")
        return None
    rows = [(pd.Timestamp(p["refPer"]), float(p["value"])) for p in pts
            if p.get("value") is not None]
    if not rows:
        return None
    return pd.Series([v for _, v in rows], index=[d for d, _ in rows]).sort_index()


def fetch(key: str, use_cache: bool = True) -> pd.Series | None:
    """'valet:CPI_TRIM', 'statcan:2062815', 'statcan:62305752:yoy' -> Series."""
    parts = key.split(":")
    src, code, yoy = parts[0], parts[1], len(parts) > 2 and parts[2] == "yoy"
    cache = RAW / f"macro_{src}_{code.replace('.', '_')}.csv"
    s = None
    if use_cache and cache.exists():
        df = pd.read_csv(cache)
        s = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
    else:
        s = valet_series(code) if src == "valet" else statcan_series(code)
        if s is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.values}).to_csv(
                cache, index=False)
    if s is None or not len(s):
        return None
    if yoy:
        s = (s / s.shift(freq=pd.DateOffset(years=1)).reindex(s.index) - 1) * 100
        s = s.dropna()
    return s


# days from the start of the reference period to publication: CPI comes out about
# three weeks after the month ends, the Labour Force Survey a week after, and
# quarterly GDP about two months after the quarter
PUBLICATION_LAG_DAYS = {"cpi": 50, "core_cpi": 50, "unemployment": 38, "gdp_growth": 150}


class MacroContext:
    def __init__(self, use_cache: bool = True):
        self.series: dict[str, pd.Series] = {}
        for name, key in cfg()["macro"]["series"].items():
            if not key:
                continue
            s = fetch(key, use_cache=use_cache)
            if s is not None and len(s):
                s.index = s.index + pd.Timedelta(days=PUBLICATION_LAG_DAYS.get(name, 0))
                self.series[name] = s

    def as_of(self, d: str) -> dict[str, float | None]:
        ts = pd.Timestamp(d)
        out: dict[str, float | None] = {}
        for name, s in self.series.items():
            prior = s[s.index <= ts]
            out[name] = float(prior.iloc[-1]) if len(prior) else None
        return out

    def string(self, d: str) -> str:
        v = self.as_of(d)
        labels = {
            "cpi": "CPI infl",
            "core_cpi": "Core infl (CPI-trim)",
            "unemployment": "Unemployment",
            "gdp_growth": "GDP growth (YoY)",
        }
        bits = [f"{lab}: {v[k]:.1f}%" for k, lab in labels.items() if v.get(k) is not None]
        return "; ".join(bits) if bits else "n/a"


if __name__ == "__main__":
    mc = MacroContext(use_cache=False)
    print("Loaded series:", list(mc.series))
    for d in ("1998-06-01", "2008-12-04", "2015-01-21", "2022-07-13", "2024-06-05"):
        print(d, "->", mc.string(d))
