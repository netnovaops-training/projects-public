"""The questions that turn a true entry into a usable one.

Jason, 2026-09-06: "I would like to add follow up questions, this was the
biggest thing I wanted to include", alongside "we are using tts so we can
see what's spoken before it's submitted".

WHY THIS IS THE HIGHEST-VALUE PIECE, in the words of her own protocol
file: "She will not remember to tell you the numbers. You have to ask,
specifically, and in a way she can answer in one line while standing in
a hallway."

Everything this session has produced bears that out. Her MSM draft came
back with a `[NEEDED: number]` where the staff count belonged. The
preceptorship entry had `[NEEDED: outcome]`. Those gaps are not the
model failing -- they are the model correctly refusing to invent, and
each one is a question nobody was asking her.

WHY IT LIVES HERE AND NOT ONLY ON JOBS
The job path has asked follow-ups since long before this session and does
it well. But she does not use the job path any more: she dictates, or she
photographs a certificate. Both produce portfolio drafts and neither
asked her anything, so the one mechanism that fills the gaps was wired to
the one door she had stopped using.

ONE AT A TIME, AND SPOKEN
The protocol says between three and seven questions. Presented as a wall
of seven, she answers none -- which is the failure the protocol itself
predicts. So they come one at a time, each is read aloud, and each can be
answered by voice, because the moment she has to answer them is usually
the moment her hands are full.
"""
from __future__ import annotations

import json

from . import db, llm

SYSTEM = """You are asking a nurse officer the questions that turn a true entry
in her career record into one that can actually go into a package.

Her draft is below. It is accurate as far as it goes. What it lacks is the
detail a board needs, and she will not think to volunteer it -- you have to
ask.

RULES, from her own follow-up protocol:
- Answerable in one or two sentences. Never ask her to write a paragraph.
- ONE fact per question. Not "how many staff and what was the outcome?"
- Plain English. Never "what was the echelon of impact?" Ask "did anyone
  outside your unit end up using this?"
- Never ask what the draft already answers.
- Never ask for anything patient-identifying, classified or CUI.
- Between 3 and 6 questions. More and she answers none.

WHAT TO PRIORITISE, in order:
1. Any number the draft is missing. A bullet without a figure is the one that
   loses. "How many?" and "over what period?" are worth more than anything else
   you could ask.
2. Who else was affected, and at what level -- her unit, the group, beyond.
3. Who could confirm it, or what document evidences it.
4. What her own role actually was, if the draft is vague about it. "Asked to
   improve it" hides whether she led it.

Reply as JSON only:
{"questions": [{"ask": "the question, as you would say it out loud",
                "why": "what it unlocks, one short phrase"}]}
"""


def _entry_text(entry: dict) -> str:
    bits = [f"Title: {entry.get('title') or '(untitled)'}"]
    if entry.get("happened_on"):
        bits.append(f"When: {entry['happened_on']}")
    for f in ("situation", "task", "action", "result", "evidence", "skills"):
        v = (entry.get(f) or "").strip()
        if v:
            bits.append(f"{f.capitalize()}: {v}")
    return "\n".join(bits)


def generate(entry_id: int, system_prompt: str = "") -> list:
    """Questions for one portfolio entry. [] on any failure.

    A failure here costs her the questions, not the entry. The draft is
    already saved by the time this runs.
    """
    entry = db.portfolio_get(entry_id)
    if not entry:
        return []
    system = ((system_prompt + "\n\n" + SYSTEM) if system_prompt else SYSTEM)
    try:
        answer, _model = llm.ask(system, _entry_text(entry), temperature=0.3)
        data = llm.extract_json(answer)
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "followups", f"could not generate: {e}")
        return []
    out = []
    for q in (data or {}).get("questions", [])[:6]:
        ask = str((q or {}).get("ask") or "").strip()
        if ask:
            out.append({"ask": ask, "why": str(q.get("why") or "").strip(),
                        "answer": ""})
    if out:
        db.entry_followups_set(entry_id, out)
    return out


def get(entry_id: int) -> list:
    return db.entry_followups_get(entry_id)


def answer(entry_id: int, index: int, text: str) -> list:
    qs = db.entry_followups_get(entry_id)
    if 0 <= index < len(qs):
        qs[index]["answer"] = (text or "").strip()[:2000]
        db.entry_followups_set(entry_id, qs)
    return qs


FOLD_SYSTEM = """You are updating one entry in a nurse officer's career record
with answers she has just given.

Fold her answers into the entry. Do not rewrite what was already right, and do
not add anything she did not say.

- Put numbers where the gaps were. If she said "thirty four", write 34.
- If she did not answer a question, leave that gap as it was. Do NOT fill it
  with a guess, and do not remove the marker saying it is missing.
- Never widen scope beyond what she stated.
- Keep her rank as it was at the time.

Reply as JSON only, with the same field names:
{"title": "", "happened_on": "", "situation": "", "task": "", "action": "",
 "result": "", "evidence": "", "skills": ""}
"""


def fold_in(entry_id: int, system_prompt: str = "") -> dict:
    """Rewrite the entry with her answers. Returns what changed."""
    entry = db.portfolio_get(entry_id)
    if not entry:
        return {}
    qs = [q for q in db.entry_followups_get(entry_id) if q.get("answer")]
    if not qs:
        return {"changed": [], "why": "Nothing has been answered yet."}
    said = "\n".join(f"Q: {q['ask']}\nA: {q['answer']}" for q in qs)
    system = ((system_prompt + "\n\n" + FOLD_SYSTEM)
              if system_prompt else FOLD_SYSTEM)
    user = f"# The entry as it stands\n\n{_entry_text(entry)}\n\n# What she just told you\n\n{said}"
    try:
        answer_text, model = llm.ask(system, user, temperature=0.1)
        data = llm.extract_json(answer_text)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not update it: {e}"}
    if not isinstance(data, dict):
        return {"error": "The update came back in a shape I could not read."}
    fields = {k: str(data.get(k) or "").strip() for k in
              ("title", "happened_on", "situation", "task", "action",
               "result", "evidence", "skills") if data.get(k) is not None}
    changed = [k for k, v in fields.items()
               if v and str(entry.get(k) or "").strip() != v]
    if changed:
        db.portfolio_update(entry_id, **{k: fields[k] for k in changed})
    return {"changed": changed, "model": model,
            "why": (f"Updated {', '.join(changed)}." if changed
                    else "Nothing needed changing.")}
