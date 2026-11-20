"""Background job pipeline: wake desktop -> transcribe -> draft -> extract gaps.

Runs as a daemon thread inside the portal process so the whole thing is one
systemd unit. Also owns the idle-hibernate timer.
"""
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import backup, config, db, desktop, llm, research

_stop = threading.Event()

MODES = {
    "log": "Log an accomplishment",
    "award": "Draft award package statements",
    "interview": "Board / interview prep",
}


def _now_local() -> datetime:
    try:
        return datetime.now(ZoneInfo(config.TIMEZONE))
    except Exception:
        return datetime.now()


# --- prompt construction -----------------------------------------------------

def _template_override() -> str:
    """An instance's own output template, if it ships one.

    Found by running a real upload through /ability before it was used: the
    knowledge base had been swapped for Jason but the output template had
    not, so his State IT record came back asking for the "echelon: unit /
    group / wing / MAJCOM". The knowledge base is per-instance; the shape of
    the answer was not.

    If `KNOWLEDGE_DIR/_template.md` exists, its contents replace the `log`
    template. Absent -- which is Casey's case -- nothing changes at all, so
    this cannot alter her drafts by accident.

    The leading underscore keeps it out of `knowledge_files()`, which globs
    `*.md` into the system prompt. Without that the template would be
    concatenated into the prompt as well as used as the template, and the
    model would see the instructions twice.
    """
    try:
        p = config.KNOWLEDGE_DIR / "_template.md"
        if p.is_file():
            t = p.read_text(encoding="utf-8").strip()
            if len(t) > 80:            # a stub or an empty file is not a template
                return t
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "template", f"could not read _template.md: {e}")
    return ""


TASK_PROMPTS = {
    "log": """\
TASK: LOG AN ACCOMPLISHMENT

Turn the raw input below into one structured accomplishment record for the
running career log. Do not invent facts. Where a number, date, or name is
missing, write `[NEEDED: ...]` rather than guessing.

Output EXACTLY this markdown structure and nothing else:

### {date} — <short title, max 10 words>

**What happened (plain language):**
<2-4 sentences, plain English, no jargon>

**Action:** <what she personally did>
**Scope:** <who/what was affected, with counts if known, and the echelon: patient / shift / unit / squadron / group / wing / MAJCOM>
**Impact:** <the measurable or observable effect>
**Result / outcome:** <the higher-level mission or clinical outcome enabled>

**Draft performance statement (narrative, past tense, active voice):**
<ONE standalone sentence in AF Form 1206 performance-statement style. Third person, using EXACTLY the name and rank given in the profile section above -- do not substitute a different rank or surname, and do not promote her. Must contain at least one number. If no number is available, write the sentence with a `[NEEDED: number]` placeholder inline.>

**Category fit:** <which 1206 category this best supports>
**Awards this could feed:** <name specific awards from the awards catalog, or "none yet — needs more scope">
**Evidence to keep:** <what document, log, report, or person can verify this>
**Confidence:** <High / Medium / Low — Low if the input was vague>
""",
    "award": """\
TASK: DRAFT AWARD PACKAGE STATEMENTS

Target award: {award_target}

Using the raw input below plus anything in the profile, draft competitive
AF Form 1206 narrative performance statements. Follow the format rules in the
core rules file exactly: standalone complete sentences, past tense, active
voice, third person, NO bullet characters, NO acronym legend, at least one
number per statement.

Output EXACTLY this markdown structure and nothing else:

## Draft statements — {award_target}
_Generated {date}. VERIFY every number before submission._

### <CATEGORY HEADING 1>
<statement 1>

<statement 2>

### <CATEGORY HEADING 2>
<statement>

## Scope check
For each statement above, state the highest echelon it credibly reaches and
whether that is verified or assumed.

## Weak spots
List any statement that is missing a number, missing an outcome, or stops at
the individual/shift level, and say exactly what is needed to fix it.
""",
    "interview": """\
TASK: BOARD / INTERVIEW PREP

Using the raw input and the profile, generate promotion-board and award-board
preparation material.

Output EXACTLY this markdown structure and nothing else:

## Board prep — {date}

### Likely questions
<5 questions a board would realistically ask a field grade officer in this role>

### Suggested answer frames
<for each question, a 3-4 line answer skeleton built ONLY from facts present in the input or profile; mark anything she still needs to supply as [NEEDED: ...]>

### Her three strongest talking points right now
<3 items, each with the specific evidence that backs it>

### What is thin
<honest assessment of where her record is weakest for this board, and the single highest-leverage thing she could do in the next 90 days>
""",
}

