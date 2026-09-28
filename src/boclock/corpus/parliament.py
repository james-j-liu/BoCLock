"""Parliamentary hearings with Governing Council witnesses, split into one document per member.

Twice a year, after a Monetary Policy Report, the Governor and Senior Deputy
Governor appear before the House of Commons Standing Committee on Finance (FINA)
and the Senate Standing Committee on Banking, Commerce and the Economy (BANC):
an opening statement, then an hour or more of questions. The Bank publishes the
opening statement (boc_speeches picks it up); the questions and answers exist only
in Parliament's transcripts, which are fetched here.

Each hearing is split by witness, as MPCLock does for the Treasury Committee: one
document per Council member, holding their own words (opening statement included)
and, before each answer, the question it answers. Speaker labels are replaced by
QUESTION / ANSWER so no parliamentarian's name reaches the judge. A hearing with a
transcript supersedes the separately published opening statement (supersede()).

House   /Committees/en/FINA/Meetings?parl=P&session=S lists every meeting with its
        date, study and evidence link. Candidates are meetings whose study names the
        Bank or its Report, or which fall on the date of a published BoC opening
        statement; the transcript itself decides (a Council member must speak).
        From 2006 the evidence has an XML version (<Intervention>/<PersonSpeaking>/
        <ParaText>); before that, HTML with bold "Name (Title, Bank of Canada):" labels.
Senate  /umbraco/surface/CommitteesAjax/GetTablePartialView lists meetings with their
        witnesses (100 a page, p=N) for every session back to 1994. From 2011 each row
        links its transcript; earlier ones are found on the session's issue pages
        (/en/Content/SEN/Committee/<ps>/bank/<n>cv-e), matched by date. HTML with bold
        "Name, Title, Bank of Canada:" / "Mr. Dodge:" labels.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import re
from concurrent.futures import ThreadPoolExecutor

from ..roster_gc import TENURE, canon
from ..schema import ST_TESTIMONY, Speech
from . import boc_site

OC = "https://www.ourcommons.ca"
SEN = "https://sencanada.ca"
SEN_BANC_ID = 1003

# (parliament, session) since the Council was created in 1994
SESSIONS = [(35, 1), (35, 2), (36, 1), (36, 2), (37, 1), (37, 2), (37, 3), (38, 1),
            (39, 1), (39, 2), (40, 1), (40, 2), (40, 3), (41, 1), (41, 2), (42, 1),
            (43, 1), (43, 2), (44, 1), (45, 1)]

HOUSE = "House of Commons Finance Committee"
SENATE = "Senate Banking Committee"

_BANK_STUDY_RE = re.compile(r"Bank of Canada|Monetary Policy", re.I)
_LABEL_SPLIT_RE = re.compile(
    r"<b>\s*((?:(?!</b>)[^<]|<(?!/?b>)[^>]*>){3,200}?)\s*</b>\s*:?", re.I)
_NOISE_RE = re.compile(r"^\[(?:English|Translation|Français|French|Traduction)\]$|^[◊•]\s*\d{4}$",
                       re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(_html.unescape(_TAG_RE.sub(" ", fragment)).split())


# --- identifying Council witnesses in speaker labels ---------------------------
_SURNAMES: dict[str, str] = {}
for _p in TENURE:
    _SURNAMES.setdefault(_p.split()[-1].lower(), _p)


def _member_in(label: str, day: str) -> str | None:
    """The Council member a full witness label names ("Mr. Gordon Thiessen (Governor,
    Bank of Canada)", "Tiff Macklem, Governor, Bank of Canada"), if any."""
    if "bank of canada" not in label.lower():
        return None
    for surname, person in _SURNAMES.items():
        if re.search(rf"\b{re.escape(surname)}\b", label, re.I):
            return person
    return None


def _is_member_label(label: str) -> bool:
    """Labels of parliamentarians: chairs, senators, and MPs (riding, party)."""
    low = label.lower()
    return (low.startswith(("senator", "the chair", "the vice-chair", "the deputy chair",
                            "the chairman", "the chairperson", "hon. senator", "le président"))
            or bool(re.search(r"\([^)]*,\s*(?:Lib|CPC|Cons|NDP|BQ|Bloc|Ref|PC|Green|GP|Ind|"
                              r"Canadian Alliance|Alliance)\.?\)", label)))


