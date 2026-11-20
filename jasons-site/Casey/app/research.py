"""What runs while she is not looking, and what it is allowed to say.

Jason, 2026-09-06: "in the background id like to be doing background
information and update her on the new information so she knows there is
new information pulled."

THREE SOURCES, AND THEY ARE NOT EQUALLY TRUSTED
------------------------------------------------
1. THE CALENDAR (below). Dates, transcribed from
   knowledge/30-awards-catalog.md, which recorded where each one came
   from. Deterministic: no model is asked what day it is. This is the
   half that produces "AMSUS opens in eight weeks and somebody else has
   to nominate you, so ask now".
2. HER OWN RECORD. progress() already knows what is finished and not
   sent, and what has gone quiet. Also deterministic, also free.
3. A MODEL, and only for the one thing the first two cannot do: reading
   an entry she wrote and saying which award it could support and what
   is missing from it. It is given her record and the catalog and asked
   to MATCH them -- never to supply a fact of its own.

WHY THAT SPLIT MATTERS MORE HERE THAN ALMOST ANYWHERE
A career portal that invents an award deadline does not merely mislead
her, it makes her miss the real one. So no finding in this file gets its
dates from a model, every calendar finding carries the source the catalog
cited, and the wording tells her to confirm -- which is what the catalog
itself says to do in its own opening line.

WHAT TRIGGERS A PASS
Her record changing, not a clock. A scan run against an unchanged record
costs a model call and can only reach the conclusion it reached last
time. The calendar half is checked hourly regardless, because a date can
come due while she does nothing -- that is rather the point of a date.

DRIFT
The calendar below duplicates dates that also live in the catalog
markdown, and duplicated facts drift apart. catalog_drift() reads the
markdown and reports any award named here that has gone missing from it,
so the pair failing to agree is visible instead of silent.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta

from . import config, db, llm, portfolio

# ---------------------------------------------------------------------------
#  THE CALENDAR
#
#  Transcribed from knowledge/30-awards-catalog.md ("THE CALENDAR --
#  researched 4 September 2026"), which names its sources per row. Read
#  that file for the reasoning; this is the machine-readable half.
#
#  lead_days is the number this file exists for. A deadline is not the
#  moment to act on a deadline: AMSUS has to be entered by somebody else,
#  so the useful alert fires when there is still time to ASK a supervisor,
#  not when nominations close. Every lead time here is the catalog's own
#  advice turned into a number.
# ---------------------------------------------------------------------------

CALENDAR = [
    {
        "key": "amsus",
        "name": "AMSUS nominations",
        # 2026 cycle closed 20 Nov 2025; the next annual meeting cycle is
        # the live target. Month-precision on purpose -- the catalog does
        # not have a confirmed day and inventing one would be a lie with
        # a decimal point on it.
        "month": 11, "day": 20,
        "lead_days": 120,
        "what": "Fifteen awards; the ones that fit are Nursing, Rising Star, "
                "Innovator and Operational Medicine.",
        "action": "SOMEONE ELSE HAS TO NOMINATE YOU. Ask a supervisor now -- "
                  "not in November. That conversation is the long pole, not "
                  "the paperwork.",
        "source": "amsus.swoogo.com (2026 awards). Confirm the date -- the "
                  "2026 cycle was extended once.",
    },
    {
        "key": "modimes",
        "name": "March of Dimes Nurse of the Year",
        "month": 7, "day": 19,
        "lead_days": 75,
        "what": "State and chapter specific; the 2026 window ran 4 May - 19 Jul.",
        "action": "Find the chapter for the state you are stationed in -- the "
                  "window and the categories are set locally.",
        "source": "heroesinaction.marchofdimes.org.",
    },
    {
        "key": "afms",
        "name": "AFMS annual awards (MTF suspense)",
        "month": 12, "day": 1,
        "lead_days": 90,
        "what": "Winners are announced Feb-Mar, so the local suspense falls in "
                "the autumn.",
        "action": "POLICY UNVERIFIED in the catalog -- the real date comes from "
                  "your Chief Nurse or the awards monitor. Ask; do not assume "
                  "this one.",
        "source": "Inferred from AFMS announcement timing. Not confirmed.",
    },
]

# ---------------------------------------------------------------------------
#  STANDING ACTIONS -- live regardless of any date
#
#  THE LEAD-TIME RULE ABOVE HAD A HOLE IN IT AND THIS IS THE PATCH.
#  Every entry in CALENDAR is suppressed until its deadline comes within
#  lead_days. Run against AWHONN that produced exactly the wrong result:
#  its deadline is 1 September, so for eleven months of the year it said
#  nothing -- about the item the catalog itself calls "the single most
#  consequential fact in this file".
#
#  The reason is that AWHONN's real constraint is not its deadline, it is
#  a THREE-YEAR MEMBERSHIP CLOCK that only starts when she joins. A
#  deadline you can act on the week before is not the same kind of object
#  as a clock where every day of delay costs a day at the far end, and
#  scheduling them the same way silences the second kind.
#
#  So these have no date and are never suppressed. They stop when the
#  thing is done -- which is a question only she can answer, so each one
#  says what would make it go away.
# ---------------------------------------------------------------------------

STANDING = [
    {
        "key": "awhonn-clock",
        "name": "The AWHONN three-year clock",
        "urgency": "now",
        "what": "Nominees must be an active voting AWHONN member for three "
                "consecutive years BEFORE nomination, and hold it through the "
                "nomination year. Seven categories are behind that gate; "
                "Practice and Innovation are close to a description of the "
                "QBL work.\n\n"
                "Every day not joined is a day added to the far end. That is "
                "what makes it urgent while the deadline itself is a year "
                "away -- the deadline is not the constraint, the clock is.",
        "action": "If you are not a member: join. That is the entire action "
                  "and it costs a membership fee. If you ARE a member: find "
                  "out what YEAR you joined, because that decides whether "
                  "Sep 2027 is open to you or Sep 2028.",
        "source": "awhonn.org (Awards of Excellence). Catalog, 'The AWHONN "
                  "gate is a three-year clock'.",
        "resolves": "Tell the portal you have joined and what year, and this "
                    "stops.",
    },
    {
        "key": "daisy",
        "name": "The DAISY Award has no cycle",
        "urgency": "normal",
        "what": "Nominated by patients, families and colleagues at any time, "
                "and confirmed live at military treatment facilities in 2026.",
        "action": "Find out whether YOUR facility is a DAISY partner. That is "
                  "the only open question -- there is no window to miss and "
                  "nothing to submit yourself.",
        "source": "Catalog, Tier 3. dvidshub.net (Navy DAISY 2026).",
        "resolves": "Answer yes or no once and this stops.",
    },
]


# Quarterly, so it gets its own handling rather than a fixed date.
FGOQ = {
    "key": "fgoq",
    "name": "Field Grade Officer of the Quarter",
    "lead_days": 30,
    "what": "The most attempts per year and the shortest feedback loop -- the "
            "one to build the habit on.",
    "action": "Packages are typically due the 25th-26th of the month after the "
              "quarter ends. Confirm the suspense with your awards monitor.",
    "source": "Catalog, Tier 3. Suspense is local -- confirm it.",
}


def _fingerprint(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def _next_occurrence(month: int, day: int, today: date) -> date:
    """The next time this month/day comes round, this year or next."""
    try:
        this_year = date(today.year, month, day)
    except ValueError:                     # 29 Feb and friends
        this_year = date(today.year, month, 28)
    if this_year >= today:
        return this_year
    try:
        return date(today.year + 1, month, day)
    except ValueError:
        return date(today.year + 1, month, 28)


def _fgoq_due(today: date) -> date:
    """The next quarterly package date: the 25th of the month after a
    quarter ends (Jan / Apr / Jul / Oct)."""
    for m in (1, 4, 7, 10):
        d = date(today.year, m, 25)
        if d >= today:
            return d
    return date(today.year + 1, 1, 25)


def _urgency(days: int, lead: int) -> str:
    if days <= max(14, lead // 6):
        return "now"
    if days <= lead:
        return "soon"
    return "normal"


def calendar_findings(today: date | None = None) -> list[dict]:
    """What the dates say today. No model involved, and none needed."""
    today = today or date.today()
    out = []
    for item in CALENDAR:
        due = _next_occurrence(item["month"], item["day"], today)
        days = (due - today).days
        if days > item["lead_days"]:
            continue                       # too far off to be useful yet
        out.append({
            "fingerprint": _fingerprint("cal", item["key"], due.isoformat()),
            "kind": "deadline",
            "urgency": _urgency(days, item["lead_days"]),
            "title": f"{item['name']} — {days} days out ({due:%d %b %Y})",
            "body": f"{item['what']}\n\nSource: {item['source']}",
            "action": item["action"],
            "source": item["source"],
        })
    for item in STANDING:
        out.append({
            # No date in the fingerprint: a standing action is one row
            # forever, and times_seen is what shows how long it has stood.
            "fingerprint": _fingerprint("standing", item["key"]),
            "kind": "standing",
            "urgency": item["urgency"],
            "title": item["name"],
            "body": f"{item['what']}\n\n{item['resolves']}\n\n"
                    f"Source: {item['source']}",
            "action": item["action"],
            "source": item["source"],
        })
    due = _fgoq_due(today)
    days = (due - today).days
    if days <= FGOQ["lead_days"]:
        out.append({
            "fingerprint": _fingerprint("cal", "fgoq", due.isoformat()),
            "kind": "deadline",
            "urgency": _urgency(days, FGOQ["lead_days"]),
            "title": f"{FGOQ['name']} — package due about {due:%d %b}",
            "body": f"{FGOQ['what']}\n\nSource: {FGOQ['source']}",
            "action": FGOQ["action"],
            "source": FGOQ["source"],
        })
    return out


def record_findings() -> list[dict]:
    """What her own record says, with no model and no outside facts.

    progress() already computes all of this for the dashboard. The
    difference is that a dashboard is only true while she is looking at
    it, and a finding waits for her.
    """
    p = portfolio.progress()
    out = []
    ready = p.get("ready_unsent") or []
    if ready:
        titles = "; ".join(e["title"] for e in ready[:6] if e.get("title"))
        out.append({
            # Fingerprinted on the COUNT, so finishing another one is a
            # new finding and re-running the scan is not.
            "fingerprint": _fingerprint("ready", len(ready)),
            "kind": "gap",
            "urgency": "soon",
            "title": f"{len(ready)} finished and not submitted",
            "body": (f"{titles}\n\nThis is the most recoverable thing in the "
                     "whole record: the writing is already done."),
            "action": "Pick one and file it against a live category.",
            "source": "Your own portfolio.",
        })
    stale = p.get("stale") or []
    if stale:
        out.append({
            "fingerprint": _fingerprint("stale", len(stale)),
            "kind": "gap",
            "urgency": "normal",
            "title": f"{len(stale)} untouched for over {p['stale_days']} days",
            "body": "; ".join(e["title"] for e in stale[:6] if e.get("title")),
            "action": "Either finish one or mark it dropped — a draft that is "
                      "neither is the thing that quietly eats the year.",
            "source": "Your own portfolio.",
        })
    if p.get("total", 0) == 0:
        out.append({
            "fingerprint": _fingerprint("empty", "start"),
            "kind": "gap",
            "urgency": "normal",
            "title": "Nothing in the record yet",
            "body": ("The quarterly package is the cheapest place to start: "
                     "it comes round four times a year, so a first attempt "
                     "costs one quarter rather than one year."),
            "action": "Say one thing you did this month. It does not have to "
                      "be finished writing — it has to exist.",
            "source": "Your own portfolio.",
        })
    return out


# ---------------------------------------------------------------------------
#  The model half. Matching only.
# ---------------------------------------------------------------------------

MATCH_SYSTEM = """You match a nurse officer's own record against an awards
catalog she already has. You are matching, not researching.