FOLLOWUP_PROMPT = """\
You just produced the draft below from the user's raw notes.

Your job now is to find what is MISSING — the specific facts that would make
this materially stronger for an Air Force award or promotion board, and that
only she can supply.

Ask between 3 and 7 questions. Rules for the questions:
- Every question must be answerable in one or two sentences by her.
- At least TWO questions must probe LEADERSHIP scope: who she directed,
  influenced, mentored, or whose work she changed, and at what echelon.
- At least TWO questions must probe QUANTIFICATION: a count, a dollar figure,
  a percentage with its baseline, a time saved, or a volume.
- At least ONE question must probe ADDITIONAL DUTIES OR VOLUNTEER WORK she
  held at the same time -- awards monitor, unit training manager, safety
  representative, mentoring, a base or community programme she ran. Ask what
  she was responsible for ALONGSIDE this, and for how long. She will not
  raise these herself: they are the things done on top of the actual job, so
  they read to her as background rather than as achievements. They are also
  the eligibility gates for most of the awards she is chasing, which is the
  opposite of background. Skip this only if the draft already names one.
- At least ONE question must probe whether the impact travelled upward: was it
  adopted, published, briefed to leadership, codified, or copied elsewhere.
- Never ask something the draft already answers.
- Never ask for patient names, dates of birth, medical record numbers, or any
  other PHI. Never ask for classified or CUI operational detail.
- Plain English. She is a busy clinician, not a personnel specialist.

Return ONLY a JSON array of strings. No preamble, no markdown fences, no keys.
Example: ["How many nurses did you personally train on the new protocol?", "..."]

DRAFT:
---
{draft}
---
"""


def build_system_prompt() -> tuple[str, str]:
    kb, version = llm.load_knowledge()
    if not kb:
        kb = ("(No knowledge files found. Behaviour is undefined and output should "
              "not be trusted. Populate the knowledge directory.)")
    system = (
        "You are the career documentation assistant described in the knowledge base below. "
        "The knowledge base is authoritative: follow its rules over your own habits.\n\n"
        "ABSOLUTE RULES:\n"
        "1. Never invent a fact, number, date, name, or award. If you do not have it, "
        "write [NEEDED: <what is missing>].\n"
        "2. Never output protected health information. If the input contains a patient "
        "name, date of birth, or medical record number, replace it with [PHI REMOVED] "
        "and note this at the top of your output.\n"
        "3. Never output anything that looks classified or CUI. Flag it instead.\n"
        "4. Follow the output structure you are given exactly. No preamble, no sign-off, "
        "no offers of further help.\n\n"
        "===== KNOWLEDGE BASE =====\n" + kb + "\n===== END KNOWLEDGE BASE =====\n"
    )
    return system, version


# --- PHI safety net ----------------------------------------------------------

_PHI_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN REMOVED]"),
    (re.compile(r"\bMRN[:\s#]*\d+\b", re.I), "[MRN REMOVED]"),
    (re.compile(r"\bmedical record (?:number|#)[:\s]*\d+\b", re.I), "[MRN REMOVED]"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b(?=\s*(?:DOB|date of birth))", re.I), "[DOB REMOVED]"),
    (re.compile(r"\b(?:DOB|date of birth)[:\s]*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", re.I), "[DOB REMOVED]"),
]