class _Speakers:
    """Maps each label in one hearing to a Council member (or None). A member is first
    named in full with 'Bank of Canada'; later labels use the surname alone
    ("Mr. Dodge"), which counts only once that surname has been seen as a witness —
    so Senator Lowell Murray is never taken for Deputy Governor John Murray."""

    def __init__(self, day: str):
        self.day = day
        self.seen: dict[str, str] = {}

    def who(self, label: str) -> str | None:
        if _is_member_label(label):
            return None
        m = _member_in(label, self.day)
        if m:
            self.seen[m.split()[-1].lower()] = m
            return m
        for surname, person in self.seen.items():
            if re.search(rf"\b{re.escape(surname)}\b", label, re.I):
                return person
        return None


def _is_banker_label(label: str) -> bool:
    return "bank of canada" in label.lower()


# --- transcript parsing -------------------------------------------------------
def turns_from_xml(x: str) -> list[tuple[str, str]]:
    out = []
    for iv in re.findall(r"<Intervention\b.*?</Intervention>", x, re.S):
        lab = re.search(r"<PersonSpeaking>(.*?)</PersonSpeaking>", iv, re.S)
        paras = [_text(p) for p in re.findall(r"<ParaText[^>]*>(.*?)</ParaText>", iv, re.S)]
        paras = [p for p in paras if p and not _NOISE_RE.match(p)]
        if lab and paras:
            out.append((_text(lab.group(1)).rstrip(": "), "\n".join(paras)))
    return out


def turns_from_html(h: str) -> list[tuple[str, str]]:
    """Speaker turns from an HTML transcript: each turn starts at a bold label that
    ends in a colon and runs to the next one."""
    body = h
    for marker in ("publication-container-content", "<main", "<body"):
        i = h.find(marker)
        if i >= 0:
            body = h[i:]
            break
    marks = []
    for m in _LABEL_SPLIT_RE.finditer(body):
        raw = _text(m.group(1))
        tail = body[m.end() - 1:m.end()]
        if not (raw.endswith(":") or tail == ":"):
            continue
        label = raw.rstrip(": ").strip()
        if 2 <= len(label.split()) <= 25 or label.lower().startswith("the chair"):
            marks.append((m.start(), m.end(), label))
    out = []
    for k, (s, e, label) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(body)
        chunk = body[e:end]
        chunk = re.split(r"<footer|class=\"footer|id=\"footer", chunk)[0]
        paras = [_text(p) for p in re.split(r"</?p[^>]*>|<br\s*/?>", chunk, flags=re.I)]
        paras = [p for p in paras if p and not _NOISE_RE.match(p) and not re.fullmatch(r"[◊•\s\d]+", p)]
        if paras:
            out.append((label, "\n".join(paras)))
    return out


def split_by_member(turns, day: str) -> dict[str, str]:
    """person -> their document: every answer, preceded by the question it answers."""
    who = _Speakers(day)
    docs: dict[str, list[str]] = {}
    prev_q = None
    for label, text in turns:
        person = who.who(label)
        if person:
            first = person not in docs
            parts = docs.setdefault(person, [])
            # a member's first turn is usually the opening statement, preceded by the
            # chair's welcome rather than a question
            if prev_q and not first:
                parts.append("QUESTION: " + prev_q)
            parts.append("ANSWER: " + text)
            prev_q = None
        elif _is_banker_label(label):
            prev_q = None          # another Bank official (not on the Council) answered
        else:
            # a parliamentarian: the latest substantive turn is the pending question
            if len(text.split()) >= 12:
                prev_q = text
    return {p: "\n\n".join(v) for p, v in docs.items()}


def _records(turns, day: str, chamber: str, url: str) -> list[Speech]:
    out = []
    for person, text in split_by_member(turns, day).items():
        answer_words = sum(len(b.split()) for b in text.split("\n\n") if b.startswith("ANSWER"))
        if answer_words < 150:
            continue
        out.append(Speech(date=day, speaker=canon(person),
                          title=f"{chamber} — evidence, {day}", text=text,
                          source_type=ST_TESTIMONY, institution=chamber, source_url=url))
    return out


