"""What stands between her and the next award, and how close she is.

Jason, 2026-09-06: "add the /road-map to Zees jacket so that she can also
see what she will tackle before the next award by allowing her to keep a
calendar and having clear metrics to keep in mind and finding metrics
that she may not see in her notes, and dialogue to show how close to
hitting it ... make sure she is asked how many patients she handled, any
safety and leadership skills she may not have mentioned."

NO INVENTED PERCENTAGE. The obvious build is a progress bar, and it would
be a lie: nothing here can know what a board will think of her package.
What CAN be counted is countable and specific -- does the record carry a
number, is there evidence behind it, has anyone agreed to nominate her,
is the window open. So the readiness read is a checklist of things that
are true or not true, and the headline is "4 of 7 ready", which is a fact
rather than a guess dressed as one.

THE METRICS SHE CANNOT SEE IN HER OWN NOTES
This is the half Jason asked for that she cannot do herself. A nurse
writes "improved handoffs" and does not think to write the patient
volume behind it, because the volume is just Tuesday to her. MEASURES
below is the list of things her specialty is measured on, checked against
what her record actually says, so the ones she has never mentioned
surface as questions rather than staying invisible.

Patient volume, safety and leadership lead that list because Jason named
them, and because they are the three a board looks for first and a
clinician mentions last.
"""
from __future__ import annotations

import re
from datetime import date

from . import awards, db, milestones, research

