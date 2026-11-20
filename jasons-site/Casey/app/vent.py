"""Somewhere to say the hard part, that is not her career record.

Jason, 2026-09-06: "when she's talking, don't allow any negative talk
about what's going on. allow that just to be rant. allow a separate
spreadsheet or word document that is just for ranting or distractions."

WHY THIS IS NOT A FEATURE, IT IS THE THING THAT MAKES THE REST USABLE
She is PCSing to England with a date nobody has, she moved on 11 July,
she has children, and she is being asked to narrate her working life into
a system that turns everything she says into award material. A portal
that treats every utterance as package input is exhausting to talk to,
and the way people cope is by saying less. That costs the record far more
than the venting would.

So there is a place to say it, and it is walled off:

  * NEVER read for accomplishments. Nothing here reaches the portfolio,
    the working document, an award draft or an export.
  * NEVER shown a model that is drafting. The one model call this module
    makes is the OPPOSITE job -- pulling out a fact that is worth keeping
    and OFFERING it, so a real problem mentioned mid-rant is not lost.
  * KEPT, because it is hers. Not analysed, not scored, not summarised
    behind her back. She can delete any of it and it is gone.

THE ONE THING IT DOES DO
A rant often contains a fact: "I have had no handover since the move and
I am covering two elements." That is a genuine leadership scope line
hiding in a complaint. So each entry can be asked, once, whether there is
something in it worth keeping -- and the answer is a suggestion she
accepts or dismisses, never an entry made for her.
"""
from __future__ import annotations

import time

from . import db, llm


def add(username: str, text: str, mood: str = "") -> int:
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to save.")
    return db.vent_add(username, text[:20000], mood[:40])


def listing(username: str = "", limit: int = 100) -> list:
    return db.vent_list(username, limit)


def remove(vent_id: int) -> None:
    db.vent_delete(vent_id)


LOOK_SYSTEM = """Somebody has written down something difficult about their
working life. This is NOT a career entry and must never be treated as one.

Read it once and answer one question: is there a FACT in here that belongs in
a professional record -- a workload, a scope, a duty they have picked up, a
number, something they are covering?

Examples of a fact worth keeping, said inside a complaint:
  "no handover since the move and I'm covering two elements"  -> she is
  covering two elements, which is scope.
  "third week running the floor on my own"  -> she has been in charge.

Do NOT extract feelings, frustration, opinions about people, or anything about
her employer's failings. Those are hers and stay here.

If there is nothing, say so -- that is the common and correct answer.

Reply as JSON only:
{"found": true|false,
 "fact": "the neutral, professional version of just the fact",
 "why": "one short phrase on what it evidences"}
"""


def look_for_a_fact(text: str, system_prompt: str = "") -> dict:
    """Offer a fact hiding in a rant. Never writes anything itself.

    The model is given the SYSTEM prompt only as context about who she is;
    what it returns is a suggestion for her, and nothing here saves it.
    """
    if len((text or "").split()) < 8:
        return {"found": False}
    system = ((system_prompt + "\n\n" + LOOK_SYSTEM)
              if system_prompt else LOOK_SYSTEM)
    try:
        answer, _model = llm.ask(system, text[:6000], temperature=0.1)
        d = llm.extract_json(answer)
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "vent", f"could not read it: {e}")
        return {"found": False}
    if not isinstance(d, dict) or not d.get("found"):
        return {"found": False}
    fact = str(d.get("fact") or "").strip()
    if not fact:
        return {"found": False}
    return {"found": True, "fact": fact,
            "why": str(d.get("why") or "").strip()}
