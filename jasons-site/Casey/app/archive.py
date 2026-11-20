"""A PDF goes two places at once: the archive, and her record.

Jason, 2026-09-06: "I wanted to be able to upload a PDF archive it and
have it stored with the dockers I already have ... use my llm to take that
information and sort that Information into a unified access."

THE ARCHIVE ALREADY EXISTED AND IS NOT A NEW CONTAINER
paperless-ngx has been running on the NUC for days, behind /paperless. It
does OCR, full-text search, tagging and retention already, and doing any
of that again here would be worse and duplicated. So the PDF is FILED
there, and what comes back here is the text and a link.

WHY A TOKEN AND NOT THE IDENTITY HEADER
Paperless is configured to trust X-Auth-Email as the remote user
(PAPERLESS_ENABLE_HTTP_REMOTE_USER). That works for a browser arriving
through Caddy, and it does NOT work from here -- posting with the header
from this container answered 401. There is an nginx sidecar in front of
Paperless that pins where that header may come from, which is exactly the
protection that makes the header safe to trust in the first place. Rather
than widen it so an app could impersonate a person, this uses her own API
token: identity Paperless can verify by itself.

The token is HERS, and everything filed with it belongs to her account.
It is not an admin token, and it cannot see anybody else's documents --
checked: created with documents permissions only.

TWO DESTINATIONS, ONE UPLOAD, AND NEITHER BLOCKS THE OTHER
Filing can succeed while extraction fails, or the reverse. They are
reported separately, because "your PDF is safe but I could not read it"
and "I read it but it is not archived" are different problems with
different fixes, and collapsing them into one error message helps nobody.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

from . import config, db, llm

BASE = os.getenv("ZEE_PAPERLESS_URL", "http://192.168.1.86:8000").rstrip("/")
TOKEN = os.getenv("ZEE_PAPERLESS_TOKEN", "").strip()
PUBLIC = os.getenv("ZEE_PAPERLESS_PUBLIC",
                   "https://example.org/paperless").rstrip("/")
TIMEOUT = float(os.getenv("ZEE_PAPERLESS_TIMEOUT", "120"))


class ArchiveError(Exception):
    """Filing failed. The message is shown to her."""


def configured() -> bool:
    return bool(TOKEN)


def _headers() -> dict:
    return {"Authorization": f"Token {TOKEN}"}


def file_document(path: Path, title: str = "", tags: list | None = None) -> dict:
    """Put one file into Paperless. Returns what it can be found by.

    Paperless consumes asynchronously -- the POST returns a task id, not a
    document id, and the document appears when OCR finishes. So this does
    not pretend to hand back a document id it does not have; it returns
    the task and the place to look.
    """
    if not configured():
        raise ArchiveError(
            "The document archive is not set up yet (no ZEE_PAPERLESS_TOKEN).")
    if not path.is_file():
        raise ArchiveError("That file is not there any more.")
    data = {}
    if title:
        data["title"] = title[:120]
    try:
        with open(path, "rb") as fh:
            r = httpx.post(f"{BASE}/api/documents/post_document/",
                           headers=_headers(),
                           files={"document": (path.name, fh)},
                           data=data, timeout=TIMEOUT)
    except httpx.RequestError as e:
        raise ArchiveError(f"Could not reach the archive ({e.__class__.__name__}).")
    if r.status_code >= 400:
        raise ArchiveError(f"The archive refused it ({r.status_code}): "
                           f"{r.text[:200]}")
    task = (r.text or "").strip().strip('"')
    db.log_event("info", "archive", f"filed {path.name} -> task {task[:20]}")
    return {"task": task, "where": f"{PUBLIC}/documents",
            "note": "Filed. It appears in the archive once the text has been "
                    "read out of it, usually within a minute."}


def recent(limit: int = 20) -> list:
    """Her documents, newest first. [] if the archive cannot be reached."""
    if not configured():
        return []
    try:
        r = httpx.get(f"{BASE}/api/documents/",
                      headers=_headers(),
                      params={"page_size": limit, "ordering": "-created"},
                      timeout=30)
        if r.status_code != 200:
            return []
        out = []
        for d in (r.json().get("results") or []):
            out.append({
                "id": d.get("id"),
                "title": d.get("title") or "(untitled)",
                "created": (d.get("created") or "")[:10],
                "url": f"{PUBLIC}/documents/{d.get('id')}/details",
            })
        return out
    except Exception:  # noqa: BLE001 -- the archive being down is not an error here
        return []


# ---------------------------------------------------------------------------
#  Reading it into her record
# ---------------------------------------------------------------------------

SORT_SYSTEM = """You are reading a document a nurse officer uploaded to her own
career portal, and deciding what in it belongs in her record.

WHAT THIS DOCUMENT COULD BE
A performance report, an award citation or nomination, a certificate, a
training record, a decoration, a CV, a policy she wrote, a QI report.

