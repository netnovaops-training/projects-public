"""The portfolio: what she has actually done, in the shape a promotion
or an award nomination asks for.

WHY THIS EXISTS SEPARATELY FROM THE LOG. A transcript is a record of
talking; a portfolio is a record of DOING. Nobody reviewing her for a
promotion wants forty minutes of conversation -- they want the thing she
achieved, when, what it changed, and what proves it. So an entry here is
structured on purpose:

    situation / task / action / result / evidence

which is the shape every award nomination and competency framework asks
for, so the same entry serves both without rewriting.

TWO COPIES, DELIBERATELY.
  SQLite    beside the app -- the working copy the page reads and writes.
  Postgres  the archive -- every entry mirrored to a database that
            outlives the app, can be dumped, and can be read by
            something other than the code that wrote it.

The mirror is best-effort by design: if the archive is down, the entry is
still saved locally and marked unmirrored, and the next write catches it
up. A backup that can take the primary down with it is not a backup.
"""
import json
import os
import time
from typing import Optional

from . import config, db, llm

ARCHIVE_DSN = os.getenv("ZEE_ARCHIVE_DSN", "").strip()

# The fields an entry carries. Kept in one place because the SQLite
# table, the Postgres mirror, the export and the drafting prompt must all
# agree -- and the way they stop agreeing is by being written out four
# times.
FIELDS = ("title", "happened_on", "category", "situation", "task",
          "action", "result", "evidence", "skills", "award_target",
          "status", "note")

CATEGORIES = ("accomplishment", "award", "promotion", "training",
              "feedback", "metric")
STATUSES = ("draft", "ready", "submitted", "won", "archived")


# --- drafting ----------------------------------------------------------------

DRAFT_SYSTEM = (
    "You turn something a person said about their work into ONE structured "
    "portfolio entry. Return STRICT JSON only -- no prose, no code fence -- "
    "with exactly these keys: title, happened_on, category, situation, task, "
    "action, result, evidence, skills.\n"
    "  title       a short specific name for what they did\n"
    "  happened_on YYYY-MM-DD if the text says when, otherwise \"\"\n"
    "  category    one of: accomplishment, award, promotion, training, "
    "feedback, metric\n"
    "  situation   the context they were working in\n"
    "  task        what they were responsible for\n"
    "  action      what THEY specifically did\n"
    "  result      what changed because of it, with any numbers they gave\n"
    "  evidence    what would prove this -- documents, names, systems, "
    "dates they mentioned\n"
    "  skills      comma-separated competencies this demonstrates\n"
    "USE ONLY WHAT THE TEXT SAYS. If the text does not support a field, "
    "return an empty string for it. Never invent a number, a date, a name, "
    "a job title or an outcome. An empty field is correct and useful; an "
    "invented one is a lie in a document that goes to an employer."
)


def draft_from_text(text: str) -> tuple[dict, str]:
    """One portfolio entry drafted from something she said.

    Returns (entry, model). Missing or unparseable JSON yields an entry
    with the raw text in `situation` and nothing invented around it --
    a bad draft she can edit beats a confident fabrication.
    """
    raw, model = llm.ask(DRAFT_SYSTEM, text[:12000], temperature=0.2)
    body = raw.strip()
    if body.startswith("```"):
        body = body.split("```")[1]
        body = body.split("\n", 1)[1] if "\n" in body else body
    try:
        start, end = body.index("{"), body.rindex("}") + 1
        data = json.loads(body[start:end])
    except Exception:  # noqa: BLE001
        db.log_event("warn", "portfolio",
                     "draft did not return JSON; kept the words instead")
        return ({"title": text.strip()[:70] or "Untitled",
                 "situation": text.strip(), "category": "accomplishment"},
                model)
    out = {k: str(data.get(k, "") or "").strip() for k in FIELDS if k in data}
    if out.get("category") not in CATEGORIES:
        out["category"] = "accomplishment"
    if not out.get("title"):
        out["title"] = text.strip()[:70] or "Untitled"
    return out, model


