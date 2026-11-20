"""Career Portal — FastAPI app served behind Caddy on the Raspberry Pi."""
import json
import random
import re
import secrets
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (actions, archive, awards, chatgpt, config, db, desktop,
               deepreview, dictate, exports, followups, gaps, handoff,
               imports, llm, milestones, portfolio, render, research,
               roadmap, vent, workbook, working, worker)

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _unseen_findings() -> int:
    """The badge count, as a Jinja global rather than a context key.

    Every page renders the nav, so the alternative was adding the same
    line to six TemplateResponse dicts and remembering it on the seventh.
    It is an indexed COUNT on a small table; a page render can afford it.
    Failure returns 0 -- a missing badge is a small loss, a 500 on every
    page because the count could not be read is not.
    """
    try:
        return db.findings_unseen_count()
    except Exception:  # noqa: BLE001
        return 0


def _career_strip(limit: int = 40) -> list:
    """Her milestones as x-positions for the banner strip.

    A Jinja global for the same reason the badge is one: every page
    renders the banner, and the alternative was the same line in a dozen
    TemplateResponse dicts and forgetting it on the thirteenth.

    Positions are spread across the span of her career rather than evenly,
    so the strip says something true about pace -- a cluster of three in
    one year looks like a cluster.
    """
    try:
        rows = milestones.listing()
        if not rows:
            return []
        years = [int(r["year"]) for r in rows if str(r.get("year", "")).isdigit()]
        if not years:
            return []
        lo, hi = min(years), max(years)
        span = max(1, hi - lo)
        out = []
        for r in rows[:limit]:
            y = int(r["year"]) if str(r.get("year", "")).isdigit() else lo
            out.append({"x": round(((y - lo) / span) * 980, 1),
                        "tier": r.get("tier", "minor")})
        return out
    except Exception:  # noqa: BLE001
        return []


templates.env.globals["career_strip"] = _career_strip
templates.env.globals["unseen_findings"] = _unseen_findings

app = FastAPI(title=config.SITE_NAME, root_path=config.ROOT_PATH,
              docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


# --- helpers -----------------------------------------------------------------

def current_user(request: Request) -> Optional[dict]:
    """Whoever Caddy already signed in, as a row in our own users table.

    THIS APP HAS NO LOGIN OF ITS OWN, DELIBERATELY.
    ------------------------------------------------
    It used to: its own username and password, its own session cookie, its
    own login-throttling table. That meant a SECOND set of credentials on
    top of the one site-wide sign-in at /auth -- removing somebody from
    /admin/people closed every other door and left this account, and its
    password, sitting here untouched. The half you forget is always the
    removal.

    Now there is one door. Caddy's forward_auth asks the shared auth
    service "is this person allowed, and specifically at /casey?" (see
    rust/auth's app_for_uri() and common::people::Person::apps) before this
    process ever sees the request, and copies the address it verified into
    X-Auth-Email. If that header is here, the person is signed in and
    allowed at this door specifically; there is no second question worth
    asking.

    WHY TRUSTING A HEADER IS SAFE HERE
    -----------------------------------
    Same reasoning as /mama's current_user() (Mom/app/main.py): this
    container publishes no port and is reachable only via Caddy on the
    Docker network, and Caddy's own (appproxy) snippet strips any
    client-supplied X-Auth-Email before forward_auth sets the real one. A
    request that reaches this process without that header did not come the
    way it must, and the right answer to that is no, not a guess.
    """
    email = (request.headers.get("X-Auth-Email") or "").strip().lower()
    if not email:
        return None
    row = db.user_for_email(email)
    if not row:
        return None
    return {"username": row["username"], "display_name": row["display_name"],
            "role": row["role"], "is_admin": row["role"] == "admin"}


def require_user(request: Request) -> dict:
    u = current_user(request)
    if not u:
        # NOT a redirect to a login page -- there is no login page any more,
        # and sending somebody to one would be a loop. Reaching here means
        # the request did not come through Caddy, so it says so plainly
        # rather than pretending the person needs to do something.
        raise HTTPException(
            401,
            "This page is only reachable through the website's sign-in. "
            f"Go to https://{config.PUBLIC_HOST}{config.ROOT_PATH}/ rather "
            "than to this container directly.",
        )
    return u


def require_admin(request: Request) -> dict:
    u = require_user(request)
    if not u["is_admin"]:
        raise HTTPException(status_code=403, detail="Administrators only")
    return u


def fmt_ts(ts: float) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%d %b %Y, %-I:%M %p")


def _kb_current() -> str:
    """The knowledge version drafts are being written against right now.

    Cached for a minute: every job row on the dashboard asks, and hashing
    the knowledge directory per row would read the same five files sixty
    times to draw one page.
    """
    import time as _t
    now = _t.time()
    if now - _KB_CACHE["at"] > 60:
        try:
            _KB_CACHE["v"] = worker.build_system_prompt()[1]
        except Exception:  # noqa: BLE001
            _KB_CACHE["v"] = ""
        _KB_CACHE["at"] = now
    return _KB_CACHE["v"]


_KB_CACHE = {"at": 0.0, "v": ""}


def job_view(row) -> dict:
    d = dict(row)
    d["created_str"] = fmt_ts(row["created_at"])
    d["updated_str"] = fmt_ts(row["updated_at"])
    d["followup_list"] = db.jload(row["followups"], [])
    # WRITTEN AGAINST OLDER GUIDANCE? Every job records the knowledge
    # version it was drafted with. When the profile was corrected from
    # Major to Captain that version changed, so anything carrying the old
    # one says something about her that is no longer true. She should be
    # told which, and be able to redo it in one click.
    cur = _kb_current()
    d["kb_current"] = cur
    d["stale"] = bool(cur and d.get("kb_version") and d["kb_version"] != cur
                      and d.get("status") == "done")
    return d


templates.env.filters["fmt_ts"] = fmt_ts


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    return templates.TemplateResponse(request,
        "error.html",
        {"request": request, "root": config.ROOT_PATH, "site_name": config.SITE_NAME, "user": current_user(request),
         "code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code)


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    db.init_db()
    n = db.requeue_stuck_jobs()
    if n:
        db.log_event("warn", "startup", f"Requeued {n} interrupted job(s)")
    worker.start()
    db.log_event("info", "startup", "Portal started")


# --- dashboard ---------------------------------------------------------------

AWARD_TARGETS = [
    "Field Grade Officer of the Quarter",
    "Field Grade Officer of the Year",
    "AFMS Clinical Excellence in Nursing — Field Grade Nurse of the Year",
    "AFMS Outstanding Excellence in Nursing Leadership",
    "AFMS Nursing Educator of the Year",
    "MHS Military Nursing Leadership Excellence — Midgrade",
    "Lance P. Sijan Leadership Award — Senior Officer",
    "AMSUS Nursing Award",
    "Decoration (MSM / ASCOM / ASAM)",
    "Officer Performance Brief (OPB) input",
    "Other / not sure yet",
]


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_user(request)
    jobs = [job_view(j) for j in db.list_jobs(
        None if user["is_admin"] else user["username"], limit=60)]
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request, "root": config.ROOT_PATH, "site_name": config.SITE_NAME, "user": user, "jobs": jobs,
        "modes": worker.MODES, "award_targets": AWARD_TARGETS,
        "growth": portfolio.growth_series(),
        "max_mb": config.MAX_UPLOAD_MB})


@app.post("/upload")
async def upload(request: Request,
                 file: Optional[UploadFile] = File(None),
                 note: str = Form(""),
                 mode: str = Form("log"),
                 award_target: str = Form("")):
    user = require_user(request)
    note = (note or "").strip()

    stored_path = ""
    orig_name = "typed note"
    kind = "text"

    if file is not None and file.filename:
        orig_name = Path(file.filename).name
        ext = Path(orig_name).suffix.lower()
        if ext not in config.ALLOWED_EXT:
            raise HTTPException(400, f"'{ext}' files are not accepted. Allowed: "
                                     + ", ".join(sorted(config.ALLOWED_EXT)))
        kind = "audio" if ext in config.AUDIO_EXT else "document"
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        # TRUNCATE THE STEM, keep the suffix. [:80] on the whole name threw
        # away the extension of anything with a long title -- and the
        # extension is how llm.py knows what the file is. A 1.7 MB PDF whose
        # article headline ran past 80 characters was saved with no ".pdf",
        # read as "[Unsupported document type]", and reported to Casey as
        # probably being a scan that needed OCR. It was not (2026-09-07).
        # `ext` is already validated against ALLOWED_EXT above.
        stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(orig_name).stem)[:80]
        safe = f"{stem}{ext}"
        dest = config.UPLOAD_DIR / f"{int(time.time())}_{secrets.token_hex(4)}_{safe}"
        limit = config.MAX_UPLOAD_MB * 1024 * 1024
        written = 0
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"File is larger than {config.MAX_UPLOAD_MB} MB.")
                out.write(chunk)
        if written == 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "That file was empty.")
        stored_path = str(dest)
    elif not note:
        raise HTTPException(400, "Add a recording, a document, or some typed notes.")

    job_id = db.create_job(user["username"], mode, orig_name, stored_path, kind,
                           note=note, award_target=award_target)
    db.log_event("info", "upload", f"{user['username']} queued job {job_id} ({kind}, {mode})")
    return RedirectResponse(f"{config.ROOT_PATH}/job/{job_id}", status_code=303)


