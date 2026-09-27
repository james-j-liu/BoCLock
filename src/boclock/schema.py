"""Core data model for the corpus.

A Speech is one judged unit. Individual Governing Council members (Governor,
Senior Deputy Governor, Deputy Governors) get one record per speech. The
"BoC Governing Council" composite speaker (rate announcements, Monetary Policy
Reports, Summaries of Governing Council deliberations, and the press-conference
opening statements) is modelled by setting speaker == BOC_GC on those records, so
they aggregate together in the rankings while still being scored per-document.
"""
from __future__ import annotations

import base64
import hashlib
import json
import zlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterator, Optional

BOC_GC = "BoC Governing Council"

# Back-compat alias: much of the shared pipeline was written against the ECB name.
ECB_COUNCIL = BOC_GC

# Document types
ST_SPEECH = "speech"            # individual Council member speech / lecture / remarks
ST_INTERVIEW = "interview"      # media interview
ST_STATEMENT = "mp_statement"   # press-conference opening statement (Governor + SDG)
ST_ANNOUNCE = "mp_announce"     # policy rate announcement (press release)
ST_ACCOUNT = "mp_account"       # Summary of Governing Council deliberations (2023-)
ST_REPORT = "mp_report"         # Monetary Policy Report (and MPR Update, 2000-2013)
ST_TESTIMONY = "testimony"      # one Council member's evidence to a parliamentary committee
ST_QA = "mp_qa"                 # unused: the Bank publishes no press-conference transcripts

COUNCIL_TYPES = {ST_STATEMENT, ST_ANNOUNCE, ST_ACCOUNT, ST_REPORT, ST_QA}
GC_TYPES = COUNCIL_TYPES


@dataclass
class Speech:
    date: str                       # ISO YYYY-MM-DD
    speaker: str                    # canonical speaker name, or ECB_COUNCIL
    title: str
    text: str                       # full text, English (post-translation)
    source_type: str                # one of the ST_* constants
    institution: str = ""           # e.g. "European Central Bank", "Deutsche Bundesbank"
    source_url: str = ""
    orig_language: str = "en"
    translated: bool = False
    word_count: int = 0
    is_policy: Optional[bool] = None      # set by classifier
    text_anon: str = ""                   # set by anonymizer

    # pairwise-tournament outputs (filled later)
    mu: Optional[float] = None
    mu_adj: Optional[float] = None
    sigma: Optional[float] = None
    n_comparisons: int = 0

    # direct-scoring outputs (alternative method: one LLM 0-100 rating per speech)
    direct_score: Optional[float] = None
    direct_adj: Optional[float] = None

    id: str = ""

    def __post_init__(self):
        if not self.word_count and self.text:
            self.word_count = len(self.text.split())
        if not self.id:
            self.id = self.make_id()

    def make_id(self) -> str:
        h = hashlib.sha1(
            f"{self.date}|{self.speaker}|{self.title}|{self.source_url}".encode("utf-8")
        ).hexdigest()[:16]
        return h

    @property
    def is_council(self) -> bool:
        return self.speaker == ECB_COUNCIL or self.source_type in COUNCIL_TYPES


def keeps_text(s: "Speech") -> bool:
    """Whether a record's body text has to survive a save.

    The corpus lives in git (that is what makes the daily run incremental) and
    GitHub rejects any file over 100 MB, so text is kept where it can still be
    needed and dropped where it cannot. Everything by a Council member or the
    Council keeps its text whatever the classifier said, because a change to
    the classifier has to be able to re-judge a speech it previously rejected.
    Speeches by officials who never sit on the Council keep their metadata and
    source_url only — a roster change can re-scrape them.
    """
    from .roster_gc import is_gc
    return is_gc(s.speaker)


# Long texts are stored compressed (zlib, then base64 so the file stays JSONL):
# 86 MB of text becomes 40 MB, well inside GitHub's 100 MB per-file limit. zlib is
# deterministic, so a record that has not changed is byte-identical on every save
# and git's daily deltas stay as small as they were with plain text.
_COMPRESS_OVER = 2000


def _record(s: Speech, keep_all_text: bool = False) -> dict:
    d = asdict(s)
    d["text_anon"] = ""          # derived: recomputed per run, never stored
    if not (keep_all_text or keeps_text(s)):
        d["text"] = ""
    if len(d["text"]) > _COMPRESS_OVER:
        d["text_z"] = base64.b64encode(zlib.compress(d["text"].encode("utf-8"), 9)).decode("ascii")
        d["text"] = ""
    return d


def _from_json(line: str) -> "Speech":
    rec = json.loads(line)
    packed = rec.pop("text_z", None)
    if packed:
        rec["text"] = zlib.decompress(base64.b64decode(packed)).decode("utf-8")
    return Speech(**rec)


def save_corpus(speeches: list[Speech], path: str | Path,
                keep_all_text: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for s in speeches:
            f.write(json.dumps(_record(s, keep_all_text), ensure_ascii=False) + "\n")


def load_corpus(path: str | Path) -> list[Speech]:
    path = Path(path)
    out: list[Speech] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(_from_json(line))
    return out


def iter_corpus(path: str | Path) -> Iterator[Speech]:
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield _from_json(line)
