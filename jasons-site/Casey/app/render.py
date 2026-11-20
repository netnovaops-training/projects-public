"""One record in, the right shape out.

Jason, 2026-09-06: "she chooses the output of what it's going on within
or award ... split out the correct output for that award and the language
it needs to be put out in."

THE SAME ACCOMPLISHMENT IS FOUR DIFFERENT DOCUMENTS
A 1206 wants a two-line bullet with no pronouns and a number in it. AMSUS
wants narrative prose about the last twelve to eighteen months, written in
somebody else's voice. DAISY wants a story a patient tells, with no metrics
at all -- numbers are the wrong register there entirely. A promotion board
wants a trajectory across years. Hand a board the bullets and the record
reads thin; hand the 1206 the narrative and it does not fit the form.

So the target is not a filter over one output. It selects a different
register, and the register is what this module applies.

THE RULES LIVE IN THE AWARD FILE, NOT IN THIS CODE
Each knowledge/awards/<id>.md carries a "How this must be written"
section, and that section is passed to the model verbatim. Two reasons,
and the second is the real one:

  1. Jason or Casey can correct how a package is written by editing a
     markdown file, with no code change.
  2. When a wing instruction turns out to differ from what is written
     there, the fix belongs next to the award it applies to -- not buried
     in a prompt string in Python where nobody will find it.

WHAT IT MAY NOT DO
It writes from her record and nothing else. It may not invent an
accomplishment, a number, a date or a scope. An empty record produces
"there is nothing here to write from yet", which is the true answer and
more useful than a fluent paragraph about work she did not do -- that
paragraph would go into a real package under her name.
"""
from __future__ import annotations

import re

from . import awards, db, llm

# The section of an award file that describes its output register.
_HOWTO = re.compile(
    r"^##\s+How this (?:must be|is) written.*?$(.*?)(?=^##\s|\Z)",
    re.M | re.S)


def format_guidance(award_id: str) -> str:
    """The award's own rules about how its output must be written."""
    a = awards.get(award_id)
    if not a:
        return ""
    m = _HOWTO.search(a.get("body", ""))
    return (m.group(0) if m else "").strip()


SYSTEM = """You turn a nurse officer's own record into ONE document, in the exact
register the target demands. You are a drafter, not a researcher and not a
biographer.

ABSOLUTE RULES
- Write ONLY from the record you are given. Never invent an accomplishment, a
  number, a date, a unit, a name or a scope. If the record does not contain a
  number, do not produce one -- say the number is missing.
- Never escalate scope. If the record says one unit, the output says one unit.
  Scope inflation is the failure that gets a package returned unscored, and it
  is the single most common way a draft like this does damage.
- Her Master's is IN PROGRESS. Never write it as held.
- Follow the target's writing rules below EXACTLY -- they override any general
  instinct about good writing. If they say no first person, use none. If they
  say no metrics, use none.
- Where the record is too thin for this target, say so plainly and list what is
  missing. That is a useful answer. A fluent paragraph about work she did not
  do is not -- it would go into a real package under her name.

Return JSON only:
{"draft": "the document itself, in the target's register",
 "missing": ["what the record needs before this is submittable"],
 "scope_notes": "anything you had to hold back because the record did not
                 support it, or empty"}
"""


def _record_for(target_id: str, limit: int = 30) -> str:
    """Her record, as material. Everything relevant, nothing invented."""
    rows = db.portfolio_list(limit=limit)
    if not rows:
        return ""
    # Entries she has already aimed at this target come first: they are the
    # ones she thinks belong here, and that judgement is hers to make.
    rows.sort(key=lambda r: (r.get("award_target") or "") != target_id)
    out = []
    for r in rows:
        bits = [f"### {r['title'] or '(untitled)'}"]
        if r.get("happened_on"):
            bits.append(f"When: {r['happened_on']}")
        if r.get("award_target"):
            bits.append(f"She aimed this at: {r['award_target']}")
        for f in ("situation", "task", "action", "result", "evidence", "skills"):
            v = (r.get(f) or "").strip()
            if v:
                bits.append(f"{f.capitalize()}: {v}")
        out.append("\n".join(bits))
    return "\n\n".join(out)


def draft(award_id: str, system_prompt: str = "", extra: str = "") -> dict:
    """Draft the output for one target, in that target's language."""
    a = awards.get(award_id)
    if not a:
        return {"error": f"There is no award called {award_id!r}."}
    if a.get("status") == "closed":
        # Refusing here is the correct behaviour, not an obstacle. These
        # files exist precisely so a closed door is caught before effort
        # goes into it.
        return {"error": f"{a['name']} is closed to her — see the award file "
                         "for why. Nothing is drafted for a closed target."}

    record = _record_for(award_id)
    if not record:
        return {"draft": "", "missing": [
            "There is nothing in the portfolio yet, so there is nothing to "
            "write from. Add one entry — even rough — and this will have "
            "material."], "scope_notes": ""}

    guidance = format_guidance(award_id) or (
        "## How this must be written\n\nNo specific format is recorded for this "
        "target. Write it as a short factual narrative and say that the format "
        "was not specified.")
    state = db.target_get(award_id)

    user = "\n\n".join([
        f"# TARGET: {a['name']}",
        guidance,
        "# WHAT SHE HAS ALREADY NOTED ABOUT THIS TARGET",
        "\n".join(f"{k}: {state[k]}" for k in
                  ("status", "next_action", "notes", "owner_note",
                   "deadline_note")
                  if state.get(k)) or "(nothing yet)",
        "# HER RECORD — the only material you may use",
        record,
        ("# ALSO CONSIDER\n" + extra) if extra.strip() else "",
    ]).strip()

    system = ((system_prompt + "\n\n" + SYSTEM) if system_prompt else SYSTEM)
    try:
        answer, model = llm.ask(system, user, temperature=0.2)
        data = llm.extract_json(answer)
    except Exception as e:  # noqa: BLE001
        db.log_event("error", "render", f"draft failed: {e}")
        return {"error": f"No draft came back: {e}"}
    if not isinstance(data, dict):
        return {"error": "The draft came back in a shape I could not read."}
    missing = data.get("missing")
    if isinstance(missing, str):
        missing = [missing]
    return {
        "award_id": award_id,
        "award_name": a["name"],
        "format": a.get("format", ""),
        "draft": str(data.get("draft") or "").strip(),
        "missing": [str(m) for m in (missing or []) if str(m).strip()],
        "scope_notes": str(data.get("scope_notes") or "").strip(),
        "model": model,
    }


def draft_markdown(result: dict) -> str:
    """The draft as a file she can download, hand over, or paste."""
    if result.get("error"):
        return f"# Could not draft\n\n{result['error']}\n"
    lines = [f"# {result['award_name']} — draft", ""]
    if result.get("format"):
        lines += [f"*Written in the `{result['format']}` register. "
                  "See the award file for the rules this follows.*", ""]
    lines += ["---", "", result.get("draft") or "_(nothing drafted)_", ""]
    if result.get("missing"):
        lines += ["---", "", "## Before this is submittable", ""]
        lines += [f"- {m}" for m in result["missing"]]
        lines.append("")
    if result.get("scope_notes"):
        lines += ["---", "", "## Held back on purpose", "",
                  result["scope_notes"], ""]
    lines += ["---", "",
              f"*Drafted by {result.get('model', 'a model')} from her own "
              "record. It invents nothing — if a number is missing here, it is "
              "missing from the record. Check every fact before this goes "
              "anywhere.*", ""]
    return "\n".join(lines)
