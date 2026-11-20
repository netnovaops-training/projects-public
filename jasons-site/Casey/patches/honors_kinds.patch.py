#!/usr/bin/env python3
"""Somewhere to put school and college honours. Run from Casey/.

Jason, 2026-09-07: "I want to add her honors when she was in highschool and
in college."

The milestone vocabulary already gets the hard distinction right -- AFJROTC
(high school) and AFROTC (commissioning) are separate kinds, with a note
saying why confusing them is not pedantry. What it has no word for is an
academic honour: Dean's List, an honour society, graduating cum laude, a
departmental prize, a scholarship.

Those would currently land as "other", which is where things go to stop
being findable. Two kinds fix it:

  honor        minor -- Dean's List, honour society, cum laude, a prize
  scholarship  minor -- a named or competitive award of money

BOTH MINOR, AND THAT IS NOT A JUDGEMENT ABOUT HER. The tiers on this
timeline mean "changed what you are" (red) versus "built toward the next
one" (blue) -- commissioning changes what you are, the Dean's List does not.
Minor is the correct shelf for something that evidences the person without
altering their status, and the jacket legend already says so in those words.

WHY SCHOLARSHIP IS SEPARATE FROM HONOR. A scholarship is competitive, dated,
and usually has a dollar figure and a selecting body attached -- which makes
it evidence in a way a Dean's List entry is not. Awards boards read them
differently, so the record should keep them apart rather than merge them and
lose the distinction later.

NO FACTS ARE ADDED HERE. This patch creates the shelf; what actually goes on
it has to come from Casey or Jason. Inventing a plausible honour for somebody's
official record is precisely the failure this whole portal is built to
prevent.
"""
import io
import sys

P = "app/milestones.py"
s = io.open(P, encoding="utf-8").read()
if '"honor"' in s:
    sys.exit("already patched")

OLD = '''    "credential":  ("minor", "Credential"),'''
NEW = '''    # ACADEMIC HONOURS, added 2026-09-07. Jason: "I want to add her honors
    # when she was in highschool and in college." Without these they land
    # as "other", which is where things go to stop being findable.
    #
    # MINOR IS NOT A VERDICT ON THEM. The tiers here mean "changed what you
    # are" against "built toward the next one" -- commissioning changes what
    # she is, the Dean's List does not. That is the shelf, and the jacket
    # legend already says it in those words.
    "honor":       ("minor", "Academic honour"),
    # KEPT SEPARATE FROM honor ON PURPOSE. A scholarship is competitive,
    # dated, and normally carries a figure and a selecting body -- which
    # makes it evidence in a way a Dean's List line is not. Merging them
    # loses a distinction an awards board actually reads.
    "scholarship": ("minor", "Scholarship"),
    "credential":  ("minor", "Credential"),'''
assert OLD in s, "credential kind not found"
s = s.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("milestones.py: honor + scholarship kinds added")

# The profile gets the matching slots, so the gap is visible rather than
# implied by absence.
K = "knowledge/10-profile.md"
k = io.open(K, encoding="utf-8").read()
if "High school honours" in k:
    print("  profile already has the slots")
else:
    OLDK = "- **Prior degrees:** [FILL IN]"
    NEWK = ("- **Prior degrees:** [FILL IN]\n"
            "- **High school honours / AFJROTC:** [FILL IN — awards, rank held,\n"
            "  honour roll, anything she was selected for]\n"
            "- **College honours:** [FILL IN — Dean's List and which semesters,\n"
            "  honour societies, cum laude / magna / summa, departmental prizes]\n"
            "- **Scholarships:** [FILL IN — name, awarding body, year, amount if\n"
            "  known. Competitive ones are evidence, not decoration]")
    assert OLDK in k, "Prior degrees line not found"
    k = k.replace(OLDK, NEWK, 1)
    io.open(K, "w", encoding="utf-8", newline="\n").write(k)
    print("  profile: three honour slots added")