# --- House of Commons FINA ----------------------------------------------------
def house_meetings(parl: int, sess: int, use_cache: bool = True) -> list[dict]:
    h = boc_site.get(f"{OC}/Committees/en/FINA/Meetings?parl={parl}&session={sess}",
                     use_cache=use_cache) or ""
    out = []
    for day, block in re.findall(r'<a name="(\d{4}-\d\d-\d\d)"></a>(.*?)'
                                 r'(?=<a name="\d{4}-\d\d-\d\d"></a>|\Z)', h, re.S):
        ev = re.search(r'href="(//www\.ourcommons\.ca/DocumentViewer/en/[\d-]+/FINA/'
                       r'meeting-\d+/evidence)"', block)
        if not ev:
            continue
        studies = " ".join(_text(s) for s in re.findall(
            r'studies-activities-item">(.*?)</div>', block, re.S))
        out.append({"date": day, "url": "https:" + ev.group(1), "studies": studies})
    return out


def house_hearing(m: dict, use_cache: bool = True) -> list[Speech]:
    h = boc_site.get(m["url"], use_cache=use_cache)
    if not h or "Bank of Canada" not in h:
        return []
    xml = re.search(r'href="(/Content/Committee/[^"]+-E\.XML)"', h, re.I)
    turns = []
    if xml:
        x = boc_site.get(OC + xml.group(1), use_cache=use_cache)
        turns = turns_from_xml(x or "")
    if not turns:
        turns = turns_from_html(h)
    return _records(turns, m["date"], HOUSE, m["url"])


# --- Senate BANC --------------------------------------------------------------
def senate_meetings(ps: str, use_cache: bool = True) -> list[dict]:
    out, seen, p = [], set(), 1
    while True:
        u = (f"{SEN}/umbraco/surface/CommitteesAjax/GetTablePartialView?tableName=Meetings"
             f"&committeeId={SEN_BANC_ID}&selectedSession={ps}&isCommitteeSpecific=true"
             f"&TabSelected=PAST&PageSize=100&p={p}&Lang=en")
        h = boc_site.get(u, use_cache=use_cache) or ""
        new = 0
        for row in re.findall(r"<tr>(.*?)</tr>", h, re.S):
            mid = re.search(r"noticeofmeeting/(\d+)", row)
            if not mid or mid.group(1) in seen:
                continue
            seen.add(mid.group(1))
            new += 1
            when = re.search(r"noticeofmeeting[^>]*>\s*([A-Z][a-z]{2} \d\d, \d{4})", row)
            if not when:
                continue
            day = _dt.datetime.strptime(when.group(1), "%b %d, %Y").date().isoformat()
            ev = re.search(r'href="([^"]*/\d+ev[a-z]?-\d+-e)"', row)
            out.append({"date": day, "ps": ps, "row": row,
                        "url": (SEN + ev.group(1)) if ev else None})
        if not new:
            break
        p += 1
    return out


def _senate_issue_links(ps: str, use_cache: bool = True) -> dict[str, str]:
    """date -> evidence URL, from a pre-2011 session's issue pages."""
    code = ps.replace("-", "")
    idx = boc_site.get(f"{SEN}/en/committees/BANC/transcriptsminutes/{ps}", use_cache=use_cache) or ""
    covers = sorted(set(re.findall(r'href="(/en/Content/SEN/Committee/\d+/ban[ck]/\d+cv-e)',
                                   idx, re.I)))
    out = {}
    for cv in covers:
        h = boc_site.get(SEN + cv, use_cache=use_cache) or ""
        base = cv.rsplit("/", 1)[0]
        for href, label in re.findall(r'href="([^"]*ev[a-z]?(?:-\d+)?-e)"[^>]*>([^<]+)', h):
            m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", " ".join(label.split()))
            if not m:
                continue
            try:
                day = _dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
            except ValueError:
                continue
            url = href if href.startswith("http") else SEN + (href if href.startswith("/")
                                                               else f"{base}/{href}")
            out.setdefault(day, url)
    return out


def senate_hearing(m: dict, use_cache: bool = True) -> list[Speech]:
    if not m["url"]:
        return []
    h = boc_site.get(m["url"], use_cache=use_cache)
    if not h:
        return []
    return _records(turns_from_html(h), m["date"], SENATE, m["url"])