@app.get("/job/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int):
    user = require_user(request)
    row = db.get_job(job_id)
    if not row or (row["username"] != user["username"] and not user["is_admin"]):
        raise HTTPException(404, "That item does not exist.")
    return templates.TemplateResponse(request, "job.html", {
        "request": request, "root": config.ROOT_PATH, "site_name": config.SITE_NAME, "user": user,
        "job": job_view(row)})


@app.post("/job/{job_id}/answer")
def answer_followups(request: Request, job_id: int, answers: str = Form(...)):
    """Re-run the draft with her answers folded in, as a child job."""
    user = require_user(request)
    row = db.get_job(job_id)
    if not row or (row["username"] != user["username"] and not user["is_admin"]):
        raise HTTPException(404, "That item does not exist.")
    answers = (answers or "").strip()
    if not answers:
        return RedirectResponse(f"{config.ROOT_PATH}/job/{job_id}", status_code=303)

    questions = db.jload(row["followups"], [])
    qa = "\n".join(f"Q: {q}" for q in questions) + f"\n\nHer answers:\n{answers}"
    new_id = db.create_job(row["username"], row["mode"],
                           f"{row['orig_name']} (round 2)", "", "text",
                           note=row["transcript"], award_target=row["award_target"],
                           parent_id=job_id)
    db.update_job(new_id, answers=qa)
    return RedirectResponse(f"{config.ROOT_PATH}/job/{new_id}", status_code=303)


@app.post("/job/{job_id}/retry")
def retry_job(request: Request, job_id: int):
    user = require_user(request)
    row = db.get_job(job_id)
    if not row or (row["username"] != user["username"] and not user["is_admin"]):
        raise HTTPException(404, "That item does not exist.")
    db.update_job(job_id, status="queued", error="", progress="Waiting to retry...")
    return RedirectResponse(f"{config.ROOT_PATH}/job/{job_id}", status_code=303)


@app.get("/job/{job_id}/download")
def download_job(request: Request, job_id: int):
    user = require_user(request)
    row = db.get_job(job_id)
    if not row or (row["username"] != user["username"] and not user["is_admin"]):
        raise HTTPException(404, "That item does not exist.")
    text = f"# {row['orig_name']}\n\n{row['draft']}\n\n## Transcript\n\n{row['transcript']}\n"
    return PlainTextResponse(text, headers={
        "Content-Disposition": f'attachment; filename="job-{job_id}.md"'},
        media_type="text/markdown; charset=utf-8")


@app.get("/career-log")
def career_log(request: Request):
    require_user(request)
    path = config.OUTPUT_DIR / "career-log.md"
    if not path.exists():
        raise HTTPException(404, "No entries in the career log yet.")
    return FileResponse(path, filename="career-log.md", media_type="text/markdown; charset=utf-8")


# --- api ---------------------------------------------------------------------

@app.get("/api/status")
def api_status(request: Request):
    require_user(request)
    st = desktop.status()
    return {
        "desktop": st.to_dict(),
        "active_jobs": db.active_job_count(),
        "model": config.OLLAMA_MODEL,
        "auto_sleep_minutes": config.IDLE_SLEEP_MINUTES if config.AUTO_SLEEP else None,
    }


@app.get("/api/job/{job_id}")
def api_job(request: Request, job_id: int):
    user = require_user(request)
    row = db.get_job(job_id)
    if not row or (row["username"] != user["username"] and not user["is_admin"]):
        raise HTTPException(404, "not found")
    return {"id": row["id"], "status": row["status"], "progress": row["progress"],
            "error": row["error"]}


# --- talking to it -----------------------------------------------------------
#
#  The loop Jason asked for: speak a question, get an answer back in
#  seconds, and have BOTH kept. Speech in is the house's own speech
#  service; the answer comes from Claude when a key is present; the
#  answer goes back out through the house voice. Nothing is sent to
#  ChatGPT -- a consumer subscription carries no API access, so the
#  export is the bridge she carries there herself.


# --- the Four-Phase Quasi-Approach -------------------------------------------
#
#  A running gag between Jason and his sister: every plan is a four-phase
#  quasi-approach. Phase one analyses, phase four completes, and the two
#  in the middle are magnificent nonsense.
#
#  THE RULE THAT KEEPS IT USEFUL: the phase NAMES are the joke; what sits
#  under them is not. Real, grounded advice wearing a ridiculous hat. A
#  gag that costs her the substance stops being funny the moment she
#  actually needs the answer -- and the no-invention rule is untouched:
#  a silly heading is not licence to make up a fact about her career.
#
#  The middle names are drawn fresh each turn, because a running gag dies
#  the third time it produces the same two words.

QUASI_MIDDLE = [
    "Pre-Emptive Synergy Alignment",
    "Lateral Competency Marination",
    "Stakeholder Vibe Triangulation",
    "Retroactive Momentum Capture",
    "Cross-Functional Bandwidth Harvesting",
    "Iterative Excellence Scaffolding",
    "Strategic Ambiguity Resolution",
    "Downstream Value Percolation",
    "Holistic Leverage person24",
    "Dynamic Priority Fermentation",
    "Proactive Outcome Curation",
    "Vertical Insight Consolidation",
    "Frictionless Narrative Calibration",
    "Emergent Capability Sequencing",
    "Second-Order Impact Sharpening",
    "Adaptive Throughput Normalisation",
    "Convergent Opportunity Layering",
    "Deliberate Signal Amplification",
]


def quasi_clause() -> str:
    """The instruction, with two fresh middle phases picked for this turn."""
    a, b = random.sample(QUASI_MIDDLE, 2)
    return (
        "\n\nWhen she asks about her APPROACH, her strategy, or how to go "
        "about something, lay the answer out as a Four-Phase "
        "Quasi-Approach. This is a running joke in her family, so play it "
        "straight-faced:\n"
        "  Phase One: Analysis — what is actually true right now.\n"
        f"  Phase Two: {a} — the real first move, named ridiculously.\n"
        f"  Phase Three: {b} — the real second move, named ridiculously.\n"
        "  Phase Four: Completion — what finished looks like, concretely.\n"
        "The NAMES of phases two and three are the joke and should sound "
        "like expensive consulting nonsense. What you write UNDER each "
        "phase must be genuinely useful, specific to what she told you, "
        "and free of invention -- never make up a fact about her career "
        "to fill a phase. If a phase has nothing real in it, say so "
        "plainly under the silly heading; that is funnier than padding, "
        "and it is honest. Do not explain the joke."
    )


SYSTEM_PROMPT = (
    "You are helping Zanetta think about her career out loud. She is "
    "speaking, so answer the way you would speak back: plainly, in short "
    "paragraphs, no headings and no bullet lists unless she asks for a "
    "list. Be concrete and practical. When she describes something she "
    "achieved, help her put it in the language an award nomination or a "
    "resume would use, and say what evidence would strengthen it. If you "
    "do not know something about her situation, ask one short question "
    "rather than assuming. Never invent facts about her history, her "
    "employer, or her accomplishments."
)


@app.get("/talk", response_class=HTMLResponse)
def talk_page(request: Request):
    user = require_user(request)
    ok, why = exports.google_ready()
    return templates.TemplateResponse(request, "talk.html", {
        "request": request, "root": config.ROOT_PATH,
        "site_name": config.SITE_NAME, "user": user,
        "provider": config.provider(),
        "model": (config.ANTHROPIC_MODEL if config.provider() == "claude"
                  else config.OLLAMA_MODEL),
        "google_ready": ok, "google_why": why,
        "recent": db.qa_list(limit=40),
        "sessions": db.qa_sessions(limit=20),
    })


@app.post("/api/ask")
async def api_ask(request: Request,
                  audio: Optional[UploadFile] = File(None),
                  text: str = Form(""),
                  session: str = Form(""),
                  quasi: str = Form(""),
                  history: str = Form("")):
    """One turn: audio or text in, answer out, both written to the log."""
    user = require_user(request)
    session = (session or time.strftime("%Y-%m-%d")).strip()[:40]
    question = (text or "").strip()
    stored = ""

    if audio is not None and audio.filename:
        config.ensure_dirs()
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", audio.filename)[-60:] or "clip.webm"
        dest = config.UPLOAD_DIR / f"ask-{int(time.time())}-{secrets.token_hex(3)}-{safe}"
        dest.write_bytes(await audio.read())
        stored = str(dest)
        try:
            question = llm.transcribe(dest).strip()
        except Exception as e:  # noqa: BLE001
            db.log_event("error", "stt", f"transcription failed: {e}")
            raise HTTPException(502, f"Could not transcribe that: {e}")
    if not question:
        raise HTTPException(400, "Nothing was asked -- no words came through.")

    prior = []
    try:
        prior = json.loads(history) if history else []
        prior = [m for m in prior
                 if isinstance(m, dict) and m.get("role") in ("user", "assistant")][-12:]
    except Exception:  # noqa: BLE001
        prior = []

    # HER KNOWLEDGE BASE, NOT A GENERIC COACH (2026-09-04). This route
    # was sending only the short prompt below, so it answered as if she
    # were any nurse thinking about her career -- when the knowledge
    # directory already knows she is a Field Grade Major in the Air Force
    # Nurse Corps competing head-to-head against Lt Cols, that a package
    # filed in a Company Grade category is returned unscored, and that
    # her Master's is IN PROGRESS and must never be stated as held.
    # Generic advice was the wrong answer to every question she asked.
    kb_system, _kb_version = worker.build_system_prompt()
    system = kb_system + "\n\n" + SYSTEM_PROMPT
    if quasi.strip().lower() in ("1", "true", "on", "yes"):
        system += quasi_clause()
    try:
        answer, model = llm.ask(system, question, prior)
    except Exception as e:  # noqa: BLE001
        db.log_event("error", "llm", f"ask failed: {e}")
        raise HTTPException(502, f"No answer came back: {e}")

    spoken = ""
    if config.SPEAK_ANSWERS:
        # Rendered once and kept, keyed by the words themselves -- an
        # answer that has been spoken before costs nothing to speak
        # again. See llm.speak_cached.
        said = llm.speak_cached(answer, config.OUTPUT_DIR)
        spoken = said.name if said else ""

    qid = db.qa_add(session, user["username"], question, answer, model,
                    "voice" if stored else "typed", stored, spoken)
    # A spoken question is a recording too -- one library, not two, so
    # searching for something she said finds it wherever she said it.
    if stored:
        try:
            db.rec_add(user["username"], Path(stored).name, stored,
                       Path(stored).stat().st_size, source="asked",
                       title=question[:80], transcript=question, status="done")
        except Exception as e:  # noqa: BLE001
            db.log_event("warn", "recordings", f"could not file the question: {e}")
    return {"id": qid, "question": question, "answer": answer,
            "model": model, "session": session,
            "audio": f"{config.ROOT_PATH}/said/{spoken}" if spoken else ""}


@app.get("/said/{name}")
def said(request: Request, name: str):
    """The spoken answer, played back by the page."""
    require_user(request)
    if not re.fullmatch(r"say-[0-9a-f]+\.mp3|said-[0-9a-f-]+\.mp3", name):
        raise HTTPException(404, "not found")
    path = config.OUTPUT_DIR / name
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/api/qa")
def api_qa(request: Request, session: str = "", limit: int = 200):
    require_user(request)
    return {"rows": db.qa_list(limit=min(limit, 1000), session=session)}


# --- her recordings ----------------------------------------------------------
#
#  Audio was already being saved but nothing could play it back and
#  nothing listed it, so in practice it was lost. This is the library:
#  add a recording, it is stored, transcribed in the background, and
#  stays playable with its text beside it.
#
#  The GROWTH mark is hers to place -- the moments worth returning to.
#  It is what turns the log into a record of progress rather than a pile
#  of transcript, and it is what Hermes reaches for first.

@app.get("/recordings", response_class=HTMLResponse)
def recordings_page(request: Request, q: str = "", growth: int = 0):
    user = require_user(request)
    rows = db.rec_list(limit=200, q=q)
    if growth:
        rows = [r for r in rows if r.get("growth")]
    return templates.TemplateResponse(request, "recordings.html", {
        "request": request, "root": config.ROOT_PATH,
        "site_name": config.SITE_NAME, "user": user,
        "rows": rows, "q": q, "growth": growth,
        "audio_ext": ", ".join(sorted(config.AUDIO_EXT)),
        "max_mb": config.MAX_UPLOAD_MB,
    })


@app.post("/recordings/upload")
async def recordings_upload(request: Request,
                            files: list[UploadFile] = File(default=[]),
                            title: str = Form(""),
                            note: str = Form("")):
    """Add one or many recordings. Each is saved first and queued second,
    so a transcription that fails still leaves her the audio."""
    user = require_user(request)
    config.ensure_dirs()
    added = 0
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    for f in files:
        if not f or not f.filename:
            continue
        name = Path(f.filename).name
        ext = Path(name).suffix.lower()
        if ext not in config.AUDIO_EXT:
            db.log_event("warn", "recordings", f"refused {name} ({ext})")
            continue
        # Same fix as the document upload above: the suffix is load-bearing
        # and must survive truncation. `ext` is validated against AUDIO_EXT.
        stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).stem)[:80]
        safe = f"{stem}{ext}"
        dest = config.UPLOAD_DIR / f"rec-{int(time.time())}-{secrets.token_hex(4)}-{safe}"
        written = 0
        with dest.open("wb") as out:
            while chunk := await f.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"{name} is over {config.MAX_UPLOAD_MB} MB.")
                out.write(chunk)
        if not written:
            dest.unlink(missing_ok=True)
            continue
        db.rec_add(user["username"], name, str(dest), written,
                   source="uploaded", title=title.strip(), note=note.strip())
        added += 1
    if not added:
        raise HTTPException(400, "No audio was added. Accepted: "
                                 + ", ".join(sorted(config.AUDIO_EXT)))
    db.log_event("info", "recordings", f"{user['username']} added {added}")
    return RedirectResponse(f"{config.ROOT_PATH}/recordings", status_code=303)


