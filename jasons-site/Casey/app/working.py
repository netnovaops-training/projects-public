"""Her working document: one file she keeps, that everything writes into.

Jason, 2026-09-06: "instead of going directly to the different docker
containers to do it automatically for her ... parse the information and
directly imported into a working document for her and keep a record of it
... she then continues using the working document to keep working out of
and can be able to export that information back into chat[G]PT if she
wishes to."

THE POINT IS THAT SHE NEVER VISITS A CONTAINER
Today a document touches Paperless, the portal's database and her
portfolio, and she would have to know that to find anything. This makes
one file the place she works, and everything else feeds it behind her.

WHY MARKDOWN AND NOT .docx
Nextcloud edits .md live and collaboratively in its Text app -- the same
in-browser, several-people-at-once editing a .docx gets from Collabora --
AND it survives a round trip through a chat window. A .docx pasted into
ChatGPT is not a document, it is a zip. She asked to be able to take this
back out to ChatGPT, so the format has to be one that can leave.

APPEND, NEVER REWRITE
Every import adds a dated section at the end. Nothing already in the file
is touched, because she is editing it at the same time -- possibly at the
same moment, on a phone. A tool that rewrites a document somebody is
typing in is a tool that eats an afternoon's work exactly once and is
never trusted again.

AN APP PASSWORD, NOT HERS
The credential is a Nextcloud app password: revocable from her own
settings page without changing her login, and it cannot sign in to the
web UI. If this app is ever compromised, the blast radius is her files
over WebDAV, and she can end it herself in two clicks.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

import httpx

BASE = os.getenv("ZEE_NEXTCLOUD_URL", "http://nextcloud:80").rstrip("/")
USER = os.getenv("ZEE_NEXTCLOUD_USER", "casey").strip()
APPPASS = os.getenv("ZEE_NEXTCLOUD_APPPASS", "").strip()
PUBLIC = os.getenv("ZEE_NEXTCLOUD_PUBLIC",
                   "https://cloud.home.example.net").rstrip("/")
FOLDER = os.getenv("ZEE_WORKING_FOLDER", "Career")
DOCNAME = os.getenv("ZEE_WORKING_DOC", "Working document.md")
TIMEOUT = 60.0


class WorkingError(Exception):
    """Shown to her. Never a stack trace."""


def configured() -> bool:
    return bool(APPPASS)


def _auth():
    return (USER, APPPASS)


def _dav(path: str = "") -> str:
    return f"{BASE}/remote.php/dav/files/{USER}/{path.lstrip('/')}"


def public_url() -> str:
    """Where she opens it. The Text app edits .md live and collaboratively."""
    from urllib.parse import quote
    return f"{PUBLIC}/apps/files/?dir=/{quote(FOLDER)}"


def ensure_folder() -> None:
    if not configured():
        raise WorkingError("Her cloud is not connected yet "
                           "(no ZEE_NEXTCLOUD_APPPASS).")
    try:
        r = httpx.request("MKCOL", _dav(FOLDER), auth=_auth(), timeout=TIMEOUT)
        # 201 created, 405 already there. Both fine.
        if r.status_code not in (201, 405):
            raise WorkingError(f"Could not make the {FOLDER} folder "
                               f"({r.status_code}).")
    except httpx.RequestError as e:
        raise WorkingError(f"Could not reach her cloud ({e.__class__.__name__}).")


def read() -> str:
    """The document as it stands. '' when it does not exist yet."""
    if not configured():
        return ""
    try:
        r = httpx.get(_dav(f"{FOLDER}/{DOCNAME}"), auth=_auth(), timeout=TIMEOUT)
        return r.text if r.status_code == 200 else ""
    except httpx.RequestError:
        return ""


HEADER = f"""# Career working document

This is yours. Everything you upload lands here, and you can edit it
straight in the browser or on your phone -- it saves as you type.

Nothing above your own writing is ever rewritten by the portal. New
material is added at the end, dated, so you can see what arrived and
when.