# --- the archive -------------------------------------------------------------

ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio (
    id            BIGINT PRIMARY KEY,
    ts            DOUBLE PRECISION NOT NULL,
    updated_at    DOUBLE PRECISION,
    username      TEXT DEFAULT '',
    title         TEXT DEFAULT '',
    happened_on   TEXT DEFAULT '',
    category      TEXT DEFAULT '',
    situation     TEXT DEFAULT '',
    task          TEXT DEFAULT '',
    action        TEXT DEFAULT '',
    result        TEXT DEFAULT '',
    evidence      TEXT DEFAULT '',
    skills        TEXT DEFAULT '',
    award_target  TEXT DEFAULT '',
    status        TEXT DEFAULT 'draft',
    note          TEXT DEFAULT '',
    source_kind   TEXT DEFAULT '',
    source_id     BIGINT,
    model         TEXT DEFAULT '',
    archived_at   DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_portfolio_ts ON portfolio(ts DESC);

-- The conversation, kept in the archive too, so the record explains
-- itself: an entry can be traced back to the words it came from.
CREATE TABLE IF NOT EXISTS exchanges (
    id            BIGINT PRIMARY KEY,
    ts            DOUBLE PRECISION NOT NULL,
    session       TEXT DEFAULT '',
    question      TEXT DEFAULT '',
    answer        TEXT DEFAULT '',
    model         TEXT DEFAULT '',
    growth        INTEGER DEFAULT 0,
    archived_at   DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS recordings (
    id            BIGINT PRIMARY KEY,
    ts            DOUBLE PRECISION NOT NULL,
    title         TEXT DEFAULT '',
    orig_name     TEXT DEFAULT '',
    transcript    TEXT DEFAULT '',
    note          TEXT DEFAULT '',
    growth        INTEGER DEFAULT 0,
    archived_at   DOUBLE PRECISION
);
"""


def _connect():
    """A connection to the archive, or None if it is not configured/up."""
    if not ARCHIVE_DSN:
        return None
    try:
        import psycopg
        return psycopg.connect(ARCHIVE_DSN, connect_timeout=6)
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "archive", f"not reachable: {e}")
        return None


def archive_ready() -> tuple[bool, str]:
    if not ARCHIVE_DSN:
        return False, "No archive configured (ZEE_ARCHIVE_DSN is empty)."
    c = _connect()
    if not c:
        return False, "The archive database is not answering."
    with c:
        with c.cursor() as cur:
            cur.execute(ARCHIVE_SCHEMA)
            cur.execute("SELECT count(*) FROM portfolio")
            n = cur.fetchone()[0]
        c.commit()
    return True, f"Archive holding {n} portfolio entr{'y' if n == 1 else 'ies'}"


def _upsert(cur, table: str, row: dict) -> None:
    cols = list(row)
    place = ", ".join(["%s"] * len(cols))
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "id")
    cur.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({place})"
        f" ON CONFLICT (id) DO UPDATE SET {sets}",
        [row[c] for c in cols])


def mirror(limit: int = 500) -> tuple[bool, str]:
    """Push everything not yet in the archive. Safe to run repeatedly --
    every write is an upsert keyed on the local id, so a re-run repairs
    rather than duplicates."""
    c = _connect()
    if not c:
        return False, ("The archive is not reachable. Nothing is lost -- "
                       "the working copy has it all and the next sync "
                       "catches up.")
    now = time.time()
    n = 0
    try:
        with c:
            with c.cursor() as cur:
                cur.execute(ARCHIVE_SCHEMA)
                for row in db.portfolio_list(limit=limit):
                    r = {k: row.get(k) for k in
                         ("id", "ts", "updated_at", "username", *FIELDS,
                          "source_kind", "source_id", "model")}
                    r["archived_at"] = now
                    _upsert(cur, "portfolio", r)
                    n += 1
                for row in db.qa_list(limit=limit):
                    _upsert(cur, "exchanges", {
                        "id": row["id"], "ts": row["ts"],
                        "session": row["session"], "question": row["question"],
                        "answer": row["answer"], "model": row["model"],
                        "growth": row.get("growth", 0), "archived_at": now})
                for row in db.rec_list(limit=limit):
                    _upsert(cur, "recordings", {
                        "id": row["id"], "ts": row["ts"],
                        "title": row["title"], "orig_name": row["orig_name"],
                        "transcript": row["transcript"], "note": row["note"],
                        "growth": row.get("growth", 0), "archived_at": now})
            c.commit()
        db.portfolio_mark_mirrored(now)
        return True, (f"{n} portfolio entr{'y' if n == 1 else 'ies'} mirrored, "
                      "with her log beside them")
    except Exception as e:  # noqa: BLE001
        db.log_event("error", "archive", f"mirror failed: {e}")
        return False, f"Archive write failed: {e}"


# --- where she is up to ------------------------------------------------------
#
#  The pieces for this were already in the table -- status, category,
#  award_target, dates -- and nothing was reading them together. That is
#  the whole gap a document container would NOT have filled: an editor
#  gives you somewhere to type, not an answer to "what is ready and not
#  sent."
#
#  One query, three surfaces: a panel in her portal, a tab in the sheet,
#  and a Hermes tool. Same numbers in all three, because they call this.

STALE_DAYS = 45


def progress() -> dict:
    """A read of the record: what exists, what is ready, what has gone quiet."""
    import time as _t
    rows = db.portfolio_list(limit=2000)
    by_status, by_category, targets = {}, {}, {}
    ready_unsent, stale, wins = [], [], []
    now = _t.time()
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_category[r["category"]] = by_category.get(r["category"], 0) + 1
        if r["award_target"]:
            targets.setdefault(r["award_target"], []).append(r["title"])
        # Ready and not sent is the actionable number. An entry that is
        # finished and sitting there is the single most recoverable kind
        # of lost opportunity in this whole system.
        if r["status"] == "ready":
            ready_unsent.append(r)
        if r["status"] == "won":
            wins.append(r)
        touched = r.get("updated_at") or r["ts"]
        if r["status"] in ("draft", "ready") and (now - touched) > STALE_DAYS * 86400:
            stale.append(r)
    exchanges = len(db.qa_list(limit=5000))
    recordings = db.rec_list(limit=5000)
    growth = [r for r in recordings if r.get("growth")]
    return {
        "total": len(rows),
        "by_status": by_status,
        "by_category": by_category,
        "targets": targets,
        "ready_unsent": ready_unsent,
        "stale": stale,
        "wins": wins,
        "exchanges": exchanges,
        "recordings": len(recordings),
        "growth_moments": len(growth),
        "stale_days": STALE_DAYS,
    }


def progress_lines() -> list:
    """The same read, as sentences -- for the sheet, for Hermes, and for
    anyone who wants it read aloud rather than looked at."""
    p = progress()
    out = [f"{p['total']} portfolio entries."]
    if p["by_status"]:
        out.append("By status: " + ", ".join(
            f"{n} {s}" for s, n in sorted(p["by_status"].items(),
                                          key=lambda kv: -kv[1])) + ".")
    if p["ready_unsent"]:
        out.append(f"{len(p['ready_unsent'])} finished and NOT submitted: "
                   + "; ".join(e["title"] for e in p["ready_unsent"][:6]) + ".")
    if p["stale"]:
        out.append(f"{len(p['stale'])} untouched for over {p['stale_days']} "
                   "days: " + "; ".join(e["title"] for e in p["stale"][:6]) + ".")
    if p["wins"]:
        out.append(f"{len(p['wins'])} won: "
                   + "; ".join(e["title"] for e in p["wins"][:6]) + ".")
    if p["targets"]:
        out.append("Aimed at: " + ", ".join(sorted(p["targets"])) + ".")
    out.append(f"{p['exchanges']} conversations kept, {p['recordings']} "
               f"recordings, {p['growth_moments']} marked as growth.")
    if not p["total"]:
        out.append("Nothing in the portfolio yet -- talk to it and entries "
                   "get drafted from what you say.")
    return out


def growth_series(months: int = 24) -> dict:
    """Cumulative entries by month -- what her record looks like growing.

    CUMULATIVE, NOT PER-MONTH. Per-month is jagged and reads as failure in
    every quiet month; a record only goes up, and the line should say so.

    Dated on `happened_on` where she gave one, falling back to when the
    entry was created -- because the graph is about when the WORK happened,
    not when she got round to writing it down.
    """
    import time as _t
    from datetime import date as _d

    rows = db.portfolio_list(limit=2000)
    today = _d.today()
    # The window, oldest first: (year, month) pairs.
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()

    counts = {k: 0 for k in keys}
    for r in rows:
        when = (r.get("happened_on") or "").strip()
        key = None
        if len(when) >= 7 and when[:4].isdigit() and when[5:7].isdigit():
            key = (int(when[:4]), int(when[5:7]))
        else:
            ts = r.get("ts") or 0
            if ts:
                d = _d.fromtimestamp(ts)
                key = (d.year, d.month)
        if key in counts:
            counts[key] += 1
        elif key and key < keys[0]:
            # Older than the window: it still counts toward the total, so
            # the line does not pretend her earlier work never happened.
            counts[keys[0]] += 1

    running, series = 0, []
    for k in keys:
        running += counts[k]
        series.append({"year": k[0], "month": k[1], "total": running,
                       "added": counts[k]})
    return {"series": series, "total": running,
            "months": months, "any": running > 0}


# --- the four numbers on the portfolio page ---------------------------------

def stat_counts() -> dict:
    """Counts for the stat row. Four facts, no score.

    Jason asked for the count-up animation "for the numbers" on this page,
    and the page had none -- "Where things stand" is prose, and the only
    bare figure was `unmirrored`, which only appears when something has
    FAILED to archive. Animating that would count up only when something is
    wrong.

    Each of these changes what she does next:
      entries       how much is in the record at all
      quantified    entries carrying a real figure -- the one that decides
                    packages, because a board reads numbers and an entry
                    without one is a story
      archived      how many reached Paperless, so "working copy only" is a
                    count rather than a status word
      asking        open [NEEDED:] markers -- the work left, in one number

    Over the WHOLE record rather than the current filter, so the numbers do
    not quietly change meaning when she picks a category.
    """
    import re as _re
    rows = db.portfolio_list(limit=2000)
    num = _re.compile(r"\d")
    need = _re.compile(r"\[(NEEDED|FILL IN)", _re.I)

    quantified = asking = 0
    for r in rows:
        blob = " ".join(str(r.get(f) or "") for f in
                        ("situation", "task", "action", "result", "evidence"))
        # A number anywhere in the substance of the entry. Deliberately
        # generous: a date is a number too, and an entry with a date is
        # further along than one with nothing.
        if num.search(" ".join(str(r.get(f) or "") for f in ("result", "action"))):
            quantified += 1
        asking += len(need.findall(blob))

    return {
        "stat_entries": len(rows),
        "stat_quantified": quantified,
        "stat_archived": max(0, len(rows) - db.portfolio_unmirrored()),
        "stat_asking": asking,
    }


def normalise_when(raw: str) -> str:
    """Whatever the model said about when, as YYYY-MM-DD or "".

    THE COLUMN THE RECORD SORTS BY HAS TO BE A DATE. The prompt asks for
    YYYY-MM-DD and the model reasonably answers things like
    "17 August 2023 to 15 July 2026" -- true, useful to read, and unusable
    to sort. Stored as-is it fell through every reader to the row's created
    timestamp, so an award earned in 2023 appeared in the record as 2026.

    A RANGE RESOLVES TO ITS START. An award covering 2023 to 2026 belongs at
    the point the work began; filing it at the end would put three years of
    effort in the month the certificate was printed.

    Returns "" when there is genuinely nothing to parse. Empty and honest
    beats today's date wearing a disguise.
    """
    import datetime as _dt
    import re as _re

    raw = (raw or "").strip()
    if not raw:
        return ""

    # Already correct -- the common case once the model gets it right.
    m = _re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw)
    if m:
        return raw
    m = _re.match(r"^(\d{4})-(\d{2})$", raw)
    if m:
        return f"{raw}-01"
    if _re.match(r"^\d{4}$", raw):
        return f"{raw}-01-01"

    months = {mn: i for i, mn in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"], 1)}
    found = []
    for pat, kind in (
        (r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", "dmy"),
        (r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", "mdy"),
        (r"\b(\d{4})-(\d{2})-(\d{2})\b", "iso"),
    ):
        for mm in _re.finditer(pat, raw):
            try:
                if kind == "dmy":
                    d, mo, y = int(mm.group(1)), months[mm.group(2).lower()[:9]], int(mm.group(3))
                elif kind == "mdy":
                    mo, d, y = months[mm.group(1).lower()[:9]], int(mm.group(2)), int(mm.group(3))
                else:
                    y, mo, d = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
                if 1960 <= y <= _dt.date.today().year + 1:
                    found.append(_dt.date(y, mo, d))
            except (ValueError, KeyError):
                continue
    if found:
        # The EARLIEST, which is the start of a range -- see the note above.
        return min(found).isoformat()

    # A bare "August 2023" with no day.
    mm = _re.search(r"\b([A-Za-z]{3,9})\s+(\d{4})\b", raw)
    if mm and mm.group(1).lower()[:9] in months:
        return f"{int(mm.group(2)):04d}-{months[mm.group(1).lower()[:9]]:02d}-01"

    return ""
