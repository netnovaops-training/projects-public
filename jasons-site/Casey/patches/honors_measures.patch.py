#!/usr/bin/env python3
"""Ask her about school and college honours. Run from Casey/.

Jason, 2026-09-07: "I want to add her honors when she was in highschool and
in college" -- and, asked how, chose to have the portal ask her rather than
have them entered second-hand.

WHY HERE AND NOT IN THE FOLLOW-UP QUESTIONS. The follow-ups are generated
per upload and are about the accomplishment she just described; asking about
the Dean's List every time she logs a shift would be noise, and noise is how
a prompt stops being read. MEASURES is the right home: roadmap.py only
surfaces a measure her record has NEVER touched, so each of these appears
once, stays until something answers it, and then disappears on its own.

THE `words` LISTS ARE THE WHOLE MECHANISM AND ARE EASY TO GET WRONG. A
measure is considered "touched" if any of its words appears anywhere in her
record, so a word that is too common retires the question before it is ever
answered. "award" would match half her file; "honor roll" matches only
somebody writing about an honour roll. Each list below is deliberately
narrow, and "cum laude" is included as one phrase because the components are
useless separately.

WHY THESE ARE WORTH ASKING AT ALL, given they are fifteen years old. Two
reasons, and the second is the one people miss:
  * The awards catalog in this repo says additional duties, PME, prior
    degrees and volunteering "are precisely the eligibility gates for most
    of what" she can apply for. Academic standing sits in that same block.
  * A commissioning-source honour is the only evidence in the file of who
    she was BEFORE the Air Force shaped her. Boards reading a Field Grade
    package are asking how long she has been performing at this level, and
    a college honour society answers that question fifteen years earlier
    than her first performance report can.
"""
import io
import sys

P = "app/roadmap.py"
s = io.open(P, encoding="utf-8").read()
if '"key": "honors"' in s:
    sys.exit("already patched")

OLD = '''    {"key": "money", "ask": "Did it save or avoid any cost?",'''
NEW = '''    # SCHOOL AND COLLEGE, added 2026-09-07 at Jason's request. He was asked
    # whether to enter these himself or have the portal ask her, and chose
    # the portal -- so they are asked here rather than written in
    # second-hand, and the answers come from her.
    #
    # These retire themselves: roadmap.py only surfaces a measure whose
    # words appear NOWHERE in her record, so each shows once and then goes
    # quiet once answered. The word lists are deliberately narrow -- a
    # common word like "award" would match half her file and kill the
    # question before it was ever answered.
    {"key": "honors", "ask": "Any honours at college — Dean\\u2019s List, an "
                             "honour society, cum laude? Which years?",
     "why": "A college honour is the only thing in your file that shows who "
            "you were before the Air Force shaped you. A board asking how "
            "long you have performed at this level gets an answer fifteen "
            "years earlier than your first report can give them.",
     "words": ("dean's list", "deans list", "honour society", "honor society",
               "cum laude", "magna", "summa", "sigma theta tau",
               "phi kappa phi", "valedictorian", "salutatorian")},
    {"key": "school", "ask": "What did you hold or win in high school and "
                             "AFJROTC — rank, awards, anything you were "
                             "selected for?",
     "why": "AFJROTC leadership is the earliest evidence you have of being "
            "picked out, and it is the part nobody writes down because it "
            "feels like a long time ago.",
     "words": ("afjrotc", "jrotc", "high school", "honor roll",
               "honour roll", "cadet")},
    {"key": "scholarship", "ask": "Any scholarships? Name, who awarded it, "
                                  "roughly what year — and the amount if you "
                                  "know it.",
     "why": "A competitive scholarship is evidence rather than decoration: "
            "somebody chose you over other applicants, and that is exactly "
            "what a board is trying to establish.",
     "words": ("scholarship", "bursary", "grant awarded", "stipend",
               "hsps", "rotc scholarship")},
    {"key": "money", "ask": "Did it save or avoid any cost?",'''
assert OLD in s, "money measure not found"
s = s.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("roadmap.py: honours, high school and scholarship measures added")
