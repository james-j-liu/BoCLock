"""Bank of Canada Governing Council roster (single source of truth).

The Governing Council is the Bank's policy-making body: it sets the policy rate by
consensus. Since its creation in 1994 it has consisted of the Governor, the Senior
Deputy Governor and the Deputy Governors, and since 2023 it has also included
external (part-time) Deputy Governors. The Bank's speech archive also holds talks
by officials who never sit on the Council — the Chief Operating Officer, department
heads, research staff, members of the Board of Directors — and only Council members
belong in the scoring system.

Unlike the MPC, the Council deliberates privately and publishes no attendance
lists, so tenure cannot be read out of minutes. It is recorded here instead, in
TENURE: the date each person joined the Council and the date they left (None =
still serving). tenure.py widens each span a little at either end.

CURRENT = Council members in office as of September 2026 (bankofcanada.ca/about/
governing-council). FORMER = everyone who sat on the Council since 1994 and has left.
"""
from __future__ import annotations

BOC_GC = "BoC Governing Council"

# person -> (joined Council, left Council or None), or a list of such spans for
# someone who left and came back
TENURE: dict = {
    # Governors (Carney and Macklem sat on the Council earlier as deputies)
    "Gordon Thiessen":      ("1994-02-01", "2001-01-31"),
    "David Dodge":          ("2001-02-01", "2008-01-31"),
    "Mark Carney":          [("2003-08-01", "2004-11-15"), ("2008-02-01", "2013-06-01")],
    "Stephen S. Poloz":     ("2013-06-03", "2020-06-02"),
    "Tiff Macklem":         [("2004-07-01", "2007-08-31"),   # DG 2004-07; SDG 2010-14; Gov 2020-
                             ("2010-07-01", "2014-04-30"), ("2020-06-03", None)],
    # Senior Deputy Governors
    "Bernard Bonin":        ("1994-02-01", "1999-06-30"),
    "Malcolm Knight":       ("1999-06-01", "2003-06-30"),
    "Paul Jenkins":         ("1995-01-01", "2010-06-30"),   # DG 1995-2003; SDG 2003-10
    "Carolyn A. Wilkins":   ("2014-05-01", "2020-12-31"),
    "Carolyn Rogers":       ("2022-01-17", None),
    # Deputy Governors
    "Charles Freedman":     ("1994-02-01", "2003-01-31"),
    "Tim Noël":             ("1994-02-01", "2002-06-30"),
    "Sheryl Kennedy":       ("2001-01-01", "2008-06-30"),
    "Pierre Duguay":        ("2000-01-01", "2010-06-30"),
    "David Longworth":      ("2003-01-01", "2010-06-30"),
    "John Murray":          ("2008-03-01", "2014-06-30"),
    "Timothy Lane":         ("2009-06-01", "2022-06-30"),
    "Jean Boivin":          ("2010-01-01", "2012-12-31"),
    "Agathe Côté":          ("2010-05-01", "2016-06-30"),
    "Lawrence L. Schembri": ("2013-03-01", "2022-06-30"),
    "Lynn Patterson":       ("2013-01-01", "2019-06-30"),
    "Sylvain Leduc":        ("2016-09-01", "2019-06-30"),
    "Paul Beaudry":         ("2019-06-01", "2023-07-31"),
    "Toni Gravelle":        ("2019-01-01", None),
    "Sharon Kozicki":       ("2020-01-01", "2025-06-30"),
    "Rhys R. Mendes":       ("2022-06-01", "2026-06-30"),
    "Nicolas Vincent":      ("2023-06-01", None),           # external DG, then DG
    "Michelle Alexopoulos": ("2023-06-01", None),           # external Deputy Governor
    "Marc-André Gosselin":  ("2026-01-01", None),
}

def spans(person: str) -> list[tuple[str, str | None]]:
    t = TENURE.get(person)
    return [] if t is None else (t if isinstance(t, list) else [t])


CURRENT_GC = {p for p in TENURE if spans(p)[-1][1] is None}
FORMER_GC = set(TENURE) - CURRENT_GC

# Spellings seen on bankofcanada.ca, in BIS bylines and in parliamentary transcripts.
ALIASES = {
    "Stephen Poloz": "Stephen S. Poloz",
    "Stephen S Poloz": "Stephen S. Poloz",
    "Carolyn Wilkins": "Carolyn A. Wilkins",
    "Carolyn A Wilkins": "Carolyn A. Wilkins",
    "Lawrence Schembri": "Lawrence L. Schembri",
    "Lawrence L Schembri": "Lawrence L. Schembri",
    "Rhys Mendes": "Rhys R. Mendes",
    "Rhys R Mendes": "Rhys R. Mendes",
    "Agathe Cote": "Agathe Côté",
    "Tim Noel": "Tim Noël",
    "Timothy Noël": "Tim Noël",
    "Tim Lane": "Timothy Lane",
    "Marc-Andre Gosselin": "Marc-André Gosselin",
    "Mark J Carney": "Mark Carney",
    "Mark J. Carney": "Mark Carney",
    "David A Dodge": "David Dodge",
    "David A. Dodge": "David Dodge",
    "Gordon G Thiessen": "Gordon Thiessen",
    "Gordon G. Thiessen": "Gordon Thiessen",
    "Paul D Jenkins": "Paul Jenkins",
    "David J Longworth": "David Longworth",
    "John D Murray": "John Murray",
}


def canon(name: str) -> str:
    name = " ".join((name or "").split())
    return ALIASES.get(name, name)


def is_current_gc(name: str) -> bool:
    n = canon(name)
    return n == BOC_GC or n in CURRENT_GC


def is_gc(name: str) -> bool:
    """True for any Governing Council member (current or former) and the composite."""
    n = canon(name)
    return n == BOC_GC or n in CURRENT_GC or n in FORMER_GC


def _apply_live_state() -> None:
    """Interface parity with MPCLock. The Council roster is maintained by hand in
    TENURE: the Bank publishes no attendance lists to read it from."""
    return None


def to_dict() -> dict:
    """Roster payload for the site (embedded in data.json meta)."""
    return {
        "current": sorted(CURRENT_GC),
        "former": sorted(FORMER_GC),
        "aliases": ALIASES,
    }
