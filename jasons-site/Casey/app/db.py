"""SQLite storage: users, login throttling, and the job queue."""
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Optional

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL DEFAULT '',
    pw_salt       TEXT NOT NULL,
    pw_hash       TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    created_at    REAL NOT NULL,
    must_change   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    username      TEXT NOT NULL,
    mode          TEXT NOT NULL,          -- log | award | interview
    award_target  TEXT NOT NULL DEFAULT '',
    orig_name     TEXT NOT NULL,
    stored_path   TEXT NOT NULL DEFAULT '',
    kind          TEXT NOT NULL,          -- audio | text | document
    note          TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,          -- queued|waking|transcribing|drafting|done|error|cancelled
    progress      TEXT NOT NULL DEFAULT '',
    transcript    TEXT NOT NULL DEFAULT '',
    draft         TEXT NOT NULL DEFAULT '',
    followups     TEXT NOT NULL DEFAULT '[]',
    answers       TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL DEFAULT '',
    parent_id     INTEGER,
    model_used    TEXT NOT NULL DEFAULT '',
    kb_version    TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);

-- EVERY QUESTION AND ANSWER (2026-09-03). The whole point of talking to
-- it is that the talking is kept: what she asked, what came back, which
-- model said it, and whether it was spoken. `session` groups one sitting
-- so a conversation can be read back in order rather than as a pile.
CREATE TABLE IF NOT EXISTS qa (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    session       TEXT NOT NULL DEFAULT '',
    username      TEXT NOT NULL DEFAULT '',
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    asked_by      TEXT NOT NULL DEFAULT 'voice',   -- voice | typed
    audio_path    TEXT NOT NULL DEFAULT '',
    spoken_path   TEXT NOT NULL DEFAULT '',
    exported_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_qa_ts ON qa(ts DESC);
CREATE INDEX IF NOT EXISTS idx_qa_session ON qa(session, ts);

-- HER TAPE (2026-09-03). Every piece of audio, kept and playable, with
-- whatever the speech service made of it. `source` says how it arrived:
--   asked     a spoken question from the talking page
--   uploaded  a recording she added herself
-- Transcription runs in the background, so `status` is what the page
-- watches. A failed transcript never loses the audio -- the recording is
-- the artefact, the text is a convenience over it.
CREATE TABLE IF NOT EXISTS recordings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    username      TEXT NOT NULL DEFAULT '',
    orig_name     TEXT NOT NULL DEFAULT '',
    stored_path   TEXT NOT NULL,
    bytes         INTEGER NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'uploaded',
    title         TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    transcript    TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'queued',  -- queued|working|done|error
    error         TEXT NOT NULL DEFAULT '',
    transcribed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_rec_ts ON recordings(ts DESC);
CREATE INDEX IF NOT EXISTS idx_rec_status ON recordings(status);

-- THE PORTFOLIO (2026-09-03). Not a transcript -- a record of DOING,
-- shaped the way a promotion case or an award nomination asks for it:
-- situation, task, action, result, evidence. The same entry then serves
-- both without being rewritten.
--
-- `mirrored_at` is how the archive knows what it has not seen. The
-- working copy is here; the durable copy is Postgres.
CREATE TABLE IF NOT EXISTS portfolio (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    updated_at    REAL,
    username      TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL DEFAULT '',
    happened_on   TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT 'accomplishment',
    situation     TEXT NOT NULL DEFAULT '',
    task          TEXT NOT NULL DEFAULT '',
    action        TEXT NOT NULL DEFAULT '',
    result        TEXT NOT NULL DEFAULT '',
    evidence      TEXT NOT NULL DEFAULT '',
    skills        TEXT NOT NULL DEFAULT '',
    award_target  TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'draft',
    note          TEXT NOT NULL DEFAULT '',
    source_kind   TEXT NOT NULL DEFAULT '',
    source_id     INTEGER,
    model         TEXT NOT NULL DEFAULT '',
    mirrored_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_portfolio_ts ON portfolio(ts DESC);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    level         TEXT NOT NULL,
    source        TEXT NOT NULL,
    message       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

-- What the background pass turned up, and whether she has seen it.
--
-- SEPARATE FROM events ON PURPOSE. events is a technical log -- it is
-- pruned every 45 days and nobody reads it. A finding is addressed TO
-- her, has to survive until she has actually seen it, and carries a
-- state (new -> seen -> acted on or dismissed) that a log line does not.
--
-- fingerprint is what stops the same finding arriving every few hours.
-- It is a hash of what the finding IS, not when it was made, so a scan
-- that reaches the same conclusion twice updates one row instead of
-- stacking up duplicates she then has to dismiss one at a time.
CREATE TABLE IF NOT EXISTS findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    updated_at    REAL,
    fingerprint   TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL DEFAULT '',
    urgency       TEXT NOT NULL DEFAULT 'normal',
    title         TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL DEFAULT '',
    action        TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT '',
    entry_id      INTEGER,
    seen_at       REAL,
    dismissed_at  REAL,
    times_seen    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_findings_ts ON findings(ts DESC);
CREATE INDEX IF NOT EXISTS idx_findings_new ON findings(seen_at, dismissed_at);

-- Her progress against one award. See target_set() for why there is only
-- one of these no matter which front door she came in through.
CREATE TABLE IF NOT EXISTS targets (
    award_id      TEXT PRIMARY KEY,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    updated_via   TEXT NOT NULL DEFAULT '',
    updated_by    TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'considering',
    notes         TEXT NOT NULL DEFAULT '',
    next_action   TEXT NOT NULL DEFAULT '',
    owner_note    TEXT NOT NULL DEFAULT '',
    deadline_note TEXT NOT NULL DEFAULT ''
);

-- Every change, so "what moved since I last looked" has an answer that
-- does not depend on anyone having remembered to write it down.
CREATE TABLE IF NOT EXISTS target_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    award_id      TEXT NOT NULL,
    field         TEXT NOT NULL DEFAULT '',
    old_value     TEXT NOT NULL DEFAULT '',
    new_value     TEXT NOT NULL DEFAULT '',
    via           TEXT NOT NULL DEFAULT '',
    username      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tevents_ts ON target_events(ts DESC);

-- The jacket timeline. See milestone_add() for why this is its own table
-- and why `precision` travels beside the date.
CREATE TABLE IF NOT EXISTS milestones (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    username   TEXT NOT NULL DEFAULT '',
    when_iso   TEXT NOT NULL,
    precision  TEXT NOT NULL DEFAULT 'day',
    title      TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'other',
    tier       TEXT NOT NULL DEFAULT 'minor',
    detail     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_milestones_when ON milestones(when_iso ASC);

-- Somewhere to say the hard part. Walled off from the record on purpose --
-- see vent.py. Nothing here is read for accomplishments or exported.
CREATE TABLE IF NOT EXISTS vents (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    username  TEXT NOT NULL DEFAULT '',
    text      TEXT NOT NULL DEFAULT '',
    mood      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vents_ts ON vents(ts DESC);
"""


def _conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        _local.conn = c
    return c


@contextmanager
def tx():
    c = _conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def _add_column(c, table: str, col: str, decl: str) -> None:
    """Add a column if it is not already there.

    CREATE TABLE IF NOT EXISTS does nothing to a table that already
    exists, so a new field on a live database needs this or it silently
    never arrives. Additive only -- nothing here drops or rewrites.
    """
    have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    if col not in have:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
        # GROWTH (2026-09-03). A mark she puts on the moments worth
        # returning to -- something learned, something done, a step
        # forward. It is what makes the log a record of progress rather
        # than a pile of transcript, and it is what Hermes surfaces.
        _add_column(c, "recordings", "growth", "INTEGER NOT NULL DEFAULT 0")
        _add_column(c, "qa", "growth", "INTEGER NOT NULL DEFAULT 0")
        # Follow-up questions live on the ENTRY they are about. Additive,
        # so an existing database gets the column without losing anything.
        _add_column(c, "portfolio", "followups", "TEXT NOT NULL DEFAULT '[]'")
        # A milestone can be a SPAN, not just a point. Her assignment ran
        # Aug 2023 to Jul 2026 and her Master's is still running -- and
        # they overlap, because she does not do one thing at a time.
        _add_column(c, "milestones", "until_iso", "TEXT NOT NULL DEFAULT ''")
        _add_column(c, "milestones", "until_precision", "TEXT NOT NULL DEFAULT ''")


# --- password hashing (stdlib scrypt, no external deps) ----------------------

def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32
    )
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected: str) -> bool:
    try:
        _, actual = hash_password(password, salt)
    except Exception:
        return False
    return secrets.compare_digest(actual, expected)


# --- users -------------------------------------------------------------------

def create_user(username: str, password: str, display_name: str = "", role: str = "user",
                must_change: bool = False) -> None:
    salt, h = hash_password(password)
    with tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO users(username, display_name, pw_salt, pw_hash, role, created_at, must_change)"
            " VALUES (?,?,?,?,?,?,?)",
            (username.lower().strip(), display_name or username, salt, h, role, time.time(),
             1 if must_change else 0),
        )


def set_password(username: str, password: str) -> None:
    salt, h = hash_password(password)
    with tx() as c:
        c.execute("UPDATE users SET pw_salt=?, pw_hash=?, must_change=0 WHERE username=?",
                  (salt, h, username.lower().strip()))


def get_user(username: str) -> Optional[sqlite3.Row]:
    cur = _conn().execute("SELECT * FROM users WHERE username=?", (username.lower().strip(),))
    return cur.fetchone()


def user_for_email(email: str) -> Optional[sqlite3.Row]:
    """The account for a signed-in address, made on first sight. Same
    pattern as Mom/app/core.py's user_for_email() -- see its own docstring
    for the long version. Short version: the address IS the username, role
    is re-derived from config.OWNERS on every call so promoting or demoting
    somebody is a line in .env and a restart, and the password columns hold
    random, unusable bytes because nothing ever checks them any more -- this
    app has no login of its own, see main.py's current_user()."""
    username = (email or "").strip().lower()
    if not username:
        return None
    role = "admin" if username in config.OWNERS else "user"

    row = get_user(username)
    if row is not None:
        if row["role"] != role:
            with tx() as c:
                c.execute("UPDATE users SET role=? WHERE username=?", (role, username))
            row = get_user(username)
        return row

    salt, h = hash_password(secrets.token_urlsafe(32))
    with tx() as c:
        c.execute(
            "INSERT INTO users(username, display_name, pw_salt, pw_hash, role, "
            "created_at, must_change) VALUES (?,?,?,?,?,?,0) "
            "ON CONFLICT(username) DO NOTHING",
            (username, username.split("@")[0], salt, h, role, time.time()))
    return get_user(username)


def list_users() -> list[sqlite3.Row]:
    return _conn().execute("SELECT * FROM users ORDER BY created_at").fetchall()


def user_count() -> int:
    return _conn().execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


# --- jobs --------------------------------------------------------------------

def create_job(username: str, mode: str, orig_name: str, stored_path: str, kind: str,
               note: str = "", award_target: str = "", parent_id: Optional[int] = None) -> int:
    now = time.time()
    with tx() as c:
        cur = c.execute(
            "INSERT INTO jobs(created_at, updated_at, username, mode, award_target, orig_name,"
            " stored_path, kind, note, status, parent_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,'queued',?)",
            (now, now, username, mode, award_target, orig_name, stored_path, kind, note, parent_id),
        )
        return int(cur.lastrowid)


def update_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with tx() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def get_job(job_id: int) -> Optional[sqlite3.Row]:
    return _conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def list_jobs(username: Optional[str] = None, limit: int = 100) -> list[sqlite3.Row]:
    if username:
        return _conn().execute(
            "SELECT * FROM jobs WHERE username=? ORDER BY created_at DESC LIMIT ?",
            (username, limit)).fetchall()
    return _conn().execute(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()


def next_queued_job() -> Optional[sqlite3.Row]:
    return _conn().execute(
        "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()


def active_job_count() -> int:
    return _conn().execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status IN "
        "('queued','waking','transcribing','drafting')").fetchone()["n"]


def last_activity_ts() -> float:
    row = _conn().execute("SELECT MAX(updated_at) AS t FROM jobs").fetchone()
    return float(row["t"] or 0.0)


def requeue_stuck_jobs() -> int:
    """On startup, put any half-finished job back in the queue."""
    with tx() as c:
        cur = c.execute(
            "UPDATE jobs SET status='queued', progress='Requeued after portal restart'"
            " WHERE status IN ('waking','transcribing','drafting')")
        return cur.rowcount


# --- events ------------------------------------------------------------------

def log_event(level: str, source: str, message: str) -> None:
    try:
        with tx() as c:
            c.execute("INSERT INTO events(ts, level, source, message) VALUES (?,?,?,?)",
                      (time.time(), level, source, message[:4000]))
    except Exception:
        pass


def recent_events(limit: int = 200) -> list[sqlite3.Row]:
    return _conn().execute(
        "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def prune_events(keep_days: int = 30) -> None:
    cutoff = time.time() - keep_days * 86400
    with tx() as c:
        c.execute("DELETE FROM events WHERE ts < ?", (cutoff,))


def jload(s: str, default: Any) -> Any:
    try:
        return json.loads(s) if s else default
    except Exception:
        return default

# --- the question-and-answer log ---------------------------------------------

def qa_add(session: str, username: str, question: str, answer: str,
           model: str, asked_by: str = "voice", audio_path: str = "",
           spoken_path: str = "") -> int:
    c = _conn()
    cur = c.execute(
        "INSERT INTO qa (ts, session, username, question, answer, model,"
        " asked_by, audio_path, spoken_path) VALUES (?,?,?,?,?,?,?,?,?)",
        (time.time(), session, username, question, answer, model,
         asked_by, audio_path, spoken_path))
    c.commit()
    return cur.lastrowid


def qa_list(limit: int = 500, session: str = "", since: float = 0.0) -> list[dict]:
    q = "SELECT * FROM qa WHERE ts >= ?"
    args: list = [since]
    if session:
        q += " AND session = ?"
        args.append(session)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in _conn().execute(q, args).fetchall()]


def qa_sessions(limit: int = 60) -> list[dict]:
    """One row per sitting: when it started, how many exchanges."""
    rows = _conn().execute(
        "SELECT session, MIN(ts) AS started, MAX(ts) AS ended,"
        " COUNT(*) AS turns FROM qa WHERE session <> ''"
        " GROUP BY session ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def qa_mark_exported(ids: list[int]) -> None:
    if not ids:
        return
    c = _conn()
    c.executemany("UPDATE qa SET exported_at = ? WHERE id = ?",
                  [(time.time(), i) for i in ids])
    c.commit()

# --- the recordings library --------------------------------------------------

def rec_add(username: str, orig_name: str, stored_path: str, nbytes: int,
            source: str = "uploaded", title: str = "", note: str = "",
            transcript: str = "", status: str = "queued") -> int:
    c = _conn()
    cur = c.execute(
        "INSERT INTO recordings (ts, username, orig_name, stored_path, bytes,"
        " source, title, note, transcript, status, transcribed_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), username, orig_name, stored_path, nbytes, source,
         title, note, transcript, status,
         time.time() if transcript else None))
    c.commit()
    return cur.lastrowid


def rec_get(rec_id: int) -> Optional[dict]:
    r = _conn().execute("SELECT * FROM recordings WHERE id = ?",
                        (rec_id,)).fetchone()
    return dict(r) if r else None


def rec_list(limit: int = 200, q: str = "") -> list[dict]:
    sql = "SELECT * FROM recordings"
    args: list = []
    if q:
        sql += (" WHERE title LIKE ? OR note LIKE ? OR transcript LIKE ?"
                " OR orig_name LIKE ?")
        args += [f"%{q}%"] * 4
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in _conn().execute(sql, args).fetchall()]


def rec_next_queued() -> Optional[dict]:
    r = _conn().execute(
        "SELECT * FROM recordings WHERE status = 'queued' ORDER BY ts LIMIT 1"
    ).fetchone()
    return dict(r) if r else None


def rec_update(rec_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    c = _conn()
    c.execute(f"UPDATE recordings SET {cols} WHERE id = ?",
              [*fields.values(), rec_id])
    c.commit()


def rec_delete(rec_id: int) -> Optional[str]:
    """Forget a recording. Returns its path so the caller can remove the
    file -- this does NOT delete from disk, deliberately, so a mistaken
    click costs a row and not the tape."""
    row = rec_get(rec_id)
    if not row:
        return None
    c = _conn()
    c.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
    c.commit()
    return row["stored_path"]


def rec_requeue_stuck() -> int:
    """Anything caught mid-transcription by a restart goes back in line."""
    c = _conn()
    n = c.execute("UPDATE recordings SET status = 'queued'"
                  " WHERE status = 'working'").rowcount
    c.commit()
    return n

def set_growth(kind: str, row_id: int, on: bool) -> None:
    """Mark (or unmark) one recording or exchange as a growth moment."""
    table = {"recording": "recordings", "qa": "qa"}.get(kind)
    if not table:
        raise ValueError("kind must be 'recording' or 'qa'")
    c = _conn()
    c.execute(f"UPDATE {table} SET growth = ? WHERE id = ?",
              (1 if on else 0, row_id))
    c.commit()


def search_notes(q: str, limit: int = 40, growth_only: bool = False) -> list[dict]:
    """One search across both halves of what she has said.

    Recordings and exchanges are different tables but the same corpus as
    far as anybody looking for something is concerned, so this returns
    them interleaved and newest first, each carrying what it is.
    """
    like = f"%{q}%"
    out: list[dict] = []
    rw = "AND growth = 1" if growth_only else ""
    if q:
        rows = _conn().execute(
            f"SELECT id, ts, title, orig_name, transcript, note, growth"
            f" FROM recordings WHERE (transcript LIKE ? OR title LIKE ?"
            f" OR note LIKE ? OR orig_name LIKE ?) {rw}"
            f" ORDER BY ts DESC LIMIT ?", (like, like, like, like, limit)
        ).fetchall()
    else:
        rows = _conn().execute(
            f"SELECT id, ts, title, orig_name, transcript, note, growth"
            f" FROM recordings WHERE 1=1 {rw} ORDER BY ts DESC LIMIT ?",
            (limit,)).fetchall()
    for r in rows:
        d = dict(r)
        out.append({"kind": "recording", "id": d["id"], "ts": d["ts"],
                    "title": d["title"] or d["orig_name"],
                    "text": d["transcript"], "note": d["note"],
                    "growth": bool(d["growth"])})
    qw = "AND growth = 1" if growth_only else ""
    if q:
        rows = _conn().execute(
            f"SELECT id, ts, question, answer, model, growth FROM qa"
            f" WHERE (question LIKE ? OR answer LIKE ?) {qw}"
            f" ORDER BY ts DESC LIMIT ?", (like, like, limit)).fetchall()
    else:
        rows = _conn().execute(
            f"SELECT id, ts, question, answer, model, growth FROM qa"
            f" WHERE 1=1 {qw} ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    for r in rows:
        d = dict(r)
        out.append({"kind": "exchange", "id": d["id"], "ts": d["ts"],
                    "title": d["question"][:90], "text": d["answer"],
                    "note": d["model"], "growth": bool(d["growth"])})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:limit]

# --- the portfolio -----------------------------------------------------------

PORTFOLIO_FIELDS = ("title", "happened_on", "category", "situation", "task",
                    "action", "result", "evidence", "skills", "award_target",
                    "status", "note")


def portfolio_add(username: str, entry: dict, source_kind: str = "",
                  source_id: Optional[int] = None, model: str = "") -> int:
    # THE DATE THE RECORD SORTS BY MUST BE A DATE. The model answers this
    # field in prose often enough -- "17 August 2023 to 15 July 2026" -- and
    # stored raw it fell through every reader to the row's created timestamp,
    # so an award earned in 2023 showed up in the record as 2026 with nothing
    # reporting a problem. Normalised here, at the one door every entry comes
    # through, rather than leniently in each reader where one would forget.
    from . import portfolio as _pf
    if isinstance(entry, dict) and entry.get("happened_on"):
        entry = dict(entry)
        entry["happened_on"] = _pf.normalise_when(entry["happened_on"])
    vals = {k: str(entry.get(k, "") or "") for k in PORTFOLIO_FIELDS}
    cols = ["ts", "updated_at", "username", *PORTFOLIO_FIELDS,
            "source_kind", "source_id", "model"]
    now = time.time()
    args = [now, now, username, *[vals[k] for k in PORTFOLIO_FIELDS],
            source_kind, source_id, model]
    c = _conn()
    cur = c.execute(
        f"INSERT INTO portfolio ({', '.join(cols)})"
        f" VALUES ({', '.join('?' * len(cols))})", args)
    c.commit()
    return cur.lastrowid


def portfolio_list(limit: int = 300, status: str = "",
                   category: str = "") -> list[dict]:
    sql, args = "SELECT * FROM portfolio WHERE 1=1", []
    if status:
        sql += " AND status = ?"
        args.append(status)
    if category:
        sql += " AND category = ?"
        args.append(category)
    sql += " ORDER BY (happened_on = ''), happened_on DESC, ts DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in _conn().execute(sql, args).fetchall()]


def portfolio_get(entry_id: int) -> Optional[dict]:
    r = _conn().execute("SELECT * FROM portfolio WHERE id = ?",
                        (entry_id,)).fetchone()
    return dict(r) if r else None


def portfolio_update(entry_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items()
              if k in PORTFOLIO_FIELDS or k == "mirrored_at"}
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    c = _conn()
    c.execute(f"UPDATE portfolio SET {cols} WHERE id = ?",
              [*fields.values(), entry_id])
    c.commit()


def portfolio_delete(entry_id: int) -> None:
    c = _conn()
    c.execute("DELETE FROM portfolio WHERE id = ?", (entry_id,))
    c.commit()


def portfolio_mark_mirrored(when: float) -> None:
    c = _conn()
    c.execute("UPDATE portfolio SET mirrored_at = ?"
              " WHERE mirrored_at IS NULL OR mirrored_at < updated_at",
              (when,))
    c.commit()


def portfolio_unmirrored() -> int:
    return _conn().execute(
        "SELECT COUNT(*) FROM portfolio"
        " WHERE mirrored_at IS NULL OR mirrored_at < updated_at"
    ).fetchone()[0]


# --- findings: what the background pass turned up ----------------------------
#
#  UPSERT BY FINGERPRINT, NEVER PLAIN INSERT. The scan runs again every
#  time her record changes, and most of what it finds the second time is
#  what it found the first time. Inserting each pass would bury the one
#  genuinely new thing under twenty copies of last week's, which is the
#  fastest way to teach someone to ignore a notification panel entirely.
#
#  A repeat does NOT clear seen_at -- something she has already read does
#  not become new again just because the scan ran. It only bumps
#  times_seen, which is how "this has been true for six weeks and you
#  have not acted on it" becomes visible without nagging.

def finding_upsert(fingerprint: str, kind: str, title: str, body: str,
                   action: str = "", urgency: str = "normal",
                   source: str = "", entry_id: int | None = None) -> tuple[int, bool]:
    """Returns (id, is_new). is_new is False for something already known."""
    now = time.time()
    c = _conn()
    row = c.execute("SELECT id, seen_at FROM findings WHERE fingerprint = ?",
                    (fingerprint,)).fetchone()
    if row:
        c.execute("UPDATE findings SET updated_at = ?, times_seen = times_seen + 1,"
                  " title = ?, body = ?, action = ?, urgency = ?"
                  " WHERE id = ?",
                  (now, title, body, action, urgency, row["id"]))
        c.commit()
        return row["id"], False
    cur = c.execute(
        "INSERT INTO findings (ts, updated_at, fingerprint, kind, urgency,"
        " title, body, action, source, entry_id, times_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,1)",
        (now, now, fingerprint, kind, urgency, title, body, action,
         source, entry_id))
    c.commit()
    return cur.lastrowid, True


def findings_list(limit: int = 100, unseen_only: bool = False,
                  include_dismissed: bool = False) -> list[dict]:
    sql = "SELECT * FROM findings WHERE 1=1"
    if unseen_only:
        sql += " AND seen_at IS NULL"
    if not include_dismissed:
        sql += " AND dismissed_at IS NULL"
    # Urgency first, then newest. A deadline three weeks out outranks a
    # suggestion made this morning.
    sql += (" ORDER BY CASE urgency WHEN 'now' THEN 0 WHEN 'soon' THEN 1"
            " ELSE 2 END, ts DESC LIMIT ?")
    return [dict(r) for r in _conn().execute(sql, (limit,)).fetchall()]


def findings_unseen_count() -> int:
    return _conn().execute(
        "SELECT COUNT(*) FROM findings"
        " WHERE seen_at IS NULL AND dismissed_at IS NULL").fetchone()[0]


def findings_mark_seen(ids: list[int] | None = None) -> int:
    """Mark specific findings seen, or all of them if ids is None."""
    now = time.time()
    c = _conn()
    if ids:
        q = ",".join("?" * len(ids))
        cur = c.execute(f"UPDATE findings SET seen_at = ? WHERE seen_at IS NULL"
                        f" AND id IN ({q})", [now, *ids])
    else:
        cur = c.execute("UPDATE findings SET seen_at = ? WHERE seen_at IS NULL",
                        (now,))
    c.commit()
    return cur.rowcount


def finding_dismiss(finding_id: int) -> None:
    c = _conn()
    now = time.time()
    c.execute("UPDATE findings SET dismissed_at = ?,"
              " seen_at = COALESCE(seen_at, ?) WHERE id = ?",
              (now, now, finding_id))
    c.commit()


def record_changed_at() -> float:
    """The last time anything she owns actually changed.

    The research pass is triggered by this rather than by a timer: a scan
    that runs when nothing has happened costs a model call and can only
    reach the conclusion it reached last time.
    """
    c = _conn()
    best = 0.0
    for sql in ("SELECT MAX(COALESCE(updated_at, ts)) FROM portfolio",
                "SELECT MAX(ts) FROM qa",
                "SELECT MAX(ts) FROM recordings"):
        try:
            v = c.execute(sql).fetchone()[0]
            if v:
                best = max(best, float(v))
        except Exception:  # noqa: BLE001 -- a table that is not there yet
            pass
    return best


# --- one row per award she is working, shared by every session ---------------
#
#  THE POINT OF THIS TABLE IS THAT THERE IS ONLY ONE OF IT.
#
#  Jason, 2026-09-06: "allowing all changes that she makes to her career
#  shared between all the sessions ... this will allow progress to be noted
#  through all sessions."
#
#  She can work in the portal, in Telegram, or in ChatGPT through the
#  action API. Those are three front doors, not three records. Whichever
#  one she used last, the next one opens on the same state -- so the
#  question "where did I write that down" stops having an answer, because
#  there is only one place it could be.
#
#  updated_via is kept for exactly one reason: when a number looks wrong,
#  the first useful question is which door it came in through.

TARGET_FIELDS = ("status", "notes", "next_action", "owner_note", "deadline_note")


def target_get(award_id: str) -> dict:
    r = _conn().execute("SELECT * FROM targets WHERE award_id = ?",
                        (award_id,)).fetchone()
    return dict(r) if r else {}


def target_all() -> dict:
    return {r["award_id"]: dict(r)
            for r in _conn().execute("SELECT * FROM targets").fetchall()}


def target_set(award_id: str, via: str = "portal", username: str = "",
               **fields) -> dict:
    """Upsert one award's state, and log what changed.

    ONLY FIELDS ACTUALLY PASSED ARE TOUCHED. A caller that knows the
    status and nothing else must not blank her notes -- which is exactly
    what a naive full-row upsert does, and exactly the kind of loss that
    is noticed weeks later.
    """
    now = time.time()
    c = _conn()
    before = target_get(award_id)
    keep = {k: v for k, v in fields.items()
            if k in TARGET_FIELDS and v is not None}
    if not before:
        cols = ["award_id", "created_at", "updated_at", "updated_via",
                "updated_by", *keep.keys()]
        c.execute(
            f"INSERT INTO targets ({', '.join(cols)})"
            f" VALUES ({', '.join('?' * len(cols))})",
            [award_id, now, now, via, username, *keep.values()])
    elif keep:
        sets = ", ".join(f"{k} = ?" for k in keep)
        c.execute(
            f"UPDATE targets SET {sets}, updated_at = ?, updated_via = ?,"
            f" updated_by = ? WHERE award_id = ?",
            [*keep.values(), now, via, username, award_id])
    c.commit()
    for k, v in keep.items():
        old = (before or {}).get(k) or ""
        if str(old) != str(v):
            c.execute(
                "INSERT INTO target_events (ts, award_id, field, old_value,"
                " new_value, via, username) VALUES (?,?,?,?,?,?,?)",
                (now, award_id, k, str(old)[:2000], str(v)[:2000], via, username))
    c.commit()
    return target_get(award_id)


def target_history(award_id: str = "", limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM target_events WHERE 1=1"
    args = []
    if award_id:
        sql += " AND award_id = ?"
        args.append(award_id)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in _conn().execute(sql, args).fetchall()]


# --- the jacket timeline -----------------------------------------------------
#
#  Its own table, not derived from the portfolio. The portfolio holds what
#  she DID; a jacket holds what HAPPENED TO her -- commissioned, promoted,
#  pinned, graduated. Deriving one from the other would either flood the
#  rail with quarterly bullets or lose the day she pinned on Major.
#
#  `precision` travels with the date because "2019" and "14 SEP 2019" are
#  both honest answers about a career, and demanding the day is how the
#  entry never gets made.

def milestone_add(username: str, when_iso: str, precision: str, title: str,
                  kind: str, tier: str, detail: str = "",
                  until_iso: str = "", until_precision: str = "") -> int:
    now = time.time()
    c = _conn()
    cur = c.execute(
        "INSERT INTO milestones (ts, username, when_iso, precision, title,"
        " kind, tier, detail, until_iso, until_precision)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now, username, when_iso, precision, title, kind, tier, detail,
         until_iso, until_precision))
    c.commit()
    return cur.lastrowid


def milestone_list() -> list[dict]:
    return [dict(r) for r in _conn().execute(
        "SELECT * FROM milestones ORDER BY when_iso ASC, id ASC").fetchall()]


def milestone_get(mid: int) -> dict:
    r = _conn().execute("SELECT * FROM milestones WHERE id = ?", (mid,)).fetchone()
    return dict(r) if r else {}


def milestone_update(mid: int, **fields) -> None:
    keep = {k: v for k, v in fields.items() if k in
            ("when_iso", "precision", "title", "kind", "tier", "detail",
             "until_iso", "until_precision")
            and v is not None}
    if not keep:
        return
    c = _conn()
    c.execute(f"UPDATE milestones SET {', '.join(f'{k} = ?' for k in keep)}"
              " WHERE id = ?", [*keep.values(), mid])
    c.commit()


def milestone_delete(mid: int) -> None:
    c = _conn()
    c.execute("DELETE FROM milestones WHERE id = ?", (mid,))
    c.commit()


# --- follow-up questions attached to one portfolio entry ---------------------
#
#  Stored on the entry rather than in their own table: they are meaningless
#  without it, they die with it, and a question with no entry behind it is
#  not something anyone would ever want to query for.

def entry_followups_get(entry_id: int) -> list:
    r = _conn().execute("SELECT followups FROM portfolio WHERE id = ?",
                        (entry_id,)).fetchone()
    if not r:
        return []
    try:
        return json.loads(r["followups"] or "[]")
    except Exception:  # noqa: BLE001
        return []


def entry_followups_set(entry_id: int, questions: list) -> None:
    c = _conn()
    c.execute("UPDATE portfolio SET followups = ?, updated_at = ? WHERE id = ?",
              (json.dumps(questions), time.time(), entry_id))
    c.commit()


# --- the vent: walled off from the record on purpose -------------------------
#
#  Its own table, deliberately NOT the portfolio. Nothing in here is read
#  for accomplishments, exported, or shown to a model that is drafting.
#  See vent.py for why that separation is what makes the rest of the
#  portal usable rather than exhausting to talk to.

def vent_add(username: str, text: str, mood: str = "") -> int:
    c = _conn()
    cur = c.execute(
        "INSERT INTO vents (ts, username, text, mood) VALUES (?,?,?,?)",
        (time.time(), username, text, mood))
    c.commit()
    return cur.lastrowid


def vent_list(username: str = "", limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM vents WHERE 1=1"
    args = []
    if username:
        sql += " AND username = ?"
        args.append(username)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in _conn().execute(sql, args).fetchall()]


def vent_delete(vent_id: int) -> None:
    c = _conn()
    c.execute("DELETE FROM vents WHERE id = ?", (vent_id,))
    c.commit()