@app.get("/recordings/{rec_id}/audio")
def recording_audio(request: Request, rec_id: int):
    require_user(request)
    row = db.rec_get(rec_id)
    if not row:
        raise HTTPException(404, "not found")
    path = Path(row["stored_path"])
    if not path.exists():
        raise HTTPException(410, "The audio for this one is no longer on disk.")
    return FileResponse(path, filename=row["orig_name"] or path.name)


@app.post("/recordings/{rec_id}/retranscribe")
def recording_retranscribe(request: Request, rec_id: int):
    require_user(request)
    if not db.rec_get(rec_id):
        raise HTTPException(404, "not found")
    db.rec_update(rec_id, status="queued", error="")
    return RedirectResponse(f"{config.ROOT_PATH}/recordings", status_code=303)


@app.post("/recordings/{rec_id}/growth")
def recording_growth(request: Request, rec_id: int, on: int = Form(1)):
    require_user(request)
    db.set_growth("recording", rec_id, bool(on))
    return RedirectResponse(f"{config.ROOT_PATH}/recordings", status_code=303)


@app.post("/qa/{qa_id}/growth")
def qa_growth(request: Request, qa_id: int, on: int = Form(1)):
    require_user(request)
    db.set_growth("qa", qa_id, bool(on))
    return JSONResponse({"ok": True})


@app.post("/recordings/{rec_id}/forget")
def recording_forget(request: Request, rec_id: int):
    """Drops the row, LEAVES the file. A mistaken click should cost an
    entry, never the tape."""
    require_user(request)
    path = db.rec_delete(rec_id)
    if path is None:
        raise HTTPException(404, "not found")
    db.log_event("info", "recordings", f"forgot {rec_id}; file kept at {path}")
    return RedirectResponse(f"{config.ROOT_PATH}/recordings", status_code=303)


@app.get("/api/progress")
def api_progress(request: Request):
    """The same read the page and the sheet use, as JSON -- so Hermes
    cannot report a different number from the one she is looking at."""
    require_user(request)
    p = portfolio.progress()
    return {"lines": portfolio.progress_lines(),
            "total": p["total"], "by_status": p["by_status"],
            "ready_unsent": [e["title"] for e in p["ready_unsent"]],
            "stale": [e["title"] for e in p["stale"]],
            "growth_moments": p["growth_moments"]}


@app.get("/api/notes/search")
def api_notes_search(request: Request, q: str = "", limit: int = 30,
                     growth: int = 0):
    """One search across her recordings and her exchanges.

    This is the surface Hermes reads, so it stays plain JSON and answers
    the same way whether it is a person or the house assistant asking.
    """
    require_user(request)
    rows = db.search_notes(q, limit=min(limit, 200), growth_only=bool(growth))
    return {"query": q, "growth_only": bool(growth), "count": len(rows),
            "results": [{**r, "text": (r["text"] or "")[:1500]} for r in rows]}


# --- the portfolio -----------------------------------------------------------
#
#  A transcript is a record of talking; this is a record of DOING, shaped
#  the way a promotion case and an award nomination both ask for it. An
#  entry can be drafted from something she already said -- a recording,
#  an exchange -- so the work of writing it up is mostly done by the time
#  she looks at it.
#
#  Two copies on purpose: SQLite here is the working copy, Postgres is
#  the archive that outlives the app. The mirror is best-effort -- if the
#  archive is down the entry is still saved and simply marked unmirrored.