HARD RULES
- Never state a deadline, eligibility rule, membership requirement or award
  name that is not in the material you were given. If you think one exists
  and it is not here, say the catalog does not cover it.
- Never inflate what she did. Her writing rules draw a hard line between the
  scope she actually held and the scope of the thing she touched. If an entry
  claims more than it shows, say so plainly -- that is more useful to her than
  encouragement.
- Her Master's is IN PROGRESS. Never write it as held.
- If an entry is too thin to match anything, say that. "Nothing here yet" is a
  real answer and a useful one.

Reply as JSON only:
{"findings": [{"title": "...", "body": "...", "action": "...",
               "award": "...", "urgency": "normal|soon|now"}]}
At most 4 findings. Leave the list empty if the record supports nothing yet.
"""


def _record_digest(limit: int = 40) -> str:
    rows = db.portfolio_list(limit=limit)
    if not rows:
        return "(the portfolio is empty)"
    out = []
    for r in rows:
        bits = [f"[{r['id']}] {r['title'] or '(untitled)'}",
                f"status={r['status']} category={r['category']}"]
        if r.get("award_target"):
            bits.append(f"aimed at {r['award_target']}")
        for f in ("situation", "task", "action", "result"):
            v = (r.get(f) or "").strip()
            if v:
                bits.append(f"{f}: {v[:300]}")
        out.append(" | ".join(bits))
    return "\n\n".join(out)


def match_findings(system_prompt: str = "") -> list[dict]:
    """Ask the model to match her record to the catalog it was given.

    Returns [] on any failure. This is the enhancement half -- the
    calendar and her own record already produce findings without it, and
    a model being down must not mean an empty panel.
    """
    digest = _record_digest()
    if digest.startswith("(the portfolio is empty"):
        return []                          # nothing to match
    system = (system_prompt + "\n\n" + MATCH_SYSTEM) if system_prompt else MATCH_SYSTEM
    user = ("Here is her record as it stands today.\n\n" + digest +
            "\n\nWhich awards in the catalog does this actually support, and "
            "what is missing from each entry that would make it usable? "
            "Match only against the catalog you were given.")
    try:
        answer, model = llm.ask(system, user, temperature=0.2)
        data = llm.extract_json(answer)
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "research", f"match pass failed: {e}")
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for f in (data.get("findings") or [])[:4]:
        if not isinstance(f, dict):
            continue
        title = str(f.get("title") or "").strip()
        if not title:
            continue
        body = str(f.get("body") or "").strip()
        out.append({
            # Fingerprinted on the TITLE plus the record's own size, so
            # the same observation about the same record is one row, but
            # the same observation after she adds an entry is new again.
            "fingerprint": _fingerprint("match", title.lower(), len(digest)),
            "kind": "match",
            "urgency": str(f.get("urgency") or "normal"),
            "title": title,
            "body": body + (f"\n\nAward: {f['award']}" if f.get("award") else ""),
            "action": str(f.get("action") or "").strip(),
            "source": f"Matched against your catalog by {model}.",
        })
    return out


# ---------------------------------------------------------------------------
#  Drift
# ---------------------------------------------------------------------------

def catalog_drift() -> list[str]:
    """Awards this file schedules that the catalog no longer mentions.

    The dates above are a transcription, and a transcription rots. This
    does not try to re-parse the markdown -- it only asks whether each
    award is still named in it, which is enough to catch the case that
    actually happens: the catalog is rewritten and this file is not.
    """
    try:
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                         for p in llm.knowledge_files())
    except Exception:  # noqa: BLE001
        return []
    low = text.lower()
    gone = []
    for item in [*CALENDAR, *STANDING, FGOQ]:
        # First distinctive word of the name -- "AMSUS", "AWHONN", "March",
        # "AFMS", "Field". Whole names differ in punctuation between the
        # two files and would false-positive constantly.
        needle = item["name"].split()[0].lower()
        if needle not in low:
            gone.append(item["name"])
    return gone


# ---------------------------------------------------------------------------
#  A pass
# ---------------------------------------------------------------------------

def scan(system_prompt: str = "", use_model: bool = True) -> dict:
    """One full pass. Returns what it found and how much of it is new."""
    found, new_ids = [], []
    found.extend(calendar_findings())
    found.extend(record_findings())
    if use_model:
        found.extend(match_findings(system_prompt))
    for drifted in catalog_drift():
        found.append({
            "fingerprint": _fingerprint("drift", drifted),
            "kind": "drift",
            "urgency": "normal",
            "title": f"The catalog no longer mentions {drifted}",
            "body": ("research.py still schedules it. One of the two is out of "
                     "date and they should be reconciled before the date it "
                     "carries is trusted."),
            "action": "For Jason, not for her.",
            "source": "Consistency check.",
        })
    new_count = 0
    for f in found:
        fid, is_new = db.finding_upsert(
            f["fingerprint"], f["kind"], f["title"], f["body"],
            action=f.get("action", ""), urgency=f.get("urgency", "normal"),
            source=f.get("source", ""))
        if is_new:
            new_count += 1
            new_ids.append(fid)
    db.log_event("info", "research",
                 f"scan: {len(found)} findings, {new_count} new")
    return {"total": len(found), "new": new_count, "new_ids": new_ids}


# ---------------------------------------------------------------------------
#  Immediate feedback, at the moment she saves something
# ---------------------------------------------------------------------------

FEEDBACK_SYSTEM = """You are reading ONE entry a nurse officer just wrote for
her own record, and answering immediately while she is still looking at it.

