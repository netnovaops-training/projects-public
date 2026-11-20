"""Recording that survives a bad signal, a locked phone, and a toddler.

Jason, 2026-09-06: "she may also maybe in a place where the audio may
interrupted from the server. I would like it cashed on her device and
then resume even if the browser is in the backgrounded ... and as well to
cut out information that is not related to her career. like if she
suddenly has to stop and ask is the water boiling? I don't want that in
her jacket."

THIS SUPERSEDES A DELIBERATE DECISION, so the reasoning is worth keeping.
talk.html says in a comment block: no in-app recording, because her phone
keyboard's dictation button is instant and needs no upload. That was
right for asking a question. It is wrong for this: keyboard dictation
stops the moment the screen locks, cannot be paused while she deals with
a child, and nobody dictates five minutes of a quarter's work into a
text field while driving. Different job, different tool.

WHY CHUNKS, AND WHY THEY ARE IDEMPOTENT
Audio arrives as numbered chunks, each stored under its own index. Upload
the same index twice and the second write simply replaces the first. That
one property is what makes retrying safe: a phone that loses signal
mid-chunk, retries, and succeeds has no way of knowing whether the first
attempt landed -- and with idempotent writes it does not need to know.
Anything that appended instead would silently double a few seconds of
audio every time the signal wavered.

NOTHING IS ASSEMBLED UNTIL SHE SAYS SO. finish() is explicit. A session
that stops halfway keeps every chunk it got, so she can come back to it
rather than losing the drive home.

THE WATER-BOILING PROBLEM
After transcription a model splits the text into passages and marks which
ones are about her work. It MARKS them; it does not remove them. Two
reasons: it will sometimes be wrong, and a transcript that quietly loses
a sentence is worse than one that shows a sentence she can delete. She
taps to drop them, which takes a second and is a decision she made.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from . import config, db, llm

ROOT = config.DATA_DIR / "dictation"
MAX_CHUNK = 12 * 1024 * 1024          # one chunk; the client sends far less
MAX_CHUNKS = 4000                     # ~5.5 hours at 5s a chunk
_SAFE_ID = re.compile(r"^[a-f0-9]{12,32}$")


class DictateError(Exception):
    """Shown to her."""


def _dir(sid: str) -> Path:
    if not _SAFE_ID.match(sid or ""):
        raise DictateError("That is not a recording I know about.")
    return ROOT / sid


def start(username: str, mime: str = "audio/webm") -> dict:
    sid = uuid.uuid4().hex[:16]
    d = _dir(sid)
    (d / "chunks").mkdir(parents=True, exist_ok=True)
    meta = {"id": sid, "username": username, "mime": mime,
            "started": time.time(), "chunks": {}, "finished": False,
            "transcript": "", "segments": []}
    _save(sid, meta)
    return meta


def _save(sid: str, meta: dict) -> None:
    (_dir(sid) / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def meta(sid: str) -> dict:
    p = _dir(sid) / "meta.json"
    if not p.exists():
        raise DictateError("That recording is not here any more.")
    return json.loads(p.read_text(encoding="utf-8"))


def put_chunk(sid: str, index: int, data: bytes) -> dict:
    """Store one chunk. Writing the same index twice is fine and expected.

    See this module's header: idempotence is what makes a retry safe on a
    phone that cannot tell whether its last attempt landed.
    """
    if not (0 <= index < MAX_CHUNKS):
        raise DictateError("That chunk number is out of range.")
    if len(data) > MAX_CHUNK:
        raise DictateError("That chunk is too large.")
    m = meta(sid)
    if m.get("finished"):
        raise DictateError("That recording is already finished.")
    # Write then rename, so a connection dropped mid-write never leaves a
    # half-written chunk that looks complete.
    d = _dir(sid) / "chunks"
    tmp = d / f"{index:05d}.part"
    tmp.write_bytes(data)
    tmp.rename(d / f"{index:05d}.bin")
    m["chunks"][str(index)] = len(data)
    m["updated"] = time.time()
    _save(sid, m)
    return {"index": index, "bytes": len(data), "have": len(m["chunks"])}


def have(sid: str) -> list:
    """Which chunk numbers the server holds.

    The client asks this on reconnect and sends only what is missing --
    which is the difference between resuming a drive home and uploading it
    again from the start.
    """
    return sorted(int(i) for i in meta(sid).get("chunks", {}))


def assemble(sid: str) -> Path:
    m = meta(sid)
    d = _dir(sid)
    have_idx = sorted(int(i) for i in m.get("chunks", {}))
    if not have_idx:
        raise DictateError("Nothing was recorded.")
    ext = "webm" if "webm" in (m.get("mime") or "") else "m4a"
    out = d / f"recording.{ext}"
    with open(out, "wb") as fh:
        for i in have_idx:
            p = d / "chunks" / f"{i:05d}.bin"
            if p.exists():
                fh.write(p.read_bytes())
    return out


def finish(sid: str) -> dict:
    """Assemble, transcribe, and split into passages she can prune."""
    m = meta(sid)
    path = assemble(sid)
    m["finished"] = True
    m["bytes"] = path.stat().st_size
    _save(sid, m)
    try:
        text = llm.transcribe(path)
    except Exception as e:  # noqa: BLE001
        db.log_event("error", "dictate", f"transcription failed: {e}")
        m["error"] = f"Could not transcribe that: {e}"
        _save(sid, m)
        return m
    m["transcript"] = text
    m["segments"] = segment(text)
    m["transcribed"] = time.time()
    _save(sid, m)
    return m


def set_segments(sid: str, segments: list) -> dict:
    """Her edits. She is the authority on her own transcript."""
    m = meta(sid)
    clean = []
    for s in segments[:400]:
        if not isinstance(s, dict):
            continue
        clean.append({"text": str(s.get("text") or "")[:4000],
                      "keep": bool(s.get("keep", True)),
                      "why": str(s.get("why") or "")[:200]})
    m["segments"] = clean
    m["edited"] = time.time()
    _save(sid, m)
    return m


def kept_text(sid: str) -> str:
    segs = meta(sid).get("segments") or []
    if not segs:
        return meta(sid).get("transcript", "")
    return "\n\n".join(s["text"].strip() for s in segs
                       if s.get("keep") and s.get("text", "").strip())


def discard(sid: str) -> None:
    shutil.rmtree(_dir(sid), ignore_errors=True)


# ---------------------------------------------------------------------------
#  Splitting the water-boiling out
# ---------------------------------------------------------------------------

SEGMENT_SYSTEM = """You SPLIT a raw dictation into passages. Splitting is the
job. Deciding whether the whole thing is work-related is NOT the job.

