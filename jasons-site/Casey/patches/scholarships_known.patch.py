#!/usr/bin/env python3
"""Stop asking whether she won scholarships. Run from Casey/.

Jason, 2026-09-07: "she also did ROTC in college / and won scholarships."

THE FIRST HALF NEEDED NOTHING. Her college AFROTC is already on the record
and correctly dated -- 2010-01-01 to 2014-05-01, kind `rotc`, "through
college to commissioning", plus the commissioning entry itself in May 2014
with an honest note that the date came from photo metadata rather than a
document. The vocabulary already keeps AFROTC (college, commissioning)
separate from AFJROTC (high school, not a commissioning source), so there
was nothing to correct.

THE SECOND HALF CHANGES A QUESTION FROM YES/NO TO WHICH. The measure added
an hour ago asked "Any scholarships?" That was the right question when
nobody knew. Jason has now answered it, so asking her again spends one of
a handful of prompt slots confirming something already established -- and a
question whose answer is already known is how somebody learns the prompts
are not really listening.

So it becomes "You won scholarships -- which ones?", and it names likely
candidates as memory prompts. THOSE ARE PROMPTS, NOT CLAIMS: an AFROTC
scholarship is common for somebody who did four years of AFROTC, and it is
still not a thing anybody has told me she held. It is offered as a jog and
recorded nowhere until she says so.

THE PROFILE RECORDS "CONFIRMED, UNDETAILED", which is a different state from
"unknown" and worth keeping distinct. Unknown means nobody has looked.
Confirmed-undetailed means the fact exists and only the specifics are
missing -- and that is a gap somebody can close in one sentence rather than
a question that needs research.
"""
import io
import sys

P = "app/roadmap.py"
s = io.open(P, encoding="utf-8").read()
if "which ones" in s:
    sys.exit("already patched")

OLD = '''    {"key": "scholarship", "ask": "Any scholarships? Name, who awarded it, "
                                  "roughly what year — and the amount if you "
                                  "know it.",
     "why": "A competitive scholarship is evidence rather than decoration: "
            "somebody chose you over other applicants, and that is exactly "
            "what a board is trying to establish.",'''
NEW = '''    # ASKS WHICH, NOT WHETHER. Jason confirmed on 2026-09-07 that she won
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
            "fine — they can be marked as approximate.",'''
assert OLD in s, "scholarship measure not found"
s = s.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("roadmap.py: scholarship question now asks which, not whether")

# The profile records that they exist. "Confirmed, undetailed" is a
# different state from "unknown" -- one is a sentence away from closed, the
# other needs somebody to go and find out.
K = "knowledge/10-profile.md"
k = io.open(K, encoding="utf-8").read()
OLDK = ("- **Scholarships:** [FILL IN — name, awarding body, year, amount if\n"
        "  known. Competitive ones are evidence, not decoration]")
NEWK = ("- **Scholarships:** **She won scholarships** — Jason confirmed this on\n"
        "  7 September 2026. WHICH ones is [FILL IN — name, awarding body,\n"
        "  year, amount if known].\n"
        "  > This is CONFIRMED-BUT-UNDETAILED, which is not the same as\n"
        "  > unknown. The fact is established; only the specifics are\n"
        "  > missing, so this closes in one sentence from her rather than\n"
        "  > needing anybody to go and find out. Competitive scholarships\n"
        "  > are evidence, not decoration — somebody chose her over other\n"
        "  > applicants, which is what a board is trying to establish.\n"
        "- **College AFROTC:** on the record — 2010 to May 2014, through\n"
        "  college to commissioning. NOT AFJROTC; see the milestone kinds.")
if OLDK in k:
    k = k.replace(OLDK, NEWK, 1)
    io.open(K, "w", encoding="utf-8", newline="\n").write(k)
    print("  profile: scholarships marked confirmed-undetailed")
else:
    print("  profile: scholarship slot not in the expected shape, left alone")