@app.get("/portfolio", response_class=HTMLResponse)
def portfolio_page(request: Request, status: str = "", category: str = ""):
    user = require_user(request)
    ok, why = portfolio.archive_ready()
    gok, gwhy = exports.google_ready()
    return templates.TemplateResponse(request, "portfolio.html", {
        "request": request, "root": config.ROOT_PATH,
        "site_name": config.SITE_NAME, "user": user,
        "rows": db.portfolio_list(status=status, category=category),
        "status": status, "category": category,
        "categories": portfolio.CATEGORIES, "statuses": portfolio.STATUSES,
        "fields": portfolio.FIELDS,
        "archive_ok": ok, "archive_why": why,
        "unmirrored": db.portfolio_unmirrored(),
        "google_ready": gok, "google_why": gwhy,
        "recordings": db.rec_list(limit=40),
        "exchanges": db.qa_list(limit=40),
        # Where she is up to, on the page she is already looking at.
        "progress": portfolio.progress(),
        "progress_lines": portfolio.progress_lines(),
        # THE STAT ROW (2026-09-07). Counts, not a score: roadmap.py refuses
        # to produce a readiness percentage and says why -- one that ignored
        # her grade once reported "7 of 7 ready" for an award a Captain
        # cannot enter. A count states a fact; a score implies a judgement.
        #
        # Computed over the WHOLE record, not the filtered `rows` above, so
        # the numbers do not change meaning when she picks a category.
        **portfolio.stat_counts(),
    })


@app.post("/portfolio/new")
def portfolio_new(request: Request, title: str = Form(""),
                  situation: str = Form(""), task: str = Form(""),
                  action: str = Form(""), result: str = Form(""),
                  evidence: str = Form(""), skills: str = Form(""),
                  happened_on: str = Form(""), category: str = Form("accomplishment"),
                  award_target: str = Form(""), status: str = Form("draft"),
                  note: str = Form("")):
    user = require_user(request)
    if not (title.strip() or situation.strip() or action.strip()):
        raise HTTPException(400, "An entry needs at least a title or what happened.")
    entry = {"title": title, "situation": situation, "task": task,
             "action": action, "result": result, "evidence": evidence,
             "skills": skills, "happened_on": happened_on,
             "category": category, "award_target": award_target,
             "status": status, "note": note}
    # FEEDBACK IS FETCHED AFTER THE REDIRECT, NOT BEFORE IT. Asking a
    # model what it thinks of the entry takes seconds; making her wait
    # those seconds to find out her entry saved would teach her that
    # writing things down is slow. So: save, redirect, and let the page
    # ask about ?fb= on its own.
    new_id = db.portfolio_add(user["username"], entry)
    portfolio.mirror()
    return RedirectResponse(f"{config.ROOT_PATH}/portfolio?fb={new_id}",
                            status_code=303)


@app.post("/portfolio/draft")
def portfolio_draft(request: Request, kind: str = Form(""),
                    source_id: int = Form(0), text: str = Form("")):
    """Turn something she already said into a structured entry."""
    user = require_user(request)
    body = text.strip()
    if kind == "recording" and source_id:
        row = db.rec_get(source_id)
        body = (row or {}).get("transcript", "")
    elif kind == "exchange" and source_id:
        row = db.qa_list(limit=1000)
        row = next((r for r in row if r["id"] == source_id), None)
        body = f"{(row or {}).get('question','')}\n\n{(row or {}).get('answer','')}"
    if not body.strip():
        raise HTTPException(400, "There is nothing there to draft from.")
    entry, model = portfolio.draft_from_text(body)
    new_id = db.portfolio_add(user["username"], entry, source_kind=kind or "typed",
                              source_id=source_id or None, model=model)
    portfolio.mirror()
    return RedirectResponse(f"{config.ROOT_PATH}/portfolio?fb={new_id}",
                            status_code=303)


@app.post("/portfolio/{entry_id}/save")
async def portfolio_save(request: Request, entry_id: int):
    user = require_user(request)
    form = await request.form()
    fields = {k: str(v) for k, v in form.items() if k in db.PORTFOLIO_FIELDS}
    if not db.portfolio_get(entry_id):
        raise HTTPException(404, "not found")
    db.portfolio_update(entry_id, **fields)
    portfolio.mirror()
    return RedirectResponse(f"{config.ROOT_PATH}/portfolio?fb={entry_id}",
                            status_code=303)


@app.post("/portfolio/{entry_id}/delete")
def portfolio_del(request: Request, entry_id: int):
    require_user(request)
    db.portfolio_delete(entry_id)
    return RedirectResponse(f"{config.ROOT_PATH}/portfolio", status_code=303)


@app.post("/portfolio/mirror")
def portfolio_mirror_now(request: Request):
    require_user(request)
    ok, msg = portfolio.mirror()
    return JSONResponse({"ok": ok, "message": msg},
                        status_code=200 if ok else 409)


# --- the running document ----------------------------------------------------

