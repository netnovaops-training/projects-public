"""The [NEEDED:] markers, as things she can fill in rather than read.

Jason, 2026-09-06: "on the NEEDED: parts make the input fields rather
than text boxes so that she can note that these needs input and that
these can be more accurate if she does this everyday to track changes."

WHY THE MARKERS ARE THE MOST ACTIONABLE THING IN HER RECORD
Every one of them is a place a model refused to invent. "training
[NEEDED: number] staff" is not a defect -- it is the system correctly
declining to make a figure up, and it marks the exact spot where one
sentence from her turns a true entry into a submittable one.

Rendered as prose they read as damage. Rendered as an input box beside
the sentence they read as a form with three blanks left, which is a
thing a person finishes.

WHY REPLACEMENT IS SURGICAL
Filling a gap rewrites ONLY that marker, by exact string, in one field.
It does not re-run a model over the entry. A model asked to "update this
with the number" will also tidy the grammar, and quietly change a word
she chose -- and she will not notice, because she was looking at the
number. Her words stay hers.
"""
from __future__ import annotations

import re

from . import db

FIELDS = ("title", "situation", "task", "action", "result", "evidence",
          "skills", "note")

# [NEEDED: number] / [NEEDED - who confirms this?] / [FILL IN] / [CONFIRM: ...]
MARKER = re.compile(r"\[(NEEDED|FILL IN|CONFIRM|VERIFY)\s*[:\-–]?\s*([^\]]*)\]",
                    re.I)


def find(entry: dict) -> list:
    """Every gap in one entry, with enough context to answer it.

    The CONTEXT is what makes it answerable. "number" on its own is not a
    question; "training [number] staff" is, and she can answer it without
    opening anything else.
    """
    out = []
    for field in FIELDS:
        text = (entry.get(field) or "")
        for m in MARKER.finditer(text):
            asks = (m.group(2) or "").strip() or "this"
            start, end = m.span()
            before = text[max(0, start - 60):start].strip()
            after = text[end:end + 60].strip()
            out.append({
                "field": field,
                "marker": m.group(0),
                "asks": asks,
                "before": ("…" + before) if start > 60 else before,
                "after": (after + "…") if len(text) > end + 60 else after,
                "kind": m.group(1).upper(),
            })
    return out


def find_all(limit: int = 200) -> list:
    """Every gap across her whole record, newest entries first."""
    out = []
    for e in db.portfolio_list(limit=limit):
        g = find(e)
        if g:
            out.append({"entry_id": e["id"], "title": e["title"] or "(untitled)",
                        "status": e["status"], "gaps": g})
    return out


def count() -> int:
    return sum(len(r["gaps"]) for r in find_all())


def fill(entry_id: int, field: str, marker: str, value: str) -> dict:
    """Replace one marker with what she typed. Nothing else changes.

    NO MODEL RUNS HERE, and that is the point. Asked to "put the number
    in", a model also tidies the grammar and swaps a word she chose --
    and she will not catch it, because she was looking at the number.
    This is a string replacement in one field.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("Nothing was entered.")
    if field not in FIELDS:
        raise ValueError("That is not a field on an entry.")
    entry = db.portfolio_get(entry_id)
    if not entry:
        raise ValueError("No such entry.")
    text = entry.get(field) or ""
    if marker not in text:
        # Already filled, or filled from somewhere else since the page
        # loaded. Saying so is better than silently doing nothing.
        raise ValueError("That gap is not there any more — it may already "
                         "have been filled.")
    db.portfolio_update(entry_id, **{field: text.replace(marker, value, 1)})
    left = len(find(db.portfolio_get(entry_id)))
    return {"field": field, "value": value, "remaining": left,
            "text": (db.portfolio_get(entry_id).get(field) or "")}


_SPLIT = re.compile(r"(\[(?:NEEDED|FILL IN|CONFIRM|VERIFY)\s*[:\-–]?\s*[^\]]*\])",
                    re.I)


def segments(text: str) -> list:
    """Split a field into prose and gaps, so a template can render inputs.

    Returns [{"kind": "text"|"gap", ...}] in order. Doing this here rather
    than in Jinja keeps the regex in one place -- the template already has
    the same marker written into it once, and two copies of a regex is one
    too many.
    """
    out = []
    for part in _SPLIT.split(text or ""):
        if not part:
            continue
        m = MARKER.fullmatch(part)
        if m:
            out.append({"kind": "gap", "marker": part,
                        "asks": (m.group(2) or "").strip() or "this"})
        else:
            out.append({"kind": "text", "text": part})
    return out
