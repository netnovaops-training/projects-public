#!/usr/bin/env python3
"""The jacket badge should say major-select. Run from Casey/.

Jason, 2026-09-07: "CAPT · NURSE CORPS that's not her title she a Major
Select."

He is right about the badge and the profile is right about everything else,
which is why this is a two-line change and not a rewrite.

WHAT THE PROFILE ALREADY SAYS, correctly:
    Rank / grade:       Captain (O-3)
    Promotion status:   MAJOR SELECT -- selected, pinning later in 2026

Both true. She holds O-3 today and has been selected for O-4. The badge read
only the first line and so announced a rank that is accurate and incomplete
-- and "incomplete" is the wrong side to err on for the one thing on the
page that says who she is.

WHAT IS NOT CHANGING, AND MUST NOT. Drafts still write past work as
`Capt Foster`. That is a deliberate, documented rule with a good reason: the
rank in a performance statement is the rank she HELD when she did the work,
and writing 2024 work under a 2026 rank misrepresents the record to a board.
Jason has corrected that in both directions already -- first that "maj is not
major", then that she is a major select -- and both corrections point the
same way. The BADGE is who she is now; the DRAFT is who she was then. They
are allowed to differ, and conflating them is what broke this before.

So: `CAPT (MAJ-SEL) · NURSE CORPS`, which is how the Air Force refers to a
selectee, and it survives the pin-on automatically -- when the profile's
Rank / grade line becomes Major and the promotion-status line goes, the
badge becomes `MAJ · NURSE CORPS` with nothing else touched.
"""
import io
import sys

P = "app/main.py"
s = io.open(P, encoding="utf-8").read()
if "MAJ-SEL" in s:
    sys.exit("already patched")

OLD = '''            m = re.search(r"\\*\\*Rank / grade:\\*\\*\\s*\\*?\\*?([^\\n*(.]+)", t)
            if m:
                rank = m.group(1).strip()
            break'''
NEW = '''            m = re.search(r"\\*\\*Rank / grade:\\*\\*\\s*\\*?\\*?([^\\n*(.]+)", t)
            if m:
                rank = m.group(1).strip()
            # SELECTED FOR THE NEXT ONE IS PART OF WHO SHE IS. The badge read
            # only the grade line, so it said CAPT -- accurate, and
            # incomplete, which is the wrong side to err on for the one line
            # on the page that states her identity. Jason, 2026-09-07:
            # "that's not her title she a Major Select."
            #
            # Read from the profile rather than hardcoded, so the day the
            # promotion-status line is removed the badge stops saying it
            # without anybody remembering to come back here.
            if re.search(r"\\*\\*Promotion status:\\*\\*.*?SELECT", t,
                         re.I | re.S):
                selected = True
            break'''
assert OLD in s, "rank read block not found"
s = s.replace(OLD, NEW, 1)

# `selected` needs initialising beside name/rank.
import re as _re
m = _re.search(r"^(\s*)name, rank = .*$", s, _re.M)
if m:
    s = s[:m.end()] + f"\n{m.group(1)}selected = False" + s[m.end():]
    print("  initialised `selected` beside name/rank")
else:
    # Fall back: initialise at the top of the function body.
    anchor = "    name = rank = \"\""
    if anchor in s:
        s = s.replace(anchor, anchor + "\n    selected = False", 1)
        print("  initialised `selected`")
    else:
        sys.exit("could not find where name/rank are initialised -- aborting")

OLD2 = '''    rank = (rank or "").upper().strip() or "USAF"
    return name.upper(), rank + " · NURSE CORPS"'''
NEW2 = '''    rank = (rank or "").upper().strip() or "USAF"
    # "(MAJ-SEL)" is how the Air Force writes a selectee, and it disappears
    # on its own: when the profile's grade line becomes Major and the
    # promotion-status line goes, this reads MAJ · NURSE CORPS with nothing
    # else edited. The DRAFTS still say Capt Foster for work done as a
    # Captain -- that is a separate, deliberate rule, and the badge saying
    # who she is now does not change who she was then.
    if selected and not rank.startswith("MAJ"):
        rank = f"{rank} (MAJ-SEL)"
    return name.upper(), rank + " · NURSE CORPS"'''
assert OLD2 in s, "badge return not found"
s = s.replace(OLD2, NEW2, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("main.py: badge now reads CAPT (MAJ-SEL)")
