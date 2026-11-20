#!/usr/bin/env python3
"""Honours are confirmed in both. Ask which. Run from Casey/.

Jason, 2026-09-07: "My sister was awarded honors in high school and college.
I don't know what — I have to get the information from her."

That sentence settles one thing and leaves another open, and the questions
should reflect exactly that split. THAT she was awarded honours in both is
now established. WHICH honours is unknown to everyone except her.

So both questions stop asking whether. A prompt that asks something already
answered teaches the reader that the prompts are not really listening, and
there are only a handful of slots -- spending one on a yes/no whose answer
is in the profile is a slot not spent on the thing nobody knows.

WHY THIS KEEPS WORKING RATHER THAN NAGGING. roadmap.py only surfaces a
measure whose words appear NOWHERE in her record, so the moment she names a
society or a semester, the question retires itself. Confirming the honours
exist does NOT retire it -- the trigger words are the specifics, which is
the correct behaviour: the gap is the detail, not the fact.

THE PROFILE RECORDS "CONFIRMED, UNDETAILED" for both, the same state the
scholarships are in. It is worth keeping distinct from unknown: unknown
means nobody has looked, confirmed-undetailed means the fact is established
and one sentence from her closes it. Jason has said he will have to ask her,
so the record should show a question waiting on her rather than a blank that
looks like nothing happened.
"""
import io
import sys

P = "app/roadmap.py"
s = io.open(P, encoding="utf-8").read()
if "You were awarded honours" in s:
    sys.exit("already patched")

OLD = '''    {"key": "honors", "ask": "Any honours at college — Dean\\u2019s List, an "
                             "honour society, cum laude? Which years?",'''
NEW = '''    # ASKS WHICH, NOT WHETHER. Jason confirmed on 2026-09-07 that she was
    # awarded honours in both high school and college, and said he would
    # have to get the specifics from her. So the yes/no is settled and only
    # the detail is open -- and the detail is what the trigger words match,
    # so this retires itself the moment she names one.
    {"key": "honors", "ask": "You were awarded honours at college — which "
                             "ones? Dean\\u2019s List (which semesters), an "
                             "honour society, cum laude / magna / summa, a "
                             "departmental prize?",'''
assert OLD in s, "honors measure not found"
s = s.replace(OLD, NEW, 1)

OLD2 = '''    {"key": "school", "ask": "What did you hold or win in high school and "
                             "AFJROTC — rank, awards, anything you were "
                             "selected for?",'''
NEW2 = '''    # Same change, and the same reason. Two of her high-school awards are
    # already on the record -- Bright Futures and the Spanish scholarship --
    # so the question names them as the anchor and asks what else sat
    # alongside them, rather than opening from nothing.
    {"key": "school", "ask": "You were awarded honours in high school too — "
                             "which ones? (Bright Futures and the Spanish "
                             "scholarship are already recorded.) Honour roll, "
                             "AFJROTC rank or awards, anything you were "
                             "selected for?",'''
assert OLD2 in s, "school measure not found"
s = s.replace(OLD2, NEW2, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("roadmap.py: both honours questions now ask which, not whether")

K = "knowledge/10-profile.md"
k = io.open(K, encoding="utf-8").read()
if "CONFIRMED by Jason" in k:
    print("  profile already updated")
else:
    OLDK = ("- **High school honours / AFJROTC:** [FILL IN — awards, rank held,\n"
            "  honour roll, anything she was selected for]\n"
            "- **College honours:** [FILL IN — Dean's List and which semesters,\n"
            "  honour societies, cum laude / magna / summa, departmental prizes]")
    NEWK = ("- **High school honours / AFJROTC:** **She was awarded honours** —\n"
            "  CONFIRMED by Jason, 7 September 2026. WHICH ones is [FILL IN].\n"
            "  Already on the record from that period: Florida Bright Futures\n"
            "  and a Spanish scholarship, both won in high school.\n"
            "- **College honours:** **She was awarded honours** — CONFIRMED by\n"
            "  Jason, 7 September 2026. WHICH ones is [FILL IN — Dean's List\n"
            "  and which semesters, honour societies, cum laude / magna /\n"
            "  summa, departmental prizes].\n"
            "  > Both of these are CONFIRMED-BUT-UNDETAILED, not unknown.\n"
            "  > Jason has said he has to get the specifics from her, so the\n"
            "  > portal now asks WHICH rather than WHETHER — asking a question\n"
            "  > whose answer is already in this file wastes one of a handful\n"
            "  > of prompt slots and teaches her the prompts are not listening.")
    if OLDK in k:
        k = k.replace(OLDK, NEWK, 1)
        io.open(K, "w", encoding="utf-8", newline="\n").write(k)
        print("  profile: honours marked confirmed-undetailed for both")
    else:
        print("  profile: honour slots not in the expected shape, left alone")
