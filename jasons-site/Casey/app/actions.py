"""The door ChatGPT comes in through.

Jason, 2026-09-06: "the ability to connect chatgpt to the Google docs
database and webhook and API to pull info to give history and breath ...
so she can either chat and chat[G]PT or use my sessions."

WHAT THIS IS
A small, token-authenticated HTTP surface that a ChatGPT **custom GPT
Action** can call. She creates a GPT once, points it at /casey/actions, and
from then on the ChatGPT she already pays for can read her record, read
an award file, write her progress, and add to her log -- and every one of
those lands in the SAME rows the website and the Telegram bot use.

WHY IT IS NOT BEHIND THE HOUSEHOLD SSO
Every other app here sits behind Caddy's forward_auth. That cannot work
for this: OpenAI's servers make the call, not her browser, and they have
no session cookie and cannot complete an interactive sign-in. So this
router carries its own bearer token and is exempted in the Caddyfile.

THAT EXEMPTION IS THE WHOLE SECURITY STORY, SO IT IS NARROW ON PURPOSE
  - One token, in ZEE_ACTION_TOKEN. No token set = the router refuses
    everything, rather than defaulting to open. A half-configured door is
    worse than a closed one because it looks shut.
  - Compared with hmac.compare_digest, not ==, so a wrong token cannot be
    guessed a character at a time by timing the reply.
  - The verbs are enumerated below and there is no general query, no SQL,
    no file read outside knowledge/awards, and nothing that deletes.
  - Every write records via="chatgpt", so when a number looks wrong the
    first question -- which door did this come in through -- has an answer.

WHAT IT DELIBERATELY WILL NOT DO
Read her ChatGPT history. That is not possible from here and no amount of
API design changes it: an OpenAI API key grants access to models, not to a
person's conversations. Her history comes in through the export file --
see chatgpt.py.
"""
from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import awards, config, db, portfolio, render

router = APIRouter(prefix="/actions", tags=["actions"])


def _check(authorization: str | None) -> None:
    token = (config.ACTION_TOKEN or "").strip()
    if not token:
        # Closed, not open. See the header.
        raise HTTPException(
            503, "The action API is not configured on this server.")
    given = (authorization or "")
    if given.lower().startswith("bearer "):
        given = given[7:]
    if not hmac.compare_digest(given.strip(), token):
        raise HTTPException(401, "Bad token.")


class TargetUpdate(BaseModel):
    award_id: str
    status: str | None = None
    next_action: str | None = None
    notes: str | None = None
    owner_note: str | None = None
    deadline_note: str | None = None


class LogEntry(BaseModel):
    title: str
    situation: str | None = ""
    task: str | None = ""
    action: str | None = ""
    result: str | None = ""
    evidence: str | None = ""
    skills: str | None = ""
    happened_on: str | None = ""
    award_target: str | None = ""


@router.get("/awards")
def list_awards(authorization: str | None = Header(None)):
    """Every award and promotion, with her current progress on each."""
    _check(authorization)
    return {"awards": awards.listing()}


@router.get("/awards/{award_id}")
def one_award(award_id: str, authorization: str | None = Header(None)):
    """One award: what it is, how its output must be written, where she is."""
    _check(authorization)
    a = awards.get(award_id)
    if not a:
        raise HTTPException(404, "No such award.")
    return {
        "id": award_id, "name": a["name"], "tier": a["tier"],
        "kind": a["status"], "format": a.get("format", ""),
        "gate": a.get("gate", ""), "blocked_on": a.get("blocked_on", ""),
        "reference": a.get("body", ""),
        "writing_rules": render.format_guidance(award_id),
        "my_progress": db.target_get(award_id),
        "markdown": awards.export_markdown(award_id),
    }


@router.post("/awards/{award_id}/progress")
def set_progress(award_id: str, body: TargetUpdate,
                 authorization: str | None = Header(None)):
    """Record progress. Lands in the same row the website reads."""
    _check(authorization)
    if award_id not in awards.all_awards():
        raise HTTPException(404, "No such award.")
    fields = {k: v for k, v in body.model_dump().items()
              if k != "award_id" and v is not None}
    if not fields:
        raise HTTPException(400, "Nothing to change.")
    if "status" in fields and fields["status"] not in awards.STATUSES:
        raise HTTPException(
            400, f"status must be one of: {', '.join(awards.STATUSES)}")
    return {"saved": db.target_set(award_id, via="chatgpt", username="casey",
                                   **fields)}


@router.get("/record")
def read_record(limit: int = 40, authorization: str | None = Header(None)):
    """Her portfolio, so ChatGPT can answer from what she has actually done."""
    _check(authorization)
    return {"entries": db.portfolio_list(limit=min(limit, 200)),
            "progress": portfolio.progress_lines()}


@router.post("/record")
def add_record(body: LogEntry, authorization: str | None = Header(None)):
    """Add an entry from a ChatGPT conversation.

    Saved as a DRAFT, always. Something said in passing in a chat is not
    the same as something she has decided belongs in her record, and the
    difference matters when the record feeds a real package.
    """
    _check(authorization)
    entry = body.model_dump()
    entry["status"] = "draft"
    entry["note"] = "Added from ChatGPT."
    new_id = db.portfolio_add("casey", entry, source_kind="chatgpt",
                              model="chatgpt-action")
    portfolio.mirror()
    return {"id": new_id, "status": "draft",
            "note": "Saved as a draft for her to confirm."}


@router.get("/draft/{award_id}")
def draft_for(award_id: str, authorization: str | None = Header(None)):
    """Her record written in one award's required register."""
    _check(authorization)
    from . import worker
    try:
        system, _ = worker.build_system_prompt()
    except Exception:  # noqa: BLE001
        system = ""
    return render.draft(award_id, system_prompt=system)


@router.get("/findings")
def read_findings(authorization: str | None = Header(None)):
    """Deadlines and matches found by the background pass."""
    _check(authorization)
    return {"unseen": db.findings_unseen_count(),
            "findings": db.findings_list(limit=40)}