A nurse officer recorded this while living her life -- driving, cooking, with
children in the room. It runs together: a sentence about her unit, then a
word to a child, then back again, with no pauses to mark it.

SPLIT AT EVERY CHANGE OF WHO SHE IS TALKING TO OR WHAT SHE IS TALKING ABOUT.
The moment she stops addressing her notes and speaks to somebody in the room
-- a child, a partner, a driver -- that is a new passage, however short, even
mid-sentence. Then when she returns to her notes, that is another one.

Then mark each passage:
  keep=true   about her work, training, patients, unit, studies, or anything
              that could appear in a career record
  keep=false  anything else: telling a child off, the kettle, a shopping
              list, directions, a false start

WORKED EXAMPLE. Input:

  "In March I audited 60 charts and 22 were missing entries. No, put that
  down right now. I said no. So we built a charting aid and rolled it out
  to 34 nurses."

Correct output -- THREE passages, not one:

  {"segments": [
    {"text": "In March I audited 60 charts and 22 were missing entries.",
     "keep": true, "why": ""},
    {"text": "No, put that down right now. I said no.",
     "keep": false, "why": "Speaking to a child in the room."},
    {"text": "So we built a charting aid and rolled it out to 34 nurses.",
     "keep": true, "why": ""}
  ]}

Returning that as ONE passage marked keep=true is the failure this exists to
prevent. It would put a child being told off into an official award package.

RULES
- Do NOT rewrite her words. Split them, nothing else. Every passage's text
  must appear in the input exactly as given.
- Every word of the input must appear in exactly one passage. Losing a
  sentence is worse than keeping a dull one.
- When you genuinely cannot tell, keep it. She can drop it in one tap; she
  cannot recover something you dropped for her.
- Speech transcribed in a car is imperfect. A garbled passage that seems
  work-related is kept.

Reply as JSON only:
{"segments": [{"text": "...", "keep": true, "why": ""}]}
"""


def segment(text: str) -> list:
    """Passages, marked. Falls back to keeping everything.

    A failure here must never cost her the transcript -- she gets one
    block she can edit by hand, which is exactly where she was before
    this feature existed.
    """
    text = (text or "").strip()
    if not text:
        return []
    # SKIP ONLY WHEN THERE IS GENUINELY NOTHING TO SPLIT.
    #
    # This used to skip anything under 200 characters, to save a model
    # call. That was exactly backwards: a quick note dictated in a car is
    # ALWAYS under 200 characters, and it is the one most likely to be
    # interrupted. Caught by the case Jason named -- "No! Put that down
    # right now" landed in a 150-character transcript, the shortcut fired,
    # and the telling-off went straight through to her record.
    #
    # A single sentence has nothing to separate, so that is the only case
    # worth short-circuiting. Anything with a second sentence gets looked
    # at, and one model call is cheap next to a child's name in a package.
    if len(re.findall(r"[.!?]+", text)) < 2 and len(text) < 120:
        return [{"text": text, "keep": True, "why": ""}]
    try:
        answer, _model = llm.ask(SEGMENT_SYSTEM, text, temperature=0.0)
        data = llm.extract_json(answer)
        segs = (data or {}).get("segments") or []
        out = []
        for s in segs:
            t = str((s or {}).get("text") or "").strip()
            if t:
                out.append({"text": t, "keep": bool(s.get("keep", True)),
                            "why": str(s.get("why") or "").strip()})
        # SAFETY NET: if the model dropped more than a fifth of the words,
        # do not trust the split at all. Silently losing a sentence of her
        # dictation is the one failure that makes this feature not worth
        # having, so the whole transcript comes back as one passage
        # instead and she edits it herself.
        if out:
            kept_words = sum(len(s["text"].split()) for s in out)
            if kept_words >= len(text.split()) * 0.8:
                return out
            db.log_event("warn", "dictate",
                         f"segmenting lost {len(text.split()) - kept_words} "
                         "words -- returning the transcript whole")
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "dictate", f"could not segment: {e}")
    return [{"text": text, "keep": True, "why": ""}]
