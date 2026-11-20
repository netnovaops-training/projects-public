"""Everything ChatGPT needs to take over, in one file.

Jason, 2026-09-06: "I'd like to be able to have chat gpt to be able to
export the session and take a over ... especially being verbose if I'm
out of tokens."

WHY THIS IS NOT JUST HER DOCUMENT
When his credit runs out she should carry on inside the ChatGPT
subscription she already pays for. Pasting her notes alone would not do
it. What makes her packages survive a board is a small set of rules that
are not obvious and are expensive to get wrong:

  * Field Grade, never Company Grade. Identical award names, and a
    package filed in the wrong category is returned unscored.
  * The Master's is IN PROGRESS. Written as held is a different kind of
    problem entirely.
  * Scope as it actually was. A unit-level result written as service-wide
    is the most common reason a package comes back.

A model that does not know those three writes fluent prose that gets her
package handed back. So they lead the file, before any of her material.

VERBOSE ON PURPOSE. It is meant to be pasted once into a long-context
chat and worked in for weeks, so it carries her whole record rather than
a summary. There is a short form for a phone.
"""
from __future__ import annotations

from . import awards, db, portfolio, working

PREAMBLE = """# Casey's career record — handoff

You are taking over from another assistant. Everything below is real and
belongs to a serving Air Force Nurse Corps officer. Work FROM it; do not
rewrite it wholesale, and do not invent anything.

## The three rules that decide whether her work is wasted

1. **She is a Major — FIELD GRADE.** Every Company Grade category is closed
   to her. Several awards exist in both versions with IDENTICAL names, and
   a package filed in the wrong category is returned unscored.
2. **Her Master's in Women's Health is IN PROGRESS.** Cite progress —
   credits, clinical hours, expected completion. Never state that she
   holds it.
3. **Never widen scope.** If something happened in one unit, it happened
   in one unit. A unit-level result described as service-wide is the most
   common reason a package is returned, and it is her name on it.

Two more that matter almost as much:

- **Never invent a number, a date or an award name.** If a figure is
  missing, say so and ask her. An empty field is a prompt; an invented one
  is a problem.
- **Bullets carry no first person.** AF Form 1206 bullets are
  action–impact–result, two lines, quantified, no "I" or "my".

---
"""

HOW_TO_CARRY_ON = """---

## How to carry on

Ask her one question at a time. She is usually doing this in gaps — in a
car, between shifts — so a wall of questions gets none of them answered.

The most useful thing you can do is push for numbers. Most of what she
writes is true and unquantified, and a bullet without a figure is the one
that loses. "How many?" and "over what period?" are worth more than any
amount of rewriting.
"""


def _record_block(limit: int = 60) -> str:
    rows = db.portfolio_list(limit=limit)
    if not rows:
        return "## Her record\n\n(Nothing in the portfolio yet.)\n"
    out = ["## Her record", ""]
    for r in rows:
        out.append(f"### {r['title'] or '(untitled)'}")
        if r.get("happened_on"):
            out.append(f"- When: {r['happened_on']}")
        out.append(f"- Status: {r['status']} / {r['category']}")
        if r.get("award_target"):
            out.append(f"- Aimed at: {r['award_target']}")
        for f, label in (("situation", "Situation"), ("task", "Task"),
                         ("action", "Action"), ("result", "Result"),
                         ("evidence", "Evidence"), ("skills", "Skills")):
            v = (r.get(f) or "").strip()
            if v:
                out.append(f"- {label}: {v}")
        out.append("")
    return "\n".join(out)


def _targets_block() -> str:
    rows = [r for r in awards.listing() if r.get("my_status")]
    if rows:
        head = "## What she is chasing"
    else:
        rows = [r for r in awards.listing() if r["kind"] == "target"][:6]
        head = "## What she could aim at (nothing chosen yet)"
    out = [head, ""]
    for r in rows:
        line = f"- **{r['name']}**"
        if r.get("my_status"):
            line += f" — {awards.STATUS_LABEL.get(r['my_status'], r['my_status'])}"
        if r.get("gate"):
            line += f"\n  - Gate: {r['gate']}"
        if r.get("blocked_on"):
            line += f"\n  - Blocked on: {r['blocked_on']}"
        if r.get("nominator_required"):
            line += "\n  - Someone else must nominate her."
        if r.get("next_action"):
            line += f"\n  - Next: {r['next_action']}"
        out.append(line)
    out.append("")
    return "\n".join(out)


def build(verbose: bool = True, session_text: str = "") -> str:
    """The whole handoff. verbose=False is the phone-sized version."""
    parts = [PREAMBLE, _targets_block()]
    if verbose:
        parts.append(_record_block())
        doc = working.read()
        if doc.strip():
            parts.append("## Her working document\n\n" + doc.strip() + "\n")
    else:
        parts.append(_record_block(limit=8))
    if session_text.strip():
        parts.append("## What she just said\n\n" + session_text.strip() + "\n")
    parts.append(HOW_TO_CARRY_ON)
    return "\n".join(parts)


def summary() -> dict:
    p = portfolio.progress()
    return {"entries": p.get("total", 0),
            "ready_unsent": len(p.get("ready_unsent") or []),
            "targets": len([r for r in awards.listing() if r.get("my_status")]),
            "doc_words": len(working.read().split())}