def scrub_phi(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    for pattern, replacement in _PHI_PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n:
            hits.append(replacement.strip("[]"))
    return text, hits


# --- pipeline ----------------------------------------------------------------

def process_job(job) -> None:
    job_id = job["id"]

    def progress(msg: str) -> None:
        db.update_job(job_id, progress=msg)

    # 1. Make sure the GPU box is awake.
    st = desktop.status()
    if not st.ready:
        if not config.AUTO_WAKE:
            raise RuntimeError("Desktop is asleep and auto-wake is disabled.")
        db.update_job(job_id, status="waking", progress="Waking the desktop...")
        st = desktop.wake_and_wait(on_progress=progress)
        if not st.ready:
            raise RuntimeError(
                f"Desktop never came up (Ollama={'up' if st.ollama else 'down'}, "
                f"Whisper={'up' if st.whisper else 'down'}). Check Wake-on-LAN settings "
                f"and that both services are set to start automatically.")

    # 2. Get text -- transcribe audio, extract from a document, or use the note.
    source_text = (job["note"] or "").strip()
    stored = Path(job["stored_path"]) if job["stored_path"] else None

    if job["kind"] == "audio" and stored and stored.exists():
        db.update_job(job_id, status="transcribing",
                      progress="Transcribing audio on the desktop GPU...")
        transcript = llm.transcribe(stored)
        if not transcript:
            raise RuntimeError("Transcription came back empty. Is the recording audible?")
    elif job["kind"] == "document" and stored and stored.exists():
        db.update_job(job_id, status="transcribing", progress="Reading document...")
        transcript = llm.extract_text(stored)
    else:
        transcript = source_text

    transcript, phi_hits = scrub_phi(transcript)
    if phi_hits:
        db.log_event("warn", f"job:{job_id}", f"PHI patterns scrubbed: {', '.join(phi_hits)}")

    combined = transcript
    if source_text and job["kind"] != "text":
        combined = f"{transcript}\n\n--- Her typed note ---\n{source_text}"
    if job["answers"]:
        combined += f"\n\n--- Her answers to earlier follow-up questions ---\n{job['answers']}"

    db.update_job(job_id, transcript=transcript)

    # NO INPUT, NO DRAFT. THIS IS NOT A CONVENIENCE CHECK.
    #
    # Job 1 was a SCANNED award citation. pypdf found no text layer and
    # returned an empty string, and the model was then handed nothing and
    # asked for a career entry. It produced one: a complete, plausible,
    # entirely fabricated account of implementing QBL calculators in
    # labour and delivery -- unit, training, impact, a draft performance
    # statement -- written into her append-only career log under her name,
    # attributed to a rank she does not hold.
    #
    # Nothing downstream could have caught that. It reads exactly like a
    # real entry, and the only reason it was found is that Jason knew she
    # had never done it.
    #
    # A model given nothing will always produce something. The only place
    # to stop it is here, before it is asked.
    # WHICH FAILURE WAS IT. The extractors report their own errors as
    # bracketed strings -- "[Unsupported document type]", "[Could not read
    # PDF: ...]" -- so a file that could not be OPENED and a file with no
    # TEXT IN IT both arrive here looking the same: short. They need
    # opposite advice, and getting it wrong sent Jason to OCR a PDF that was
    # never a scan (2026-09-07). If the extractor left a bracketed complaint,
    # repeat it instead of guessing.
    stripped = combined.strip()
    if stripped.startswith("[") and len(combined.split()) < 12:
        raise RuntimeError(
            f"That file could not be opened at all: {stripped}\n\n"
            "This is not the same as a scan with no text in it -- running it "
            "through OCR will not help. It usually means the file is not the "
            "type its name says, or it arrived damaged. Try uploading it "
            "again, or open it and re-save it as a PDF first.\n\n"
            "Nothing was drafted: a model handed an error message will write "
            "around it and that would go into your record under your name.")

    if len(combined.split()) < 12:
        raise RuntimeError(
            "There was nothing readable in that. It came back with "
            f"{len(combined.split())} words, which is not enough to write "
            "anything true from.\n\n"
            "If it was a scan or a photo, the text has to be read off the "
            "page first -- upload it under Documents instead, which runs it "
            "through the archive's OCR.\n\n"
            "Nothing was drafted, deliberately: a model handed an empty "
            "page will invent a plausible one, and that would go into your "
            "record under your name.")

    # 3. Draft.
    db.update_job(job_id, status="drafting", progress="Drafting with the local model...")
    system, kb_version = build_system_prompt()
    mode = job["mode"] if job["mode"] in TASK_PROMPTS else "log"
    # An instance may ship its own output shape -- see _template_override().
    # Only the default `log` mode is overridable; the specialised modes stay
    # as they are until something needs otherwise.
    _tpl = _template_override() if mode == "log" else ""
    # DATE THE ENTRY BY THE DOCUMENT, NOT BY THE UPLOAD. This passed
    # _now_local() until 2026-09-07, so her 2023 Commendation Medal was
    # written up as "07 Sep 2026" -- the day she happened to upload it. A
    # career record sorted by filing date tells you the order she got round
    # to things, which is not a fact anybody wants.
    #
    # document_date() tries the file's own creation metadata first, then a
    # photograph's capture date, then a date written on the page, and only
    # then today. Whichever it used is logged, so a wrong date can be found
    # later rather than looking deliberate.
    # `job` is a sqlite3.Row: it indexes by column name but has NO .get().
    # The first version used .get() and every job failed outright with an
    # AttributeError -- a date lookup taking down the whole draft, which is
    # exactly backwards for something that has a perfectly good fallback.
    _stored = job["stored_path"] if "stored_path" in job.keys() else ""
    if _stored:
        _doc_date, _date_src = llm.document_date(Path(_stored), combined)
    else:
        _doc_date, _date_src = _now_local().date(), "today (no file on this job)"
    db.log_event("info", f"job:{job_id}", f"dated from {_date_src}: {_doc_date}")
    task = (_tpl or TASK_PROMPTS[mode]).format(
        date=_doc_date.strftime("%d %b %Y"),
        award_target=job["award_target"] or "Field Grade Officer of the Quarter",
    )
    user_msg = f"{task}\n\n===== RAW INPUT =====\n{combined}\n===== END RAW INPUT =====\n"
    # ask(), NOT chat(). chat() goes straight to Ollama and skips the whole
    # Claude -> Gemini -> house-model chain, which is why every draft this
    # portal ever produced came from the local 8B even with a working Gemini
    # key in the environment (found 2026-09-07). This is the text that ends
    # up in her official record; it should have the best model available.
    draft, draft_model = llm.ask(system, user_msg)

    if phi_hits:
        draft = ("> **Heads up:** possible protected health information was detected in the "
                 "recording and automatically removed before drafting. Please re-record "
                 "without patient identifiers.\n\n") + draft

    # 4. Ask the model what she left out.
    db.update_job(job_id, draft=draft, progress="Working out what is missing...")
    followups: list[str] = []
    try:
        # The follow-ups move too. Asking a small local model for strict
        # JSON is exactly where it is weakest -- the four-branch fallback
        # parser below exists because of it.
        raw, _ = llm.ask(system, FOLLOWUP_PROMPT.format(draft=draft),
                         temperature=0.6)
        parsed = llm.extract_json(raw)
        if isinstance(parsed, list):
            followups = [str(q).strip() for q in parsed if str(q).strip()][:8]
        elif isinstance(parsed, dict):
            for value in parsed.values():
                if isinstance(value, list):
                    followups = [str(q).strip() for q in value if str(q).strip()][:8]
                    break
        if not followups:  # fall back to parsing a numbered/bulleted list
            followups = [
                re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"')
                for line in raw.splitlines()
                if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+\S", line)
            ][:8]
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", f"job:{job_id}", f"Follow-up generation failed: {e}")

    import json as _json
    db.update_job(job_id, status="done", progress="", followups=_json.dumps(followups),
                  # The model that ACTUALLY answered. This used to record
                  # OLLAMA_MODEL whatever happened, so the record agreed
                  # with itself and there was nothing to notice.
                  model_used=draft_model, kb_version=kb_version, error="")

    write_outputs(job_id)


def write_outputs(job_id: int) -> None:
    """Write a per-job markdown file and append to the rolling career log."""
    job = db.get_job(job_id)
    if not job:
        return
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(job["created_at"]).strftime("%Y-%m-%d_%H%M")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", job["orig_name"] or "note")[:60]
    per_job = config.OUTPUT_DIR / f"{stamp}_job{job_id}_{safe}.md"

    followups = db.jload(job["followups"], [])
    body = [
        f"# Job {job_id} — {job['orig_name']}",
        "",
        f"- Created: {datetime.fromtimestamp(job['created_at']).isoformat(timespec='seconds')}",
        f"- Mode: {job['mode']}   Target: {job['award_target'] or '-'}",
        f"- Model: {job['model_used']}   Knowledge base version: `{job['kb_version']}`",
        "",
        "## Draft",
        "",
        job["draft"] or "_(none)_",
        "",
        "## Follow-up questions",
        "",
    ]
    body += [f"{i}. {q}" for i, q in enumerate(followups, 1)] or ["_(none)_"]
    body += ["", "## Transcript", "", "```", job["transcript"] or "", "```", ""]
    per_job.write_text("\n".join(body), encoding="utf-8")

    log_path = config.OUTPUT_DIR / "career-log.md"
    if not log_path.exists():
        log_path.write_text(
            "# Career accomplishment log\n\n"
            "Append-only. Every entry was generated locally and must be fact-checked "
            "before it goes into an official package.\n",
            encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n\n---\n\n<!-- job {job_id} | kb {job['kb_version']} -->\n\n")
        fh.write(job["draft"] or "")
        fh.write("\n")


# --- loops -------------------------------------------------------------------

def job_loop() -> None:
    while not _stop.is_set():
        try:
            job = db.next_queued_job()
            if job:
                db.log_event("info", f"job:{job['id']}", f"Starting ({job['mode']})")
                try:
                    process_job(job)
                    db.log_event("info", f"job:{job['id']}", "Completed")
                except Exception as e:  # noqa: BLE001
                    db.update_job(job["id"], status="error", progress="",
                                  error=f"{type(e).__name__}: {e}")
                    db.log_event("error", f"job:{job['id']}",
                                 f"{e}\n{traceback.format_exc()[:1500]}")
                continue
        except Exception as e:  # noqa: BLE001
            db.log_event("error", "worker", f"Job loop error: {e}")
        _stop.wait(4)


def transcribe_loop() -> None:
    """Turn added recordings into text, one at a time, in the background.

    Its own loop rather than the job queue: a job DRAFTS something, which
    is a different and much longer errand than simply hearing what is on
    a tape. Keeping them apart means a queue of drafting work never
    delays a transcript, and a failed transcript never costs the audio.
    """
    while not _stop.is_set():
        try:
            rec = db.rec_next_queued()
            if rec:
                db.rec_update(rec["id"], status="working", error="")
                try:
                    text = llm.transcribe(Path(rec["stored_path"]))
                    db.rec_update(rec["id"], transcript=text, status="done",
                                  transcribed_at=time.time())
                    db.log_event("info", f"rec:{rec['id']}",
                                 f"Transcribed {len(text)} characters")
                except Exception as e:  # noqa: BLE001
                    db.rec_update(rec["id"], status="error",
                                  error=f"{type(e).__name__}: {e}")
                    db.log_event("error", f"rec:{rec['id']}",
                                 f"Transcription failed: {e}")
                continue
        except Exception as e:  # noqa: BLE001
            db.log_event("error", "worker", f"Transcribe loop error: {e}")
        _stop.wait(3)


def idle_loop() -> None:
    """Hibernate the desktop once it has been idle long enough."""
    while not _stop.is_set():
        _stop.wait(60)
        if _stop.is_set() or not config.AUTO_SLEEP:
            continue
        try:
            if db.active_job_count() > 0:
                continue
            idle_for = time.time() - db.last_activity_ts()
            if idle_for < config.IDLE_SLEEP_MINUTES * 60:
                continue
            st = desktop.status()
            if not (st.ollama or st.whisper or st.ssh):
                continue  # already down
            ok, msg = desktop.hibernate()
            db.log_event("info" if ok else "error", "idle",
                         f"Idle {int(idle_for / 60)} min -> hibernate: {msg}")
        except Exception as e:  # noqa: BLE001
            db.log_event("error", "idle", str(e))


# --- the background pass ------------------------------------------------------
#
#  TRIGGERED BY HER RECORD CHANGING, NOT BY A CLOCK. A scan against an
#  unchanged record costs a model call and can only reach the conclusion
#  it reached an hour ago. So the model half runs when something she owns
#  has actually changed since the last pass.
#
#  The CALENDAR half runs anyway, hourly, because a date can fall due
#  while she does nothing at all -- which is the entire failure this was
#  built to catch. It costs no model call, so running it on a timer is
#  free.
#
#  There is a deliberate quiet period after a change: she is usually mid-
#  sentence when the first save lands, and a scan fired on every keystroke
#  would spend four model calls on one entry she is still writing.

RESEARCH_SETTLE_SECONDS = 180
_last_scanned_change = 0.0


def research_loop() -> None:
    global _last_scanned_change
    while not _stop.is_set():
        _stop.wait(600)
        if _stop.is_set():
            continue
        try:
            changed = db.record_changed_at()
            settled = changed and (time.time() - changed) > RESEARCH_SETTLE_SECONDS
            fresh = changed > _last_scanned_change
            # Model half only when there is something new AND she has
            # stopped typing; calendar half every time round.
            use_model = bool(fresh and settled)
            system = ""
            if use_model:
                try:
                    system, _ = build_system_prompt()
                except Exception:  # noqa: BLE001
                    system = ""
            result = research.scan(system_prompt=system, use_model=use_model)
            if use_model:
                _last_scanned_change = changed
            if result["new"]:
                _notify(result["new"])
        except Exception as e:  # noqa: BLE001
            db.log_event("error", "research", str(e))


def _notify(new_count: int) -> None:
    """Tell her something new is waiting, on the one channel that reaches
    her without her opening a browser.

    The portal shows the count on its own; this is for the case that
    actually matters -- a deadline moving into range on a Tuesday while
    she is at work and not thinking about awards at all.

    Failure is logged and swallowed. A notification that cannot be sent
    must never take the scan down with it: the findings are already saved
    and the panel will show them the moment she looks.
    """
    if not getattr(config, "NOTIFY_URL", ""):
        return
    try:
        import httpx
        httpx.post(config.NOTIFY_URL,
                   json={"new": new_count,
                         "text": (f"{new_count} new thing"
                                  f"{'s' if new_count != 1 else ''} in your "
                                  "career portal — deadlines or matches "
                                  "against your record.")},
                   timeout=15)
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "research", f"could not notify: {e}")


BACKUP_EVERY_HOURS = 12
_last_backup = 0.0


def maintenance_loop() -> None:
    global _last_backup
    while not _stop.is_set():
        _stop.wait(3600)
        try:
            db.prune_events(keep_days=45)
        except Exception:
            pass
        # HER WHOLE RECORD IS ONE FILE ON ONE MACHINE. Twice a day, take a
        # copy that is actually coherent -- see backup.py's header for why
        # copying the file itself is not the same thing, and why that
        # matters far more than which tool moves it afterwards.
        try:
            if time.time() - _last_backup > BACKUP_EVERY_HOURS * 3600:
                backup.run()
                _last_backup = time.time()
        except Exception as e:  # noqa: BLE001
            db.log_event("error", "backup", str(e))


def start() -> None:
    for fn in (job_loop, transcribe_loop, idle_loop, maintenance_loop,
               research_loop):
        threading.Thread(target=fn, name=fn.__name__, daemon=True).start()


def stop() -> None:
    _stop.set()