# What her specialty is measured on. Each carries the words that would
# show it is already in her record, so a measure she has covered is not
# asked about again.
MEASURES = [
    {"key": "patients", "ask": "How many patients or deliveries did this cover?",
     "why": "Volume is the number a board reaches for first, and the one a "
            "clinician never writes down because it is just the job.",
     "words": ("patient", "deliveries", "births", "encounters", "cases",
               "beneficiaries", "admissions")},
    {"key": "safety", "ask": "Did anything you did make care safer — near "
                             "misses caught, an event rate that fell, a "
                             "process that stopped something going wrong?",
     "why": "Safety is the strongest thing a nurse can show and the least "
            "often claimed, because it feels like ordinary practice.",
     "words": ("safety", "harm", "near miss", "hemorrhage", "haemorrhage",
               "adverse", "incident", "risk", "sentinel", "error")},
    {"key": "leadership", "ask": "Who did you lead, teach, precept or "
                                 "supervise — and how many?",
     "why": "Field Grade and Company Grade packages both turn on people, not "
            "just outcomes. Precepting two new grads is leadership.",
     "words": ("led", "supervis", "precept", "mentor", "trained", "taught",
               "team", "charge", "element", "flight")},
    # SCHOOL AND COLLEGE, added 2026-09-07 at Jason's request. He was asked
    # whether to enter these himself or have the portal ask her, and chose
    # the portal -- so they are asked here rather than written in
    # second-hand, and the answers come from her.
    #
    # These retire themselves: roadmap.py only surfaces a measure whose
    # words appear NOWHERE in her record, so each shows once and then goes
    # quiet once answered. The word lists are deliberately narrow -- a
    # common word like "award" would match half her file and kill the
    # question before it was ever answered.
    # ASKS WHICH, NOT WHETHER. Jason confirmed on 2026-09-07 that she was
    # awarded honours in both high school and college, and said he would
    # have to get the specifics from her. So the yes/no is settled and only
    # the detail is open -- and the detail is what the trigger words match,
    # so this retires itself the moment she names one.
    {"key": "honors", "ask": "You were awarded honours at college — which "
                             "ones? Dean\u2019s List (which semesters), an "
                             "honour society, cum laude / magna / summa, a "
                             "departmental prize?",
     "why": "A college honour is the only thing in your file that shows who "
            "you were before the Air Force shaped you. A board asking how "
            "long you have performed at this level gets an answer fifteen "
            "years earlier than your first report can give them.",
     "words": ("dean's list", "deans list", "honour society", "honor society",
               "cum laude", "magna", "summa", "sigma theta tau",
               "phi kappa phi", "valedictorian", "salutatorian")},
    # Same change, and the same reason. Two of her high-school awards are
    # already on the record -- Bright Futures and the Spanish scholarship --
    # so the question names them as the anchor and asks what else sat
    # alongside them, rather than opening from nothing.
    {"key": "school", "ask": "You were awarded honours in high school too — "
                             "which ones? (Bright Futures and the Spanish "
                             "scholarship are already recorded.) Honour roll, "
                             "AFJROTC rank or awards, anything you were "
                             "selected for?",
     "why": "AFJROTC leadership is the earliest evidence you have of being "
            "picked out, and it is the part nobody writes down because it "
            "feels like a long time ago.",
     "words": ("afjrotc", "jrotc", "high school", "honor roll",
               "honour roll", "cadet")},
    # ASKS WHICH, NOT WHETHER. Jason confirmed on 2026-09-07 that she won
    # scholarships, so the yes/no is settled and asking it again would spend
    # one of a handful of prompt slots on something already known -- which is
    # how somebody learns the prompts are not really listening.
    #
    # The named examples are MEMORY PROMPTS, NOT CLAIMS. An AFROTC
    # scholarship is common for somebody who did four years of AFROTC, and
    # nobody has said she held one. It is offered as a jog and recorded
    # nowhere until she says so.
    {"key": "scholarship", "ask": "You won scholarships — which ones? Name, "
                                  "who awarded it, roughly what year, and the "
                                  "amount if you know it. (AFROTC? A nursing "
                                  "or university scholarship?)",
     "why": "A competitive scholarship is evidence rather than decoration: "
            "somebody chose you over other applicants, and that is exactly "
            "what a board is trying to establish. Approximate years are "
            "fine — they can be marked as approximate.",
     "words": ("scholarship", "bursary", "grant awarded", "stipend",
               "hsps", "rotc scholarship")},
    # THE WHOLE CATEGORY HER RECORD HAS NEVER TOUCHED. Added 2026-09-07
    # from the awards briefing: MOVSM, PVSA and base Volunteer of the Year
    # are all volunteer awards and her catalog had none of them.
    #
    # This earns a slot because those two medals are THRESHOLD awards --
    # scored on hours and duration rather than on merit. They are winnable
    # purely by writing things down as they happen, and unwinnable
    # retrospectively, because nobody reconstructs three years of Saturdays
    # well enough to certify them. The MOVSM clock is about three years, so
    # every unrecorded month is one that cannot be counted later.
    #
    # It asks for the SCORED FIELDS rather than for a story: hours, how
    # long, who benefited, what was raised. "Do you volunteer?" gets a yes
    # that helps nobody.
    {"key": "volunteer", "ask": "What do you do outside work — volunteering, "
                                "coaching, a committee, anything for the base "
                                "or the community? Roughly how many hours, "
                                "since when, and who benefited?",
     "why": "The MOVSM is an actual medal and the PVSA is scored purely on "
            "documented hours — both are won by recording things as they "
            "happen and cannot be reconstructed afterwards. The clock is "
            "about three years, so an unrecorded month is one that cannot "
            "be counted later. This is the category your record has never "
            "touched at all.",
     "words": ("volunteer", "movsm", "pvsa", "charity", "fundrais",
               "coached", "booster", "outreach", "non-profit", "nonprofit",
               "food bank", "habitat", "scouts")},
    {"key": "money", "ask": "Did it save or avoid any cost?",
     "why": "A dollar figure survives a board better than an adjective.",
     "words": ("$", "cost", "saved", "budget", "funding")},
    {"key": "scope", "ask": "Did anyone outside your own unit end up using it?",
     "why": "Scope decides which award it fits — and overstating it is what "
            "gets a package returned, so the honest answer matters both ways.",
     "words": ("group", "wing", "squadron", "enterprise", "other units",
               "MTF", "across")},
    {"key": "evidence", "ask": "What document or log would prove this if "
                               "somebody asked?",
     "why": "An unevidenced claim is the one a board quietly discounts.",
     "words": ("log", "minutes", "audit", "report", "records", "form",
               "citation", "order")},
]

_NUM = re.compile(r"\b\d")


def _record_text() -> str:
    parts = []
    for r in db.portfolio_list(limit=200):
        for f in ("title", "situation", "task", "action", "result",
                  "evidence", "skills"):
            v = (r.get(f) or "").strip()
            if v:
                parts.append(v)
    return " \n".join(parts).lower()


