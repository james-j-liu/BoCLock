"""Who was on the Governing Council, and when.

A document by an individual counts only while they sat on the Council: a Deputy
Governor's speeches from their earlier years as a department chief or as an
academic, or a former Governor commenting years later, are not the Council's
voice. The spans come from roster_gc.TENURE, widened a little at the front (a
newly announced appointee's first appearances) and at the end (a farewell speech).
"""
from __future__ import annotations

import datetime as _dt

from .roster_gc import BOC_GC, TENURE, canon, spans

GC_FIRST_DAY = "1994-02-01"
LEAD_DAYS = 60
TAIL_DAYS = 45


def _shift(day: str, days: int) -> str:
    return (_dt.date.fromisoformat(day) + _dt.timedelta(days=days)).isoformat()


class Tenure:
    def __init__(self, table: dict):
        self.table = table

    def active(self, speaker: str, day: str) -> bool:
        """True if `speaker` sat on the Governing Council around `day`."""
        person = canon(speaker)
        if person == BOC_GC:
            return day >= GC_FIRST_DAY
        return any(_shift(start, -LEAD_DAYS) <= day <= (_shift(end, TAIL_DAYS) if end else "9999")
                   for start, end in spans(person))


def for_corpus(corpus=None) -> Tenure:
    return Tenure(TENURE)


def sync_roster(corpus, path) -> dict:
    """Interface parity with MPCLock (the roster is hand-maintained)."""
    return {}