# --- loading ------------------------------------------------------------------
def _bank_row(row: str) -> bool:
    """A Senate meeting whose witness list includes a Council member."""
    if "Bank of Canada" not in row:
        return False
    return any(re.search(rf"\b{re.escape(p.split()[-1])}\b", row) for p in TENURE)


def load(use_cache: bool = True, statement_dates: set[str] | None = None,
         sessions=None, skip_urls: set | None = None, verbose: bool = True,
         concurrency: int = 4) -> list[Speech]:
    """Every FINA/BANC hearing with a Council witness, split per member.

    statement_dates: dates of the Bank's published parliamentary opening statements
    (each +-2 days), which flag House meetings whose study title does not name the Bank.
    """
    sessions = sessions or SESSIONS
    near = set()
    for d in statement_dates or ():
        t = _dt.date.fromisoformat(d)
        near |= {(t + _dt.timedelta(days=k)).isoformat() for k in range(-2, 3)}
    skip_urls = skip_urls or set()
    latest = sessions[-1]

    house, senate = [], []
    for parl, sess in sessions:
        cache = use_cache and (parl, sess) != latest     # the current session still grows
        ms = house_meetings(parl, sess, use_cache=cache)
        house += [m for m in ms if (_BANK_STUDY_RE.search(m["studies"]) or m["date"] in near)
                  and m["url"] not in skip_urls]
        ps = f"{parl}-{sess}"
        try:
            rows = [m for m in senate_meetings(ps, use_cache=cache) if _bank_row(m["row"])]
            if any(m["url"] is None for m in rows):
                links = _senate_issue_links(ps, use_cache=use_cache)
                for m in rows:
                    m["url"] = m["url"] or links.get(m["date"])
        except Exception as e:  # noqa: BLE001 - sencanada.ca blocks bursts; keep the House
            print(f"    [warn] Senate {ps}: {type(e).__name__}: {e}")
            rows = []
        senate += [m for m in rows if m["url"] not in skip_urls]

    # the Senate endpoint answers a session that does not exist yet (the daily run
    # probes the next one) with the current session's table, and a meeting can be
    # listed under two sessions: one fetch per transcript
    seen_urls: set = set()
    senate = [m for m in senate if not (m["url"] in seen_urls or seen_urls.add(m["url"]))]
    seen_urls = set()
    house = [m for m in house if not (m["url"] in seen_urls or seen_urls.add(m["url"]))]

    def work(fn, m):
        try:
            return fn(m, use_cache=use_cache)
        except Exception as e:  # noqa: BLE001 - one bad transcript is one lost hearing
            print(f"    [warn] {m.get('url')}: {type(e).__name__}: {e}")
            return []

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        h_docs = [s for r in ex.map(lambda m: work(house_hearing, m), house) for s in r]
        s_docs = [s for r in ex.map(lambda m: work(senate_hearing, m), senate) for s in r]
    if verbose:
        missing = sum(1 for m in senate if not m["url"])
        print(f"  parliament: House {len(house)} candidate meetings -> {len(h_docs)} member-documents; "
              f"Senate {len(senate)} Bank meetings ({missing} without a transcript link) "
              f"-> {len(s_docs)} member-documents")
    return list({s.id: s for s in h_docs + s_docs}.values())


def supersede(corpus: list[Speech], verbose: bool = True) -> list[Speech]:
    """Drop a published opening statement when the full transcript of that hearing,
    which contains it, is in the corpus for the same member (within two days)."""
    hearings = [(s.institution, canon(s.speaker), _dt.date.fromisoformat(s.date)) for s in corpus
                if s.source_type == ST_TESTIMONY and s.institution in (HOUSE, SENATE)]
    drop = set()
    for s in corpus:
        if s.source_type != ST_TESTIMONY or s.institution in (HOUSE, SENATE):
            continue
        # the Governor often appears before both chambers in the same week, so the
        # statement must be matched to a hearing of its own chamber
        chamber = SENATE if re.search(r"Senat", s.title) else HOUSE
        d = _dt.date.fromisoformat(s.date)
        if any(c == chamber and p == canon(s.speaker) and abs((d - hd).days) <= 2
               for c, p, hd in hearings):
            drop.add(s.id)
    if verbose and drop:
        print(f"  {len(drop)} opening statements superseded by their hearing transcripts")
    return [s for s in corpus if s.id not in drop]
