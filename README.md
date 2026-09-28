# BoCLock — Bank of Canada Governing Council hawkishness

An LLM pairwise tournament that scores Bank of Canada monetary-policy communication
on a hawkish–dovish spectrum, and publishes the result as a static site:
**https://james-j-liu.github.io/BoCLock/**

It is the Bank of Canada counterpart to [MPCLock](https://james-j-liu.github.io/mpclock/)
(Bank of England) and ECBLock, and all follow the method of
[FedLock](https://jnathan9.github.io/fedlock/): an LLM judge reads two anonymised
documents side by side, with the macro conditions of each, and picks the more
hawkish *relative to those conditions*; TrueSkill turns ~30 such comparisons per
document into a continuous score.

## What is scored

| | |
|---|---|
| **Governing Council members** | Every monetary-policy speech by a member of the Governing Council — the Governor, the Senior Deputy Governor, the Deputy Governors and (since 2023) the external Deputy Governors — 1995 to today, **only while they sat on the Council** (`roster_gc.TENURE`; Carney and Macklem each served twice). Plus their **evidence to Parliament** — House of Commons Finance Committee and Senate Banking Committee hearings, split per member (their opening statement and answers, each answer preceded by its question). Speeches by officials who never sit on the Council (COO, department heads, research staff) are excluded entirely. |
| **"BoC Governing Council"** | The Council's own output, as one composite speaker: every **rate announcement** (8 a year since Dec 2000), every **Monetary Policy Report** since May 1995 (full PDF, one document each), the **Summaries of Governing Council deliberations** (2023–), and the **press-conference opening statements**. |

The Council decides by consensus and publishes no votes, so — unlike MPCLock —
there is no vote series.

## Is there enough material?

Yes, comfortably. As built on 2026-09-27:

| Source | Records | Policy-relevant |
|---|---:|---:|
| Speeches (bankofcanada.ca + 12 BIS-only backfills) | 535 | ~390 |
| House Finance Committee hearings, per member (1998–) | 115 | 109 |
| Parliamentary opening statements not (yet) replaced by a transcript | 54 | ~52 |
| Press-conference opening statements | 125 | 125 |
| Rate announcements | 205 | 205 |
| Monetary Policy Reports | 117 | 117 |
| Summaries of deliberations | 31 | 31 |
| **Total** | **1,182** | **1,032** |

That is ~80% of MPCLock's pool (1,261), and every year from 1998 has 20+ documents.
The thin spot is 1995–2000 (Thiessen era), when the Bank's online archive holds
10–15 speeches a year and the Deputy Governors of the day barely appear.

## Sources

- **Primary — bankofcanada.ca.** The WordPress REST API is closed to anonymous
  users, so content comes from the server-rendered listings (`?mt_page=N`):
  `/press/speeches/` (~870 items back to 1995), `/press/press-releases/` (rate
  announcements, by title) and `/publications/mpr/`. Summaries of deliberations
  cannot be paginated on their listing, so they are found in `wp-sitemap.xml`.
  Newer item pages put the text in a `bochtml` content module rather than the
  `post-content` div (`corpus/boc_site.page_text`). MPR text comes from the PDF.
- **Cross-check — BIS central bankers' speeches** (`speeches.zip`, 603 BoC
  speeches). The site is more complete in every year; BIS contributes 12 speeches
  the site lacks. BIS files the press-conference statements under the Governor, so
  duplicates are caught by 8-gram text overlap, not by speaker.
- **Parliament.** House of Commons FINA evidence (`/Committees/en/FINA/Meetings?parl=P&session=S`
  lists meetings; the transcript is XML from 2006, HTML before) and Senate BANC evidence
  (`/umbraco/surface/CommitteesAjax/GetTablePartialView?tableName=Meetings&committeeId=1003&selectedSession=P-S&TabSelected=PAST&PageSize=100&p=N`,
  which lists witnesses and, from 2011, transcript links; older transcripts come from the
  session's issue pages). Each hearing is split per Council witness
  (`corpus/parliament.py`), speaker labels replaced by QUESTION/ANSWER, and supersedes
  the separately published opening statement for the same chamber. **sencanada.ca
  blocks an IP for hours after a few requests to its listing endpoint** (it happened
  locally and on a GitHub runner, even at one request per 5 s): requests to it are
  spaced, sent with the Referer/XHR headers its own pages use, and abandoned for the
  run after two timeouts (`boc_site.HostDown`). So the Senate is covered for the current
  session only (fetched daily); older Senate hearings are still represented by their
  published opening statements. To retry the history, push
  `data/processed/backfill_senate.request` or run the workflow with *backfill_senate*.

## Findings

- **Announcement-day yields** (`scripts/announcement_reaction.py`, 202 fixed-date
  announcements 2001–2026). The 2-year GoC yield change that day is explained far better
  by the *change in the announcement's tone* than by the decision: R² 0.04 → 0.18,
  +2.6bp per point of tone (t = 4.9); +1.9bp (t = 3.4) with the change in decision
  controlled for; significant on holds alone, excluding 2008–09/2020, with the tails
  trimmed, and before and after 2010 separately.
- **Decisions** (`macro/boc_decisions.py`): parsed from each announcement's opening
  sentence; every level since 2009 matches Valet V39079. Shown as the *BoC decision*
  overlay.
- **Pairing fix + rebalance**: the Swiss step used to give 60% of all comparisons to the
  ~100 most dovish documents. After the fix and a top-up to 45 appearances' worth of
  comparisons, every document has ≥25 (median 30, was 15); mean sigma 2.0 → 1.38.
- **Macro context — Bank of Canada Valet API** (CPI, CPI-trim, CPI-median, policy
  rate, 10-year GoC yield) and **Statistics Canada WDS** (unemployment, real GDP).
  Each series is lagged by its publication delay so the judge sees only what had
  been released on the document's date.

### Looked at, not included

- **Press-conference Q&A.** The Bank publishes webcasts only, no transcripts.
- **Media interviews.** `/content_type/press/selected-interviews/` links ~50
  interviews (2020–), almost all on paywalled sites (Globe and Mail, FT, Reuters,
  The Logic) or audio/video.

## Pipeline

```
corpus/       boc_speeches · boc_council · parliament · bis_boc -> data/processed/corpus.jsonl
process/      classify (policy relevance, with a second-opinion model on rejects)
              anonymize (5 layers)
judge/        jev (pairwise + direct, default) · openrouter / direct (chat fallback)
tournament/   TrueSkill engine + Swiss/uncertainty pairing
output/       era adjustment -> site/data.json
site/         static Plotly site (Timeline · Rankings · Speaker · Data · Methodology)
```

Scoring runs on TypeSafe's **Jev** decision model (`typesafe/jev-1.13`) via
OpenRouter's decisions API. Verdicts under 60% confidence are recorded as TrueSkill
draws. Classification uses Gemini 2.5 Flash-Lite, and every rejection is re-asked of
Gemini 2.5 Flash (`judge.classifier_recheck_model`): Flash-Lite alone dropped
economic-outlook speeches that name no policy action.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env                        # add OPENROUTER_API_KEY

python -m boclock.corpus.assemble          # scrape the corpus (~20 min, cached)
python scripts/classify_corpus.py --gc-only
python scripts/build_macro.py
python scripts/run_full.py --appearances 30 --concurrency 20 --resume
python -m http.server 8233 --directory site
```

`scripts/daily_update.py` is the incremental version: it reads the newest three
pages of each listing and the sitemap, scrapes only unseen URLs, classifies and
scores only what is new, and rewrites `site/data.json` and `site/macro.json`. It
runs from `.github/workflows/daily.yml` at 07:00 UTC and deploys the site to
GitHub Pages.

## Deploying

1. Create the GitHub repo (`james-j-liu/BoCLock`) and push `main`.
2. Settings → Pages → Source: **GitHub Actions**.
3. Settings → Secrets → Actions: add `OPENROUTER_API_KEY`.

## State in the repo

`data/processed/corpus.jsonl` (text + classifier verdicts + ratings) and
`data/processed/tournament_log.jsonl` (every comparison ever paid for) are committed
deliberately: they are the pipeline's memory and make the daily run incremental.
Texts over 2,000 characters are stored zlib-compressed (base64, so the file stays
JSONL); speeches by non-Council officials keep metadata only.