def measures_missing() -> list:
    """Measures her record never mentions. These become the questions."""
    text = _record_text()
    out = []
    for m in MEASURES:
        if not any(w.lower() in text for w in m["words"]):
            out.append({k: m[k] for k in ("key", "ask", "why")})
    return out


def readiness(award_id: str = "") -> dict:
    """A checklist, not a percentage. See this module's header for why."""
    target = None
    if award_id:
        target = next((a for a in awards.listing() if a["id"] == award_id), None)
    if not target:
        chasing = [a for a in awards.listing()
                   if a.get("my_status") in ("chasing", "submitted")]
        target = chasing[0] if chasing else None
    if not target:
        return {"target": None,
                "why": "Pick a target under Awards and this fills in."}

    rows = db.portfolio_list(limit=200)
    state = db.target_get(target["id"])
    aimed = [r for r in rows if (r.get("award_target") or "") == target["id"]]
    pool = aimed or rows

    quantified = [r for r in pool if _NUM.search(
        " ".join(str(r.get(f) or "") for f in ("result", "action")))]
    evidenced = [r for r in pool if (r.get("evidence") or "").strip()]
    gaps_left = sum(1 for r in pool
                    for _ in re.finditer(r"\[(NEEDED|FILL IN)", " ".join(
                        str(r.get(f) or "") for f in
                        ("situation", "task", "action", "result", "evidence"))))

    # THE GRADE GATE COMES FIRST, because everything below it is wasted if
    # this one fails. Caught live: the road map reported "7 of 7 ready"
    # for Field Grade Officer of the Quarter -- an award a CAPTAIN cannot
    # enter. A readiness score that ignores eligibility is worse than no
    # score, because it tells her to submit.
    ref = awards.get(target["id"])
    g = awards.gate_for(ref)
    shut = not g["open"]
    checks = [
        {"ok": not shut,
         "label": ("Open to you at your grade" if not shut
                   else "NOT OPEN TO YOU AT YOUR GRADE"),
         "note": "" if not shut else g["why"]},
        {"ok": bool(pool), "label": "Something in the record to build on",
         "note": f"{len(pool)} entr{'y' if len(pool) == 1 else 'ies'}"},
        {"ok": bool(quantified),
         "label": "At least one entry carries a real number",
         "note": f"{len(quantified)} of {len(pool)}"},
        {"ok": bool(evidenced), "label": "Evidence named for what you claim",
         "note": f"{len(evidenced)} of {len(pool)}"},
        {"ok": gaps_left == 0, "label": "No blanks left in the writing",
         "note": "none left" if gaps_left == 0
                 else f"{gaps_left} still marked [NEEDED]"},
        {"ok": not target.get("nominator_required") or bool(state.get("owner_note")),
         "label": ("Someone has agreed to nominate you"
                   if target.get("nominator_required")
                   else "No nominator needed for this one"),
         "note": state.get("owner_note", "") or
                 ("nobody named yet" if target.get("nominator_required") else "")},
        {"ok": not target.get("gate"), "label": "No eligibility gate in the way",
         "note": target.get("gate", "") or "clear"},
        {"ok": not target.get("blocked_on"), "label": "Nothing outstanding to find out",
         "note": target.get("blocked_on", "") or "clear"},
    ]
    ready = sum(1 for c in checks if c["ok"])
    return {"target": target, "checks": checks, "ready": ready,
            "total": len(checks), "state": state}


def calendar(within_days: int = 400) -> list:
    """Dates ahead of her, from the catalog she already has.

    Reuses research.calendar_findings rather than a second copy of the
    dates -- one transcription of a deadline is already one more than
    ideal, and two would drift apart within a month.
    """
    today = date.today()
    out = []
    for f in research.calendar_findings(today):
        out.append({"title": f["title"], "urgency": f["urgency"],
                    "action": f["action"]})
    for m in milestones.listing():
        if (m.get("until_iso") or "") == "OPEN":
            out.append({"title": f"{m['title']} — still running",
                        "urgency": "normal",
                        "action": "Finishing this is a milestone in itself."})
    return out[:10]