Say, in this order and briefly:
1. What this could count toward, from the catalog you were given. If nothing
   yet, say so.
2. The single most useful thing missing. Usually it is a measurable result or
   who else was affected -- not more adjectives.
3. If it claims more scope than it shows, say so directly. Her writing rules
   treat that as the one failure that gets a package returned.

Under 120 words. Speak to her, not about her. No preamble, no praise padding.
Never invent an award, a deadline or a rule that is not in the material given.
Never state her Master's as finished.

Reply as JSON only:
{"counts_toward": "...", "missing": "...", "scope_warning": "", "encouragement": ""}
scope_warning is "" when there is nothing wrong with the scope.
"""


def feedback(entry: dict, system_prompt: str = "") -> dict:
    """What to show her the moment she saves an entry. {} if unavailable."""
    parts = [f"Title: {entry.get('title') or '(untitled)'}",
             f"Category: {entry.get('category') or ''}"]
    if entry.get("award_target"):
        parts.append(f"She is aiming this at: {entry['award_target']}")
    for f in ("situation", "task", "action", "result", "evidence", "skills"):
        v = (entry.get(f) or "").strip()
        if v:
            parts.append(f"{f.capitalize()}: {v}")
    system = ((system_prompt + "\n\n" + FEEDBACK_SYSTEM)
              if system_prompt else FEEDBACK_SYSTEM)
    try:
        answer, model = llm.ask(system, "\n".join(parts), temperature=0.2)
        data = llm.extract_json(answer)
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "research", f"feedback failed: {e}")
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "counts_toward": str(data.get("counts_toward") or "").strip(),
        "missing": str(data.get("missing") or "").strip(),
        "scope_warning": str(data.get("scope_warning") or "").strip(),
        "encouragement": str(data.get("encouragement") or "").strip(),
        "model": model,
    }
