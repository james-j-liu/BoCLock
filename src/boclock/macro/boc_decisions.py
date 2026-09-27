"""Policy-rate decisions, read from the Bank's own rate announcements.

Each announcement's opening sentence states the new target for the overnight rate
("…raising its target for the overnight rate by one-quarter of one percentage point
to 2 3/4 per cent", "…held its target for the overnight rate at 2.25%"). The level is
parsed from it, and the decision is the change from the previous announcement, in
25bp units: 0 = hold, +1 = a quarter-point hike, -2 = a half-point cut. The Council
decides by consensus and publishes no votes, so this is the whole of the "vote".

Levels come in every notation the Bank has used since 2000: 5¾, 2 3/4, 1/2, ¼, 2.25.
"""
from __future__ import annotations

import re

_FRAC = {"¼": 0.25, "½": 0.5, "¾": 0.75}
_NUM = r"(?=\d|[¼½¾])(\d+(?:\.\d+)?)?\s*([¼½¾]|\d/\d)?"
# "…at 1 per cent", "…to 2 3/4 per cent", "…at the effective lower bound of ¼ percent"
# — the first level after the phrase, never one that belongs to the Bank Rate
_LEVEL_RE = re.compile(
    r"target\s+for\s+the\s+overnight\s+rate(?:(?!Bank Rate)[^.]){0,120}?\b(?:to|at)\s+"
    r"(?:the\s+effective\s+lower\s+bound\s+of\s+)?" + _NUM +
    r"\s*(?:per\s*cent|percent|%)", re.I)


def _value(whole: str | None, frac: str | None) -> float | None:
    if whole is None and frac is None:
        return None
    v = float(whole) if whole else 0.0
    if frac:
        if frac in _FRAC:
            v += _FRAC[frac]
        else:
            n, d = frac.split("/")
            v += int(n) / int(d)
    return v


def parse_level(text: str) -> float | None:
    """The overnight-rate target an announcement sets or keeps, in per cent."""
    m = _LEVEL_RE.search(text[:1500])
    return _value(m.group(1), m.group(2)) if m else None


def decisions(corpus) -> list[dict]:
    """[{date, level, change_bp, units}] for every rate announcement, oldest first.
    The first announcement has no predecessor and so no change."""
    ann = sorted((s for s in corpus if s.source_type == "mp_announce"), key=lambda s: s.date)
    out, prev = [], None
    for s in ann:
        lvl = parse_level(s.text)
        if lvl is None:
            continue
        change = None if prev is None else round((lvl - prev) * 100)
        out.append({"date": s.date, "level": lvl, "change_bp": change,
                    "units": None if change is None else change / 25, "id": s.id})
        prev = lvl
    return out
