"""Roster of Bank of Canada officials, used to drive anonymization.

The roster is the union of:
  - speaker names observed in the built corpus, and
  - a curated seed list of Bank of Canada Governors, Senior Deputy Governors and
    Deputy Governors (and a few ministers and foreign central bankers) whose names
    recur inside other people's speeches.

We keep this list deliberately broad: the anonymizer needs *every* name that a
judge might recognise, not just the speech's own author. Concept/place names that
collide with surnames (Phillips curve, Taylor rule) are protected by EXCLUSIONS.
"""
from __future__ import annotations

# Curated seed of names likely to appear inside speeches. Extend freely.
SEED_OFFICIALS: list[str] = [
    # Governors (and pre-Council Governors cited in histories of the Bank)
    "Graham Towers", "James Coyne", "Louis Rasminsky", "Gerald Bouey", "John Crow",
    "Gordon Thiessen", "David Dodge", "Mark Carney", "Stephen Poloz", "Tiff Macklem",
    # Senior Deputy / Deputy Governors
    "Bernard Bonin", "Malcolm Knight", "Paul Jenkins", "Carolyn Wilkins", "Carolyn Rogers",
    "Charles Freedman", "Tim Noël", "Sheryl Kennedy", "Pierre Duguay", "David Longworth",
    "John Murray", "Timothy Lane", "Jean Boivin", "Agathe Côté", "Lawrence Schembri",
    "Lynn Patterson", "Sylvain Leduc", "Paul Beaudry", "Toni Gravelle", "Sharon Kozicki",
    "Rhys Mendes", "Nicolas Vincent", "Michelle Alexopoulos", "Marc-André Gosselin",
    # other names that date a text
    "Jim Flaherty", "Bill Morneau", "Chrystia Freeland", "Paul Martin", "Ralph Goodale",
    "François-Philippe Champagne", "Dominic LeBlanc",
    "Alan Greenspan", "Ben Bernanke", "Janet Yellen", "Jerome Powell",
]

# Strings that look like surnames but must NOT be redacted (concepts / places).
EXCLUSIONS: set[str] = {
    "phillips", "taylor", "lucas", "fisher",
    "ottawa", "toronto", "montreal", "canada",
}

TITLES = [
    "Governor", "Deputy Governor", "Chief Economist", "Executive Director",
    "President", "Vice-President", "Chair", "Chairman", "Director", "Professor",
    "Sir", "Dame", "Lord", "Baroness", "Mr", "Mr.", "Ms", "Ms.", "Mrs", "Mrs.",
    "Dr", "Dr.",
]


def build_roster(corpus_speakers: list[str]) -> list[str]:
    # every Council member, current and former, and every alias — not just people who
    # already have records — or a new member with no speeches of their own yet is
    # named verbatim inside everyone else's texts
    from ..roster_gc import ALIASES, CURRENT_GC, FORMER_GC
    names = set(SEED_OFFICIALS) | CURRENT_GC | FORMER_GC | set(ALIASES)
    for s in corpus_speakers:
        if s and s != "BoC Governing Council":
            names.add(s)
    return sorted(names)