EXPORT_KINDS = {
    "md":   ("career-conversation.md", "text/markdown", exports.write_markdown),
    "csv":  ("career-conversation.csv", "text/csv", exports.write_csv),
    "docx": ("career-conversation.docx",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             exports.write_docx),
    "xlsx": ("career-conversation.xlsx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             exports.write_xlsx),
}


# --- what the background pass found, and what it thinks of one entry ---------

@app.get("/api/feedback/{entry_id}")
def api_feedback(request: Request, entry_id: int):
    """What to say about an entry the moment after she saves it.

    Fetched by the page rather than computed during the save -- see
    portfolio_new() for why. A failure here returns {} and the page shows
    nothing; the entry is already safe either way.
    """
    require_user(request)
    entry = db.portfolio_get(entry_id)
    if not entry:
        raise HTTPException(404, "not found")
    try:
        system, _ = worker.build_system_prompt()
    except Exception:  # noqa: BLE001
        system = ""
    return research.feedback(entry, system_prompt=system)


@app.get("/api/findings")
def api_findings(request: Request, limit: int = 50, unseen: int = 0):
    require_user(request)
    rows = db.findings_list(limit=limit, unseen_only=bool(unseen))
    return {"unseen": db.findings_unseen_count(),
            "findings": [{**r, "when": fmt_ts(r["ts"])} for r in rows]}


@app.post("/api/findings/seen")
async def api_findings_seen(request: Request):
    """Mark findings read. Called when she actually opens the panel --
    not when the page loads, or the badge would clear itself before she
    ever saw what was in it."""
    require_user(request)
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        pass
    ids = [int(i) for i in (body.get("ids") or []) if str(i).isdigit()]
    return {"marked": db.findings_mark_seen(ids or None),
            "unseen": db.findings_unseen_count()}


@app.post("/findings/{finding_id}/dismiss")
def finding_dismiss(request: Request, finding_id: int):
    require_user(request)
    db.finding_dismiss(finding_id)
    return RedirectResponse(f"{config.ROOT_PATH}/", status_code=303)


@app.post("/api/research/run")
def api_research_run(request: Request):
    """Run a pass now rather than waiting for the loop.

    Here because "is this thing actually doing anything?" is a fair
    question to be able to answer without reading logs.
    """
    require_user(request)
    try:
        system, _ = worker.build_system_prompt()
    except Exception:  # noqa: BLE001
        system = ""
    return research.scan(system_prompt=system)


# --- one award at a time: pick it, take it away, bring it back ---------------

@app.get("/targets", response_class=HTMLResponse)
def targets_page(request: Request, award: str = ""):
    """The dropdown. One award selected, her state, and the drafting box."""
    user = require_user(request)
    rows = awards.listing()
    chosen = award or (rows[0]["id"] if rows else "")
    ref = awards.get(chosen)
    return templates.TemplateResponse(request, "targets.html", {
        "request": request, "root": config.ROOT_PATH,
        "site_name": config.SITE_NAME, "user": user,
        "awards": rows, "chosen": chosen, "ref": ref,
        "state": db.target_get(chosen),
        "statuses": awards.STATUSES, "status_label": awards.STATUS_LABEL,
        "history": db.target_history(chosen, limit=12),
        "fmt": awards.get(chosen).get("format", ""),
    })


@app.post("/targets/{award_id}/save")
def target_save(request: Request, award_id: str,
                status: str = Form(""), next_action: str = Form(""),
                notes: str = Form(""), owner_note: str = Form(""),
                deadline_note: str = Form("")):
    user = require_user(request)
    if award_id not in awards.all_awards():
        raise HTTPException(404, "no such award")
    db.target_set(award_id, via="portal", username=user["username"],
                  status=status, next_action=next_action, notes=notes,
                  owner_note=owner_note, deadline_note=deadline_note)
    return RedirectResponse(f"{config.ROOT_PATH}/targets?award={award_id}",
                            status_code=303)


@app.get("/targets/{award_id}/export.md")
def target_export(request: Request, award_id: str):
    """The markdown for one award. One file per award, deliberately --
    a single file with everything in it is not something she can hand to
    anyone or edit without wading."""
    require_user(request)
    try:
        md = awards.export_markdown(award_id)
    except KeyError:
        raise HTTPException(404, "no such award")
    return Response(
        content=md, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{award_id}.md"'})


@app.post("/targets/import")
async def target_import(request: Request, file: UploadFile = File(None),
                        text: str = Form("")):
    """Read an edited award file back in.

    Only her half is taken -- the reference half is regenerated from disk
    on every export and ignored here. A file that has been through a chat
    window is not a trustworthy source for eligibility rules; a model
    asked to tidy it up will smooth a [POLICY UNVERIFIED] into a
    confident sentence."""
    user = require_user(request)
    body = text or ""
    if file is not None and file.filename:
        body = (await file.read()).decode("utf-8", "replace")
    if not body.strip():
        raise HTTPException(400, "Nothing was uploaded.")
    try:
        r = awards.import_markdown(body, via="upload",
                                   username=user["username"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(
        f"{config.ROOT_PATH}/targets?award={r['award_id']}", status_code=303)


@app.post("/api/targets/{award_id}/draft")
def target_draft(request: Request, award_id: str, extra: str = Form("")):
    """Her record, written in THIS target's language. See render.py."""
    require_user(request)
    try:
        system, _ = worker.build_system_prompt()
    except Exception:  # noqa: BLE001
        system = ""
    return render.draft(award_id, system_prompt=system, extra=extra)


@app.get("/targets/{award_id}/draft.md")
def target_draft_file(request: Request, award_id: str):
    require_user(request)
    try:
        system, _ = worker.build_system_prompt()
    except Exception:  # noqa: BLE001
        system = ""
    md = render.draft_markdown(render.draft(award_id, system_prompt=system))
    return Response(
        content=md, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{award_id}-draft.md"'})


# --- ChatGPT: her history in, and a door for it to come back through --------

app.include_router(actions.router)


@app.get("/actions/openapi.json", include_in_schema=False)
def actions_openapi(request: Request):
    """The schema a ChatGPT custom GPT is pointed at.

    Built from the live routes rather than written by hand, so it cannot
    drift from what the server actually does -- a hand-kept schema that
    has fallen behind produces failures inside ChatGPT that are very hard
    to read from there.
    """
    from fastapi.openapi.utils import get_openapi
    base = config.PUBLIC_URL or str(request.base_url).rstrip("/")
    spec = get_openapi(title="Casey career record", version="1.0.0",
                       description=("Her awards, promotions and career record. "
                                    "Everything written here is shared with "
                                    "her website and her phone."),
                       routes=[r for r in app.routes
                               if getattr(r, "path", "").startswith("/actions/")])
    spec["servers"] = [{"url": base}]
    return JSONResponse(spec)


@app.get("/chatgpt", response_class=HTMLResponse)
def chatgpt_page(request: Request, msg: str = ""):
    user = require_user(request)
    return templates.TemplateResponse(request, "chatgpt.html", {
        "request": request, "root": config.ROOT_PATH,
        "site_name": config.SITE_NAME, "user": user, "msg": msg,
        "have_token": bool(config.ACTION_TOKEN),
        "public_url": config.PUBLIC_URL,
        "convs": _CHATGPT_CACHE.get("convs") or [],
        "loaded_at": _CHATGPT_CACHE.get("at", 0),
    })


# The uploaded export, held in memory between picking the file and picking
# the conversation. NOT written to disk: it is her entire chat history with
# an assistant, most of which has nothing to do with her career, and there
# is no reason for this machine to keep a copy of all of it.
_CHATGPT_CACHE: dict = {}


@app.post("/chatgpt/upload")
async def chatgpt_upload(request: Request, file: UploadFile = File(...)):
    require_user(request)
    raw = await file.read()
    if len(raw) > chatgpt.MAX_BYTES:
        raise HTTPException(413, "That export is too large.")
    try:
        convs = chatgpt.conversations(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _CHATGPT_CACHE.clear()
    _CHATGPT_CACHE.update({"raw": raw, "convs": convs, "at": time.time()})
    return RedirectResponse(
        f"{config.ROOT_PATH}/chatgpt?msg=Found+{len(convs)}+conversations.",
        status_code=303)


@app.post("/chatgpt/import")
def chatgpt_import(request: Request, conversation_id: str = Form(...),
                   extract: str = Form("")):
    user = require_user(request)
    raw = _CHATGPT_CACHE.get("raw")
    if not raw:
        raise HTTPException(400, "Upload the export again -- it is not held "
                                 "between restarts on purpose.")
    try:
        t = chatgpt.file_transcript(raw, conversation_id,
                                    username=user["username"])
    except KeyError:
        raise HTTPException(404, "That conversation is not in the export.")
    made = 0
    if extract.strip() in ("1", "on", "true", "yes"):
        try:
            system, _ = worker.build_system_prompt()
        except Exception:  # noqa: BLE001
            system = ""
        # HER WORDS ONLY. The assistant's half of a conversation is where
        # invented detail lives -- it will have drafted bullets, offered
        # numbers and suggested phrasings, and none of that is evidence of
        # anything she actually did.
        for e in chatgpt.extract_entries(t["hers_only"], system_prompt=system):
            quote, conf = e.pop("quote", ""), e.pop("confidence", "")
            e.pop("model", None)
            e["status"] = "draft"
            e["note"] = (f"From ChatGPT: {t['title'][:60]}. "
                         f"Confidence {conf}. She said: {quote[:300]}")
            db.portfolio_add(user["username"], e, source_kind="chatgpt",
                             source_id=t["recording_id"])
            made += 1
        portfolio.mirror()
    return RedirectResponse(
        f"{config.ROOT_PATH}/chatgpt?msg=Imported+{t['messages']}+messages"
        f"+and+drafted+{made}+entries.", status_code=303)


# --- documents: archived in Paperless, read into her record -----------------

@app.get("/documents", response_class=HTMLResponse)
def documents_page(request: Request, msg: str = ""):
    user = require_user(request)
    return templates.TemplateResponse(request, "documents.html", {
        "request": request, "root": config.ROOT_PATH,
        "site_name": config.SITE_NAME, "user": user, "msg": msg,
        "configured": archive.configured(),
        "docs": archive.recent(20),
        "paperless": archive.PUBLIC,
    })


@app.get("/api/documents")
def api_documents(request: Request):
    require_user(request)
    return {"configured": archive.configured(), "documents": archive.recent(30)}


@app.post("/documents/upload")
async def documents_upload(request: Request, file: UploadFile = File(...),
                           title: str = Form(""), sort: str = Form("1")):
    """Take the file and hand back a job to watch.

    This used to do the whole chain inside the POST -- file it, wait for
    OCR, call a model, write to her cloud -- which is up to ninety seconds
    of a page doing nothing on a phone, with no way to tell a slow model
    from a broken one. Now it returns at once and she watches the steps.
    """
    user = require_user(request)
    config.ensure_dirs()
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "")[-70:] or "upload"
    dest = config.UPLOAD_DIR / f"doc-{int(time.time())}-{secrets.token_hex(3)}-{safe}"
    dest.write_bytes(await file.read())
    job_id = imports.start(dest, title or safe, user["username"],
                           sort=sort.strip() in ("1", "on", "true", "yes"))
    return RedirectResponse(f"{config.ROOT_PATH}/documents?job={job_id}",
                            status_code=303)


@app.get("/api/import/{job_id}")
def api_import(request: Request, job_id: str):
    """What step it is on, for the progress the page shows."""
    require_user(request)
    j = imports.get(job_id)
    if not j:
        raise HTTPException(404, "No such import.")
    j["elapsed"] = round((j.get("finished") or time.time()) - j["started"], 1)
    j["labels"] = dict(imports.STEPS)
    j["order"] = [k for k, _ in imports.STEPS]
    return j


@app.get("/api/working")
def api_working(request: Request):
    require_user(request)
    text = working.read()
    return {"configured": working.configured(), "url": working.public_url(),
            "words": len(text.split()), "bytes": len(text)}


@app.get("/working/for-chatgpt.md")
def working_for_chatgpt(request: Request):
    """Her document, ready to paste into a chat.

    The collapsed transcript blocks are stripped -- see working.for_chatgpt
    for why sending them back is a waste of her context.
    """
    require_user(request)
    text = working.for_chatgpt()
    if not text:
        raise HTTPException(404, "There is nothing in the working document yet.")
    return Response(content=text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="career-working-document.md"'})


# --- dictation that survives a bad signal -----------------------------------
#
#  Chunked and resumable because she records in a car, in a kitchen, with
#  children about. See dictate.py for why chunk writes are idempotent --
#  it is the property that makes retrying safe on a phone that cannot
#  tell whether its last attempt landed.

@app.get("/dictate", response_class=HTMLResponse)
def dictate_page(request: Request):
    user = require_user(request)
    return templates.TemplateResponse(request, "dictate.html", {
        "root": config.ROOT_PATH, "site_name": config.SITE_NAME, "user": user,
    })


@app.post("/api/dictate/start")
def api_dictate_start(request: Request, mime: str = Form("audio/webm")):
    user = require_user(request)
    return dictate.start(user["username"], mime=mime)


@app.put("/api/dictate/{sid}/chunk/{index}")
async def api_dictate_chunk(request: Request, sid: str, index: int):
    """One chunk. Sending the same index twice is safe and expected.

    PUT rather than POST on purpose: this is idempotent, and saying so in
    the method is what tells a retrying client -- or a proxy -- that
    repeating it is harmless.
    """
    require_user(request)
    body = await request.body()
    if not body:
        raise HTTPException(400, "That chunk was empty.")
    try:
        return dictate.put_chunk(sid, index, body)
    except dictate.DictateError as e:
        raise HTTPException(400, str(e))


@app.get("/api/dictate/{sid}/have")
def api_dictate_have(request: Request, sid: str):
    """Which chunks landed. The client sends only what is missing, which
    is the difference between resuming and starting the drive home again."""
    require_user(request)
    try:
        return {"have": dictate.have(sid)}
    except dictate.DictateError as e:
        raise HTTPException(404, str(e))


@app.post("/api/dictate/{sid}/finish")
def api_dictate_finish(request: Request, sid: str):
    require_user(request)
    try:
        m = dictate.finish(sid)
    except dictate.DictateError as e:
        raise HTTPException(400, str(e))
    return {"id": m["id"], "transcript": m.get("transcript", ""),
            "segments": m.get("segments", []), "error": m.get("error", "")}


@app.get("/api/dictate/{sid}")
def api_dictate_get(request: Request, sid: str):
    require_user(request)
    try:
        m = dictate.meta(sid)
    except dictate.DictateError as e:
        raise HTTPException(404, str(e))
    return {"id": m["id"], "finished": m.get("finished", False),
            "have": len(m.get("chunks", {})),
            "transcript": m.get("transcript", ""),
            "segments": m.get("segments", []), "error": m.get("error", "")}


@app.post("/api/dictate/{sid}/segments")
async def api_dictate_segments(request: Request, sid: str):
    """Her edits. She is the authority on her own transcript."""
    require_user(request)
    body = await request.json()
    try:
        m = dictate.set_segments(sid, body.get("segments") or [])
    except dictate.DictateError as e:
        raise HTTPException(400, str(e))
    return {"saved": len(m.get("segments") or [])}


@app.post("/api/dictate/{sid}/keep")
def api_dictate_keep(request: Request, sid: str, title: str = Form("")):
    """File what she kept: a recording, and a section in her document.

    The AUDIO is filed too, not just the words. A transcript of speech in
    a car is imperfect, and the recording is the only way to settle what
    she actually said.
    """
    user = require_user(request)
    try:
        m = dictate.meta(sid)
        text = dictate.kept_text(sid)
    except dictate.DictateError as e:
        raise HTTPException(404, str(e))
    if not text.strip():
        raise HTTPException(400, "Nothing was kept.")
    name = title.strip() or time.strftime("Dictated %d %b %Y, %H:%M")
    rec_id = None
    try:
        audio = dictate.assemble(sid)
        rec_id = db.rec_add(user["username"], audio.name, str(audio),
                            audio.stat().st_size, source="dictated",
                            title=name[:120], transcript=text, status="done")
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "dictate", f"could not file the audio: {e}")
    added = ""
    try:
        section = working.section_from_import(
            name, "dictated note", "", [], quotes=text[:6000])
        added = working.append(section)["url"]
    except working.WorkingError as e:
        added = ""
        db.log_event("warn", "dictate", f"could not add to the document: {e}")
    return {"recording_id": rec_id, "doc_url": added, "words": len(text.split())}


# --- handing the whole thing to ChatGPT, and hearing it read back ----------

@app.get("/handoff.md")
def handoff_file(request: Request, verbose: int = 1, session: str = ""):
    """Everything ChatGPT needs to take over.

    For the day his credit runs out: she pastes this into the ChatGPT
    subscription she already pays for and carries on. It leads with the
    three rules that decide whether a package survives a board, because a
    model that does not know them writes fluent prose that gets her
    package returned.
    """
    require_user(request)
    text = handoff.build(verbose=bool(verbose), session_text=session)
    return Response(content=text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="casey-handoff.md"'})


@app.get("/api/handoff")
def api_handoff(request: Request, verbose: int = 1):
    """The same thing as JSON, so the page can offer copy-to-clipboard.

    Copying beats downloading here: the destination is a chat box, and a
    .md file on a phone takes four taps to get into one.
    """
    require_user(request)
    text = handoff.build(verbose=bool(verbose))
    return {"text": text, "words": len(text.split()),
            "summary": handoff.summary()}


@app.post("/api/dictate/{sid}/speak")
def api_dictate_speak(request: Request, sid: str):
    """Read the kept transcript back to her.

    Jason asked for this after an upload, and it earns its place when she
    is driving: she cannot read a screen, but she can hear whether the
    thing that came back is what she meant. Rendered once and cached by
    the words themselves, so hearing it twice costs nothing.
    """
    require_user(request)
    try:
        text = dictate.kept_text(sid)
    except dictate.DictateError as e:
        raise HTTPException(404, str(e))
    if not text.strip():
        raise HTTPException(400, "There is nothing to read back.")
    said = llm.speak_cached(text[:4000], config.OUTPUT_DIR)
    if not said:
        raise HTTPException(502, "The voice service did not answer.")
    return {"audio": f"{config.ROOT_PATH}/said/{said.name}",
            "words": len(text.split())}


# --- the Claude tier: a queue, because Claude Code is not an endpoint -------
#
#  See deepreview.py. There is no Anthropic key in this stack and Claude
#  Code is an interactive tool tied to Jason's own login, so the portal
#  cannot call it. What it CAN do is leave the hard things where he will
#  find them next time he is in it -- which spends the good model on the
#  few packages that decide a quarter rather than on every transcription.

@app.get("/api/review")
def api_review(request: Request):
    require_user(request)
    return {"available": deepreview.available(),
            "waiting": deepreview.waiting(),
            "items": deepreview.listing(20)}


@app.post("/api/review/ask")
def api_review_ask(request: Request, kind: str = Form("entry"),
                   title: str = Form(""), question: str = Form(""),
                   entry_id: int = Form(0), award_id: str = Form("")):
    """Put something in front of Claude.

    The MATERIAL is assembled here rather than trusted from the browser:
    the point is that whoever answers sees the real record, not whatever a
    form field happened to contain.
    """
    user = require_user(request)
    if not deepreview.available():
        raise HTTPException(503, "The review folder is not mounted.")
    body, name = "", title.strip()
    if entry_id:
        e = db.portfolio_get(entry_id)
        if not e:
            raise HTTPException(404, "No such entry.")
        name = name or (e.get("title") or "Portfolio entry")
        body = "\n".join(
            f"- {f.capitalize()}: {e[f]}" for f in
            ("happened_on", "category", "award_target", "situation", "task",
             "action", "result", "evidence", "skills")
            if (e.get(f) or "").strip())
    elif award_id:
        a = awards.get(award_id)
        if not a:
            raise HTTPException(404, "No such award.")
        name = name or f"Draft for {a['name']}"
        try:
            system, _ = worker.build_system_prompt()
        except Exception:  # noqa: BLE001
            system = ""
        d = render.draft(award_id, system_prompt=system)
        body = ("## The award's own rules\n\n"
                + (render.format_guidance(award_id) or "(none recorded)")
                + "\n\n## The draft as it stands\n\n"
                + (d.get("draft") or "(nothing drafted)")
                + ("\n\n## Still missing\n\n"
                   + "\n".join("- " + m for m in (d.get("missing") or []))
                   if d.get("missing") else ""))
    else:
        body = "## Her record\n\n" + "\n".join(
            f"- {r['title']} ({r['status']})" for r in db.portfolio_list(limit=30))
    r = deepreview.ask(kind, name or "A question", body, question,
                       username=user["username"])
    return {"queued": r["file"], "waiting": deepreview.waiting()}


# --- /jacket: her career on a rail ------------------------------------------

def _open_questions(limit: int = 40) -> list:
    """Follow-up questions across her record that nobody has answered.

    Flattened across entries on purpose: from her side these are one
    queue of small things to answer, not a per-entry chore list, and
    seeing three left is far more finishable than seeing three entries
    each with something outstanding.
    """
    out = []
    for e in db.portfolio_list(limit=limit):
        for i, q in enumerate(db.entry_followups_get(e["id"])):
            if not (q.get("answer") or "").strip():
                out.append({"entry_id": e["id"], "index": i,
                            "ask": q.get("ask", ""), "why": q.get("why", ""),
                            "title": e["title"] or "(untitled)"})
    return out


def _jacket_identity(user: dict) -> tuple:
    """(name, rank) for the jacket header, read from the profile file.

    Falls back to her login only if the profile carries neither, because a
    wrong rank at the top of her own record is worse than a plain one.
    """
    name, rank = "", ""
    selected = False
    try:
        for p in llm.knowledge_files():
            if not p.name.startswith("10-"):
                continue
            t = p.read_text(encoding="utf-8", errors="replace")
            # SEVERAL SPELLINGS, because this has already broken once.
            # The field was "**Name:**" until the profile was corrected
            # from her citation, when it became "**Surname on official
            # documents:**". The header then fell back to her login and
            # printed "CASEY Owner 16" across a service jacket. Match what
            # is actually there rather than one spelling of it.
            for pat in (r"\*\*How she is referred to in drafts:\*\*\s*`?"
                        r"(?:Capt|Maj|Lt Col|Col)\s+([A-Za-z][A-Za-z'-]+)",
                        r"\*\*Surname on official documents:\*\*\s*\*?\*?"
                        r"([A-Za-z][A-Za-z'-]+)",
                        r"\*\*Name:\*\*\s*([^\n*(]+)"):
                m = re.search(pat, t)
                if m:
                    name = m.group(1).strip().strip("*`. ")
                    break
            m = re.search(r"\*\*Rank / grade:\*\*\s*\*?\*?([^\n*(.]+)", t)
            if m:
                rank = m.group(1).strip()
            # SELECTED FOR THE NEXT ONE IS PART OF WHO SHE IS. The badge read
            # only the grade line, so it said CAPT -- accurate, and
            # incomplete, which is the wrong side to err on for the one line
            # on the page that states her identity. Jason, 2026-09-07:
            # "that's not her title she a Major Select."
            #
            # Read from the profile rather than hardcoded, so the day the
            # promotion-status line is removed the badge stops saying it
            # without anybody remembering to come back here.
            if re.search(r"\*\*Promotion status:\*\*.*?SELECT", t,
                         re.I | re.S):
                selected = True
            break
    except Exception:  # noqa: BLE001
        pass
    if name:
        bits = [b for b in name.replace(",", " ").split() if b]
        if len(bits) >= 2:
            name = f"{bits[-1]}, {' '.join(bits[:-1])}"
    else:
        name = (user.get("display_name") or user.get("username") or "")
        name = name.split("@")[0].replace(".", " ").replace("_", " ")
    for full, ab in (("Lieutenant Colonel", "LT COL"), ("Second Lieutenant", "2D LT"),
                     ("First Lieutenant", "1ST LT"), ("Major", "MAJ"),
                     ("Captain", "CAPT"), ("Colonel", "COL")):
        if rank.lower().startswith(full.lower()):
            rank = ab
            break
    rank = (rank or "").upper().strip() or "USAF"
    # "(MAJ-SEL)" is how the Air Force writes a selectee, and it disappears
    # on its own: when the profile's grade line becomes Major and the
    # promotion-status line goes, this reads MAJ · NURSE CORPS with nothing
    # else edited. The DRAFTS still say Capt Foster for work done as a
    # Captain -- that is a separate, deliberate rule, and the badge saying
    # who she is now does not change who she was then.
    if selected and not rank.startswith("MAJ"):
        rank = f"{rank} (MAJ-SEL)"
    return name.upper(), rank + " · NURSE CORPS"


@app.get("/jacket", response_class=HTMLResponse)
def jacket_page(request: Request, msg: str = ""):
    """The service jacket. See templates/jacket.html for the design notes.

    RANK IS READ, NOT ASSUMED. It comes from the profile knowledge file if
    it is there. Printing a rank she does not hold at the top of her own
    record would be the single most embarrassing thing this page could do.
    """
    user = require_user(request)
    rows = milestones.listing()
    # NAME AND RANK COME FROM THE PROFILE, NOT FROM HER LOGIN.
    # This printed "person2" across the top of a service jacket --
    # the local part of her email address. The profile carries
    # "Name: Zanetta Owner" and "Rank / grade: Major (O-4)", and a jacket
    # is labelled SURNAME, FORENAME, so that is what it now says.
    name, rank = _jacket_identity(user)
    nxt = [a for a in awards.listing()
           if a.get("my_status") in ("chasing", "submitted")][:5]
    return templates.TemplateResponse(request, "jacket.html", {
        "root": config.ROOT_PATH, "site_name": config.SITE_NAME, "user": user,
        "milestones": rows, "total": len(rows), "span": milestones.spans(),
        "kinds": milestones.KINDS, "suggestions": milestones.suggestions(),
        "next_up": nxt, "rank": rank, "name": name, "msg": msg,
        "starter": milestones.starter_gaps(),
        # WHAT IS ASKING FOR HER ATTENTION, as pills at the top of the
        # page. Both kinds are the same thing from her side -- a small,
        # specific thing only she can answer -- so they sit together.
        "gap_rows": gaps.find_all(limit=60),
        "lanes": milestones.lanes(),
        # THE ROAD MAP. What stands between her and the next award, as a
        # checklist of countable things rather than a percentage nothing
        # here could honestly produce -- see roadmap.py.
        "road": roadmap.readiness(),
        "measures": roadmap.measures_missing(),
        "calendar": roadmap.calendar(),
        "questions": _open_questions(),
    })


@app.post("/jacket/add")
def jacket_add(request: Request, when: str = Form(""), title: str = Form(""),
               kind: str = Form("other"), detail: str = Form(""),
               until: str = Form("")):
    user = require_user(request)
    try:
        milestones.add(user["username"], when, title, kind, detail,
                       until=until)
    except ValueError as e:
        return RedirectResponse(
            f"{config.ROOT_PATH}/jacket?msg=" + quote_plus(str(e)),
            status_code=303)
    return RedirectResponse(f"{config.ROOT_PATH}/jacket", status_code=303)


@app.post("/jacket/{mid}/delete")
def jacket_delete(request: Request, mid: int):
    require_user(request)
    db.milestone_delete(mid)
    return RedirectResponse(f"{config.ROOT_PATH}/jacket", status_code=303)


@app.get("/api/jacket")
def api_jacket(request: Request):
    require_user(request)
    return {"milestones": milestones.listing(), "span": milestones.spans()}


@app.get("/api/targets")
def api_targets_list(request: Request):
    """What she is aiming at, for Hermes and anything else that asks."""
    require_user(request)
    rows = [a for a in awards.listing() if a.get("my_status")]
    if not rows:
        rows = [a for a in awards.listing() if a["kind"] == "target"][:6]
    return {"targets": rows}


@app.post("/api/remember")
def api_remember(request: Request, fact: str = Form(""), where: str = Form("note")):
    """Record something learned about her career, from anywhere.

    THIS IS WHAT "HERMES REMEMBERS THINGS ABOUT HER" MEANS HERE, and the
    shape is deliberate: Hermes keeps no memory of its own. A fact learned
    in conversation is written into HER record, where it persists, where
    she can see it, and where the portal, the exports, ChatGPT and the
    next conversation all read the same copy. A memory only one service
    holds is a memory she cannot correct.

    ALWAYS A DRAFT. Something said in passing is not the same as something
    she has decided belongs in her record, and the difference matters when
    the record feeds a real package.
    """
    user = require_user(request)
    fact = (fact or "").strip()
    if len(fact.split()) < 3:
        raise HTTPException(400, "That is too short to be worth keeping.")
    entry = {
        "title": fact[:90],
        "category": "note",
        "situation": fact,
        "status": "draft",
        "note": f"Remembered from a conversation via {where[:30]}.",
    }
    new_id = db.portfolio_add(user["username"], entry, source_kind="hermes")
    portfolio.mirror()
    return {"id": new_id, "status": "draft",
            "note": "Saved as a draft in her record for her to confirm."}


# --- follow-up questions on an entry: spoken, one at a time -----------------
#
#  Her own protocol file calls this "the highest-value thing you do", and
#  it was wired only to the job path -- the one door she has stopped
#  using. Everything she creates now comes in through dictation or a
#  photographed document, and neither asked her anything.

@app.get("/api/entry/{entry_id}/followups")
def api_followups(request: Request, entry_id: int, make: int = 0):
    """The questions for one entry. make=1 generates them if there are none."""
    require_user(request)
    if not db.portfolio_get(entry_id):
        raise HTTPException(404, "No such entry.")
    qs = followups.get(entry_id)
    if not qs and make:
        try:
            system, _ = worker.build_system_prompt()
        except Exception:  # noqa: BLE001
            system = ""
        qs = followups.generate(entry_id, system_prompt=system)
    return {"entry_id": entry_id, "questions": qs,
            "answered": sum(1 for q in qs if q.get("answer"))}


# DEFINED BEFORE THE {index} ROUTE, DELIBERATELY. FastAPI matches in
# definition order, so with this second the path /followups/apply was
# matched by /followups/{index}, "apply" failed to parse as an int, and
# the call 422'd -- which looked like the fold-in silently doing nothing.
@app.post("/api/entry/{entry_id}/followups/apply")
def api_followups_apply(request: Request, entry_id: int):
    """Fold her answers back into the entry."""
    require_user(request)
    try:
        system, _ = worker.build_system_prompt()
    except Exception:  # noqa: BLE001
        system = ""
    return followups.fold_in(entry_id, system_prompt=system)


@app.post("/api/entry/{entry_id}/followups/{index}")
async def api_followup_answer(request: Request, entry_id: int, index: int,
                              audio: Optional[UploadFile] = File(None),
                              text: str = Form("")):
    """One answer, typed or spoken.

    SPOKEN IS THE POINT. The moment she can answer these is usually the
    moment her hands are full -- driving, between shifts. Her own protocol
    says a question must be answerable "in one line while standing in a
    hallway", and a text box is not that.
    """
    require_user(request)
    said = (text or "").strip()
    if audio is not None and audio.filename:
        config.ensure_dirs()
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", audio.filename)[-60:] or "a.webm"
        dest = config.UPLOAD_DIR / f"fu-{int(time.time())}-{secrets.token_hex(3)}-{safe}"
        dest.write_bytes(await audio.read())
        try:
            said = llm.transcribe(dest).strip()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"Could not make out that answer: {e}")
    if not said:
        raise HTTPException(400, "Nothing came through.")
    qs = followups.answer(entry_id, index, said)
    return {"heard": said, "questions": qs,
            "answered": sum(1 for q in qs if q.get("answer"))}


@app.get("/api/entry/{entry_id}/followups/{index}/speak")
def api_followup_speak(request: Request, entry_id: int, index: int):
    """Read one question aloud.

    Cached by the words themselves, so hearing a question twice -- which
    she will, in a car -- costs nothing the second time.
    """
    require_user(request)
    qs = followups.get(entry_id)
    if not (0 <= index < len(qs)):
        raise HTTPException(404, "No such question.")
    said = llm.speak_cached(qs[index]["ask"], config.OUTPUT_DIR)
    if not said:
        raise HTTPException(502, "The voice service did not answer.")
    return {"audio": f"{config.ROOT_PATH}/said/{said.name}",
            "ask": qs[index]["ask"]}


# --- the [NEEDED:] markers, as things she fills in ---------------------------
#
#  Jason: "make the input fields rather than text boxes so that she can
#  note that these needs input". Every marker is a place a model refused
#  to invent, which makes it the most actionable thing in her record --
#  one sentence from her turns a true entry into a submittable one.

@app.get("/api/gaps")
def api_gaps(request: Request):
    """Every gap across her record, for the jacket pills and the badge."""
    require_user(request)
    rows = gaps.find_all()
    return {"entries": rows, "total": sum(len(r["gaps"]) for r in rows)}


@app.post("/api/gaps/fill")
def api_gap_fill(request: Request, entry_id: int = Form(...),
                 field: str = Form(...), marker: str = Form(...),
                 value: str = Form(...)):
    """Fill one gap. A string replacement, deliberately -- see gaps.fill."""
    require_user(request)
    try:
        r = gaps.fill(entry_id, field, marker, value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    portfolio.mirror()
    return r


# --- the vent, and the workbook ----------------------------------------------
#
#  Jason: "when she's talking, don't allow any negative talk about what's
#  going on. allow that just to be rant ... a separate spreadsheet or word
#  document that is just for ranting or distractions."
#
#  See vent.py for why this is what makes the rest of the portal usable
#  rather than exhausting to talk to.

@app.get("/vent", response_class=HTMLResponse)
def vent_page(request: Request):
    user = require_user(request)
    return templates.TemplateResponse(request, "vent.html", {
        "root": config.ROOT_PATH, "site_name": config.SITE_NAME, "user": user,
        "entries": vent.listing(user["username"], limit=60),
    })


@app.post("/vent/add")
def vent_add(request: Request, text: str = Form(""), mood: str = Form("")):
    user = require_user(request)
    try:
        vent.add(user["username"], text, mood)
    except ValueError:
        pass
    return RedirectResponse(f"{config.ROOT_PATH}/vent", status_code=303)


@app.post("/vent/{vent_id}/delete")
def vent_delete(request: Request, vent_id: int):
    require_user(request)
    vent.remove(vent_id)
    return RedirectResponse(f"{config.ROOT_PATH}/vent", status_code=303)


@app.post("/api/vent/{vent_id}/look")
def api_vent_look(request: Request, vent_id: int):
    """Offer a fact hiding in a rant. Saves nothing by itself.

    A complaint often carries a real scope line -- "no handover since the
    move and I'm covering two elements" is leadership scope wearing a
    grievance. This offers it; she decides.
    """
    user = require_user(request)
    row = next((v for v in vent.listing(user["username"], limit=200)
                if v["id"] == vent_id), None)
    if not row:
        raise HTTPException(404, "Not found.")
    try:
        system, _ = worker.build_system_prompt()
    except Exception:  # noqa: BLE001
        system = ""
    return vent.look_for_a_fact(row["text"], system_prompt=system)


@app.post("/api/vent/{vent_id}/keep")
def api_vent_keep(request: Request, vent_id: int, fact: str = Form(...)):
    """Take one offered fact into the record, as a draft. Her decision."""
    user = require_user(request)
    fact = (fact or "").strip()
    if len(fact.split()) < 3:
        raise HTTPException(400, "Too short to keep.")
    new_id = db.portfolio_add(user["username"], {
        "title": fact[:90], "category": "note", "situation": fact,
        "status": "draft",
        "note": "You mentioned this while writing something else. Kept "
                "because it is a fact about your work -- nothing else from "
                "that page came with it."},
        source_kind="vent")
    portfolio.mirror()
    return {"id": new_id, "status": "draft"}


@app.get("/workbook.xlsx")
def workbook_file(request: Request):
    """The running workbook: Summary, Log, and a sheet per award."""
    require_user(request)
    config.ensure_dirs()
    path = config.OUTPUT_DIR / "career-workbook.xlsx"
    try:
        workbook.build(path)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return FileResponse(
        path, filename="career-workbook.xlsx",
        media_type="application/vnd.openxmlformats-officedocument."
                   "spreadsheetml.sheet")


@app.get("/export/{kind}")
def export(request: Request, kind: str, session: str = ""):
    """A file, always. No credentials, no network, nothing to configure --
    which is why this is the path that is guaranteed to work."""
    require_user(request)
    if kind not in EXPORT_KINDS:
        raise HTTPException(404, "unknown format")
    name, media, writer = EXPORT_KINDS[kind]
    config.ensure_dirs()
    path = writer(config.OUTPUT_DIR / name, session=session)
    return FileResponse(path, filename=path.name, media_type=media)


@app.post("/export/google")
def export_google(request: Request, session: str = Form("")):
    """Push into the shared Doc and Sheet, when a service account exists."""
    require_user(request)
    ok, msg = exports.google_sync(session=session)
    return JSONResponse({"ok": ok, "message": msg},
                        status_code=200 if ok else 409)


@app.get("/manifest.webmanifest")
def manifest():
    """Lets Android/iOS install this as a real home-screen app with its own icon."""
    r = config.ROOT_PATH
    return JSONResponse({
        "name": config.SITE_NAME, "short_name": "Career",
        # OPENS ON /talk, not the dashboard. The whole point of the
        # installed app is that she can say something the moment it
        # occurs to her -- one tap to the thing that listens, not one
        # tap to a list of jobs she then has to navigate out of.
        "start_url": f"{r}/talk", "scope": f"{r}/",
        "display": "standalone", "background_color": "#f6f7f9",
        "theme_color": "#1f5f9e",
        "icons": [{"src": f"{r}/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": f"{r}/static/icon-512.png", "sizes": "512x512", "type": "image/png",
                   "purpose": "any maskable"}],
    }, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    """Exists so Android will offer "Install app", and caches NOTHING.

    A service worker is the one hard requirement for the install prompt
    beyond the manifest -- without a fetch handler registered, Chrome
    treats the page as an ordinary site and never offers the home-screen
    install. So this registers one and passes every request straight
    through.

    Caching is deliberately absent. Her portal shows a record that is
    edited from a phone, a browser and now Telegram; a page served from
    a cache made before this morning's entry is worse than a page that
    needs a signal.
    """
    return Response('self.addEventListener("fetch", function (e) {});\n',
                    media_type="application/javascript")


@app.get("/healthz")
def healthz():
    return {"ok": True}


# --- admin -------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, msg: str = ""):
    user = require_admin(request)
    kb_text, kb_version = llm.load_knowledge()
    return templates.TemplateResponse(request, "admin.html", {
        "request": request, "root": config.ROOT_PATH, "site_name": config.SITE_NAME, "user": user, "msg": msg,
        "users": db.list_users(), "events": db.recent_events(120),
        "status": desktop.status().to_dict(),
        "kb_files": [(p.name, len(p.read_text(encoding='utf-8', errors='replace')))
                     for p in llm.knowledge_files()],
        "kb_version": kb_version, "kb_chars": len(kb_text),
        "models": llm.available_models(), "config": {
            "desktop_ip": config.DESKTOP_IP, "desktop_mac": config.DESKTOP_MAC,
            "model": config.OLLAMA_MODEL, "num_ctx": config.OLLAMA_NUM_CTX,
            "auto_wake": config.AUTO_WAKE, "auto_sleep": config.AUTO_SLEEP,
            "idle_minutes": config.IDLE_SLEEP_MINUTES, "public_host": config.PUBLIC_HOST}})


@app.post("/admin/wake")
def admin_wake(request: Request):
    require_admin(request)
    ok = desktop.send_wol()
    return RedirectResponse(
        config.ROOT_PATH + "/admin?msg=" + ("Magic+packet+sent" if ok else "Wake+failed+-+check+the+log"),
        status_code=303)


@app.post("/admin/sleep")
def admin_sleep(request: Request):
    require_admin(request)
    ok, msg = desktop.hibernate()
    return RedirectResponse(f"{config.ROOT_PATH}/admin?msg={'OK:+' if ok else 'Failed:+'}{msg.replace(' ', '+')[:80]}",
                            status_code=303)


