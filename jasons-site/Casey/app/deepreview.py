"""The Claude tier, done the only way it honestly can be.

Jason wanted Claude first, then Gemini, then phi. Then: "we're using my
Claude code."

WHY THE CHAIN CANNOT SIMPLY CALL CLAUDE
Claude Code is an interactive tool tied to his own login on SuperNova. It
is not an API endpoint, there is no key in this stack (checked -- both
ANTHROPIC_API_KEY and ZEE_ANTHROPIC_API_KEY are empty and LiteLLM's
Claude entry is commented out), and a web request from a container has no
honest way to drive it. Pretending otherwise would leave a chain that
looks three deep and is two.

SO THE CLAUDE TIER IS A QUEUE, NOT A CALL
She marks something for a proper look -- a package about to be submitted,
an award she is unsure of, a draft that matters. It lands as a file in a
folder. Next time Jason is in Claude Code, the whole queue is sitting
there to be read and answered, and the answers come back into her portal.

THIS IS BETTER THAN AN API CALL WOULD HAVE BEEN, and not as a
consolation. An API tier would spend the good model on every routine
transcription. A queue spends it on the four things a quarter that decide
whether a package wins, which is where it is actually worth having.

A PLAIN FOLDER OF MARKDOWN, deliberately. It is bind-mounted to the repo
rather than living in a Docker volume, so Claude Code can read and write
it with ordinary file tools -- no docker exec, no API, no database
client. The queue is legible to a person with a text editor, which is the
property that makes it survivable.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

QUEUE = Path(os.getenv("ZEE_CLAUDE_QUEUE", "/claude-queue"))
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def available() -> bool:
    try:
        QUEUE.mkdir(parents=True, exist_ok=True)
        return QUEUE.is_dir()
    except Exception:  # noqa: BLE001
        return False


def _slug(s: str) -> str:
    return _SAFE.sub("-", (s or "item").strip())[:48].strip("-") or "item"


def ask(kind: str, title: str, body: str, question: str = "",
        username: str = "") -> dict:
    """Put one thing in the queue. Returns where it went."""
    if not available():
        raise RuntimeError("The review folder is not mounted.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{_slug(title)}.md"
    text = [
        f"# {title}", "",
        f"- Asked: {datetime.now().strftime('%d %B %Y, %H:%M')}",
        f"- Kind: {kind}",
        f"- By: {username or 'casey'}",
        "- Status: **waiting**", "",
        "## What she wants to know", "",
        (question.strip() or "A proper look at this before it goes anywhere."),
        "", "## The material", "", body.strip(), "",
        "---", "",
        "## Answer", "",
        "<!-- Claude Code: write the answer below this line. Anything here",
        "     is shown to her in the portal exactly as written, so address",
        "     her directly. Then change Status above to **answered**. -->",
        "",
    ]
    (QUEUE / name).write_text("\n".join(text), encoding="utf-8")
    return {"file": name, "path": str(QUEUE / name)}


_STATUS = re.compile(r"^- Status:\s*\*\*(\w+)\*\*", re.M)
_TITLE = re.compile(r"^#\s+(.+)$", re.M)
_ANSWER = re.compile(r"^## Answer\s*$(.*)\Z", re.M | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _read(p: Path) -> dict:
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return {}
    m = _ANSWER.search(t)
    answer = _COMMENT.sub("", m.group(1)).strip() if m else ""
    st = _STATUS.search(t)
    title = _TITLE.search(t)
    return {
        "file": p.name,
        "title": title.group(1).strip() if title else p.stem,
        # ANSWERED IS DECIDED BY THERE BEING AN ANSWER, not by the status
        # line. Forgetting to change a marker is the normal human outcome,
        # and an answer she never sees because of a missed edit is the one
        # failure this must not have.
        "status": "answered" if answer else (st.group(1) if st else "waiting"),
        "answer": answer,
        "when": p.stat().st_mtime,
    }


def listing(limit: int = 40) -> list:
    if not available():
        return []
    # Queued items are named <timestamp>-<slug>.md. Anything else in the
    # folder is documentation for whoever opens it, and the README was
    # showing up in her portal as a question waiting for an answer.
    files = [p for p in sorted(QUEUE.glob("*.md"), reverse=True)
             if re.match(r"^\d{8}-\d{6}-", p.name)]
    return [r for r in (_read(p) for p in files[:limit]) if r]


def waiting() -> int:
    return sum(1 for r in listing() if r["status"] != "answered")


def unseen_answers() -> list:
    return [r for r in listing() if r["status"] == "answered"]