---
"""


def append(section: str) -> dict:
    """Add a dated section at the end. Creates the file on first use.

    READ, APPEND, WRITE rather than a WebDAV PATCH, because Nextcloud's
    PATCH support varies by version and a half-supported partial write on
    a document she is editing is not a risk worth taking for one round
    trip saved.
    """
    if not configured():
        raise WorkingError("Her cloud is not connected yet.")
    ensure_folder()
    current = read()
    if not current.strip():
        current = HEADER
    body = current.rstrip("\n") + "\n\n" + section.strip() + "\n"
    try:
        r = httpx.put(_dav(f"{FOLDER}/{DOCNAME}"), auth=_auth(),
                      content=body.encode("utf-8"),
                      headers={"Content-Type": "text/markdown; charset=utf-8"},
                      timeout=TIMEOUT)
        if r.status_code not in (200, 201, 204):
            raise WorkingError(f"Could not save to her cloud ({r.status_code}).")
    except httpx.RequestError as e:
        raise WorkingError(f"Could not reach her cloud ({e.__class__.__name__}).")
    return {"bytes": len(body), "url": public_url(), "doc": DOCNAME}


def section_from_import(title: str, kind: str, summary: str,
                        entries: list, quotes: str = "",
                        credentials: list | None = None,
                        dates: list | None = None) -> str:
    """One import, written the way she will want to read it later.

    ENTRIES ARE WRITTEN AS PROMPTS, NOT AS FACTS. Where the source gave no
    number the line says so in words she can act on, because a blank looks
    finished and an empty field does not get filled in.
    """
    when = datetime.now().strftime("%d %B %Y, %H:%M")
    out = [f"## {title}", "",
           f"*Added {when}" + (f" — from {kind}" if kind else "") + ".*", ""]
    if summary:
        out += [summary.strip(), ""]
    if entries:
        out.append("### What this looks like for your record")
        out.append("")
        for e in entries:
            out.append(f"**{e.get('title') or '(untitled)'}**")
            if e.get("happened_on"):
                out.append(f"- When: {e['happened_on']}")
            for f, label in (("situation", "Situation"), ("task", "Task"),
                             ("action", "Action"), ("result", "Result"),
                             ("evidence", "Evidence")):
                v = (e.get(f) or "").strip()
                if v:
                    out.append(f"- {label}: {v}")
                elif f == "result":
                    out.append("- Result: **needs a number** — how much, how "
                               "many, over what period?")
                elif f == "evidence":
                    out.append("- Evidence: **who could confirm this?**")
            out.append("")
    # CREDENTIALS ARE PINS AND WERE BEING THROWN AWAY.
    #
    # sort_into_record has always returned `credentials` and `dates`
    # alongside `entries`, and only `entries` was read. Caught on a real
    # chat transcript: it correctly found "S.T.A.B.L.E. instructor card"
    # and the import silently discarded it. That is the exact material
    # Jason asked for help with -- a credential is a Whole Airman line,
    # and an instructor card is a bullet.
    if credentials:
        out += ["### Credentials this mentions", ""]
        out += [f"- {c}" for c in credentials]
        out += ["", "*Add these to the matching award file under Awards, "
                    "with the date you got them and when they renew — the "
                    "renewal window is the thing that gets missed.*", ""]
    if dates:
        out += ["### Dates it mentions", ""]
        out += [f"- {d}" for d in dates]
        out += ["", "*Confirm any of these you are going to rely on.*", ""]
    if quotes:
        out += ["<details><summary>The original words</summary>", "",
                quotes.strip()[:4000], "", "</details>", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
#  Taking it back out
# ---------------------------------------------------------------------------

_DETAILS = re.compile(r"<details>.*?</details>", re.S)


def for_chatgpt() -> str:
    """The document as something she can paste straight into a chat.

    The collapsed "original words" blocks are stripped: they are raw
    transcript she already has, they are the bulk of the file, and pasting
    them back into a chat spends her context on material the model has
    seen. What is left is her record and her own writing.
    """
    text = read()
    if not text.strip():
        return ""
    text = _DETAILS.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return (
        "Here is my career working document. I keep it in my own portal and "
        "edit it there, so please work FROM it rather than rewriting it "
        "wholesale — if you suggest changes, say which section they belong "
        "in.\n\n"
        "Two things to hold on to: never state my Master's as finished, it "
        "is in progress; and never widen the scope of anything below — a "
        "unit-level result described as service-wide is what gets a package "
        "returned.\n\n"
        "---\n\n" + text.strip() + "\n"
    )
