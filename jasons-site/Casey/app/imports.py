"""One upload, watched: archive, read, sort, file, write.

Jason, 2026-09-06: "give her a progress report of how long it's taking."

WHY THIS IS A JOB AND NOT A REQUEST
The old upload route did the whole chain inside the POST -- file to
Paperless, wait for OCR, call a model, write to her cloud -- and then
redirected. That is thirty to ninety seconds of a page doing nothing, on
a phone, with no way to tell a slow model from a broken one. On a bad
connection the browser gives up and she has no idea whether it worked.

So the upload now returns immediately with an id, and the work happens on
a thread that records what step it is on. She watches it.

THE STEPS ARE NAMED AFTER WHAT SHE CARES ABOUT, not after the containers
involved. She should never have to know that Paperless exists, which was
the point of the request.

FAILURES ARE PER-STEP AND DO NOT STOP THE REST. Filing can succeed while
the model is down; the model can work while her cloud is unreachable.
Each step records its own outcome, and the report says which parts
landed -- because "some of it worked" is the common case and one merged
error message hides it.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

from . import archive, db, followups, llm, portfolio, working

# id -> job. In memory on purpose: a progress bar has no value after a
# restart, and the RESULTS are all persisted elsewhere (Paperless, the
# portfolio, her document) by the time the job ends.
_JOBS: dict = {}
_LOCK = threading.Lock()

STEPS = [
    ("archive", "Filing it in your archive"),
    ("read", "Reading the text out of it"),
    ("sort", "Working out what belongs in your record"),
    ("record", "Saving drafts to your portfolio"),
    ("document", "Adding it to your working document"),
]


def _set(job_id: str, **fields) -> None:
    with _LOCK:
        j = _JOBS.get(job_id)
        if j:
            j.update(fields)


def get(job_id: str) -> dict:
    with _LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else {}


# WHOSE RECORD IS THIS. Jason, 2026-09-06: "I'm uploading documents but I
# want them seperate from Casey."
#
# The portal is hers. When somebody else signs in and uploads a document
# it was still being read into HER portfolio and appended to HER working
# document -- so his IT CV would have become an entry in her career
# record, attributed to her, in a file that feeds award packages.
#
# The uploader is now checked. Anyone who is not her gets the archive and
# the extraction and nothing else: no drafts in her record, no section in
# her document. Configured rather than hard-coded, so this does not have
# to be edited if she ever changes address.
OWNER = os.getenv("ZEE_OWNER", "person2@example.com").strip().lower()


def _is_hers(username: str) -> bool:
    return (username or "").strip().lower() == OWNER


def start(path: Path, title: str, username: str, sort: bool = True) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id, "title": title or path.name,
            "started": time.time(), "done": False, "step": "archive",
            "steps": {k: "waiting" for k, _ in STEPS},
            "notes": {}, "entries": 0, "doc_url": "", "error": "",
        }
    threading.Thread(target=_run, args=(job_id, path, title, username, sort),
                     daemon=True, name=f"import-{job_id}").start()
    return job_id


def _step(job_id: str, key: str, state: str, note: str = "") -> None:
    with _LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return
        j["steps"][key] = state
        if note:
            j["notes"][key] = note
        if state == "working":
            j["step"] = key


def _run(job_id: str, path: Path, title: str, username: str, sort: bool) -> None:
    text, filed = "", False
    try:
        # --- archive -------------------------------------------------------
        _step(job_id, "archive", "working")
        try:
            archive.file_document(path, title=title or path.name)
            filed = True
            _step(job_id, "archive", "done", "Filed and searchable.")
        except archive.ArchiveError as e:
            _step(job_id, "archive", "failed", str(e))

        # --- read ----------------------------------------------------------
        _step(job_id, "read", "working")
        try:
            text = llm.extract_text(path)
        except Exception as e:  # noqa: BLE001
            text = ""
            _step(job_id, "read", "failed", f"Could not open it: {e}")
        # A SCANNED PDF RETURNS NOTHING, NOT AN ERROR, AND THAT WAS THE BUG.
        #
        # This used to fall back to OCR only when the extractor returned a
        # bracketed message like "[Unsupported document type]" -- which is
        # what a PHOTO gets. A scanned PDF is different: pypdf opens it
        # happily, finds no text layer, and returns an empty string. So
        # startswith("[") was False, no OCR ran, and the next guard --
        # `not text.strip()` -- skipped sorting entirely and reported
        # nothing found.
        #
        # Caught on a real Meritorious Service citation (AF Form 2224B).
        # pypdf returned 0 characters; OCR returned 1,400 including a
        # 34-member team, 330K beneficiaries, 500 annual births, 287 complex
        # cases, diversions down 75% and $392K saved. Every quantifiable
        # figure in the document, silently dropped.
        #
        # So: anything THIN goes to OCR, not just anything bracketed. The
        # threshold is deliberately generous -- a real document has more
        # than a couple of dozen words, and a needless OCR pass costs a
        # second while a missed one costs the whole document.
        thin = len(text.split()) < 25
        if text.strip().startswith("[") or thin:
            _step(job_id, "read", "working",
                  "No text layer in it, so reading the page itself.")
            if filed:
                ocr, why = archive.text_for_file(path.name)
                if ocr and len(ocr.split()) > len(text.split()):
                    text = ocr
                elif not text.strip():
                    _step(job_id, "read", "failed", why)
            elif not text.strip():
                _step(job_id, "read", "failed",
                      "There is no text in it to read, and it could not be "
                      "archived, so there was nothing to read it with.")
        if text.strip():
            _step(job_id, "read", "done", f"{len(text.split())} words.")

        if not sort or not text.strip():
            for k in ("sort", "record", "document"):
                _step(job_id, k, "skipped")
            _set(job_id, done=True, finished=time.time())
            return

        # --- sort ----------------------------------------------------------
        _step(job_id, "sort", "working")
        try:
            system, _ = _system_prompt()
            found = archive.sort_into_record(text, system_prompt=system)
        except Exception as e:  # noqa: BLE001
            found = {}
            _step(job_id, "sort", "failed", str(e)[:150])
        entries = (found or {}).get("entries") or []
        if found:
            _step(job_id, "sort", "done",
                  f"Found {len(entries)} thing" + ("" if len(entries) == 1 else "s")
                  + " worth keeping." if entries
                  else "Nothing in it belongs in your record.")

        # --- record --------------------------------------------------------
        # SOMEBODY ELSE'S DOCUMENT STOPS HERE. It is archived and it has
        # been read, but it does not become an entry in her career record.
        if not _is_hers(username):
            for k in ("record", "document"):
                _step(job_id, k, "skipped",
                      "Not filed to her record -- this was not uploaded by her.")
            _set(job_id, done=True, finished=time.time(), not_hers=True)
            return
        _step(job_id, "record", "working")
        made, made_ids = 0, []
        for e in entries:
            quote = e.pop("quote", "")
            e["status"] = "draft"
            e["note"] = (f"From {path.name[:50]}"
                         + (f" ({found.get('kind')})" if found.get("kind") else "")
                         + (f". It says: {quote[:250]}" if quote else ""))
            try:
                made_ids.append(db.portfolio_add(username, e,
                                                 source_kind="document"))
                made += 1
            except Exception:  # noqa: BLE001
                pass
        if made:
            portfolio.mirror()
        # ASK HER THE QUESTIONS THE DRAFT COULD NOT ANSWER.
        # Her protocol file calls this "the highest-value thing you do",
        # and until now it ran only on the job path -- the one door she
        # has stopped using. A draft that comes back with [NEEDED: number]
        # in it is a question nobody was asking her.
        for eid in made_ids:
            try:
                followups.generate(eid, system_prompt=_system_prompt()[0])
            except Exception:  # noqa: BLE001
                pass
        _set(job_id, entries=made)
        _step(job_id, "record", "done" if made else "skipped",
              f"{made} draft{'' if made == 1 else 's'} saved." if made else "")

        # --- document ------------------------------------------------------
        _step(job_id, "document", "working")
        try:
            section = working.section_from_import(
                title or path.name, found.get("kind", ""),
                found.get("summary", ""), entries,
                quotes=text[:4000],
                # These were being dropped. The sorter has always returned
                # them and only `entries` was read -- so a transcript that
                # correctly yielded "S.T.A.B.L.E. instructor card" threw it
                # away. Credentials are pins; that is the material asked for.
                credentials=found.get("credentials") or [],
                dates=found.get("dates") or [])
            r = working.append(section)
            _set(job_id, doc_url=r["url"])
            _step(job_id, "document", "done", "Added to the end.")
        except working.WorkingError as e:
            _step(job_id, "document", "failed", str(e))
    except Exception as e:  # noqa: BLE001
        _set(job_id, error=str(e)[:200])
        db.log_event("error", "import", str(e))
    finally:
        _set(job_id, done=True, finished=time.time())


def _system_prompt():
    from . import worker
    try:
        return worker.build_system_prompt()
    except Exception:  # noqa: BLE001
        return "", ""