WHAT TO PULL OUT
Only things SHE did or holds. Accomplishments, credentials, dates, measurable
results, and who else was affected.

WHAT NOT TO
- Anything about other people, even if named in the document.
- Boilerplate, letterhead, distribution lists, form instructions.
- Anything you infer. If the document does not say it, it is not there.
- Never invent a number, date, unit or scope. Where the document gives no
  number, leave it empty -- an empty field is a prompt for her to fill in; an
  invented one goes into a real package under her name.
- Her Master's is IN PROGRESS unless this document explicitly says it was
  conferred. Never upgrade it.

Return JSON only:
{"kind": "what this document is, in a few words",
 "summary": "two sentences at most",
 "entries": [{"title": "", "happened_on": "", "situation": "", "task": "",
              "action": "", "result": "", "evidence": "", "skills": "",
              "quote": "the document's own words for the main claim"}],
 "credentials": ["any certification or qualification it evidences"],
 "dates": ["any date that matters, with what it is"]}
At most 5 entries. Empty list is a fine answer.
"""


def sort_into_record(text: str, system_prompt: str = "") -> dict:
    """Read a document's text and say what belongs in her record.

    Everything it produces is a DRAFT. A document is evidence of what it
    says, not a decision about what belongs in a promotion package -- that
    decision is hers.
    """
    if not (text or "").strip():
        return {}
    system = ((system_prompt + "\n\n" + SORT_SYSTEM)
              if system_prompt else SORT_SYSTEM)
    try:
        answer, model = llm.ask(system, text[:60000], temperature=0.1)
        data = llm.extract_json(answer)
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "archive", f"could not sort the document: {e}")
        return {}
    if not isinstance(data, dict):
        return {}
    entries = []
    for e in (data.get("entries") or [])[:5]:
        if isinstance(e, dict) and str(e.get("title") or "").strip():
            entries.append({k: str(e.get(k) or "").strip() for k in
                            ("title", "happened_on", "situation", "task",
                             "action", "result", "evidence", "skills", "quote")})
    return {
        "kind": str(data.get("kind") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "entries": entries,
        "credentials": [str(c) for c in (data.get("credentials") or [])][:10],
        "dates": [str(d) for d in (data.get("dates") or [])][:10],
        "model": model,
    }


def text_for_file(filename: str, timeout: float = 90.0) -> tuple[str, str]:
    """Wait for Paperless to finish reading a file, then take its text.

    Returns (text, why_not). Matched by FILENAME, not by task id, and that
    is not a shortcut -- it is the only thing that works here.

    post_document hands back a task UUID; the task list's `id` is a
    numeric row id instead, and ?task_id= filters to nothing whichever
    value is passed. Three attempts went that way before the list was
    actually printed. The upload route already gives every file a unique
    name (doc-<unixtime>-<hex>-<original>), which comes back in the task's
    input_data, cannot collide with another upload, and does not care what
    the id field is called this version.

    WHY THIS EXISTS AT ALL. The portal's own extractor reads txt, docx and
    pdf, so a PHOTO of a document came back "[Unsupported document type]"
    while Paperless had just OCR'd it correctly. Adding tesseract here
    would be a second, worse copy of an engine already running.

    Short poll on purpose: both test files were read in about a second. A
    long wait here is a page that hangs.
    """
    if not configured() or not filename:
        return "", "The archive is not connected."
    deadline = time.time() + timeout
    doc_id = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/api/tasks/", headers=_headers(), timeout=20)
            if r.status_code == 200:
                rows = r.json()
                rows = rows if isinstance(rows, list) else rows.get("results") or []
                for t in rows:
                    if filename not in str(t.get("input_data") or ""):
                        continue
                    status = (t.get("status") or "").upper()
                    if status in ("SUCCESS", "SUCCEEDED"):
                        ids = t.get("related_document_ids")
                        doc_id = (ids[0] if isinstance(ids, list) and ids
                                  else t.get("related_document"))
                        break
                    if status in ("FAILURE", "FAILED"):
                        return "", ("The archive could not read that file: "
                                    + str(t.get("result_data")
                                          or t.get("result") or "")[:200])
            if doc_id:
                break
        except httpx.RequestError:
            return "", "Could not reach the archive while it was reading."
        time.sleep(2)
    if not doc_id:
        return "", ("Archived, but still being read. The text will be in the "
                    "archive shortly -- nothing was drafted from it yet.")
    try:
        r = httpx.get(f"{BASE}/api/documents/{doc_id}/", headers=_headers(),
                      timeout=30)
        if r.status_code != 200:
            return "", f"Could not read the archived document ({r.status_code})."
        return (r.json().get("content") or "").strip(), ""
    except httpx.RequestError:
        return "", "Could not reach the archive."
