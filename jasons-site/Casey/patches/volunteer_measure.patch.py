#!/usr/bin/env python3
"""Ask about volunteering, because two medals turn on it. Run from Casey/.

From the briefing Jason pasted on 2026-09-07: MOVSM, PVSA and base Volunteer
of the Year. Her catalog had nothing for volunteering at all, and her
record's `Volunteer and community involvement` line has been [FILL IN] since
the profile was written.

WHY THIS DESERVES A SLOT WHEN THERE ARE ONLY A HANDFUL. Most awards are
judged on merit, and merit cannot be manufactured by better paperwork.
MOVSM and PVSA are different: they are **threshold** awards, scored on
hours and duration. That has two consequences and they point the same way.

  * They are winnable purely by writing things down as they happen.
  * They are UNWINNABLE RETROSPECTIVELY. Nobody reconstructs three years of
    Saturday mornings from memory with enough confidence to certify them.

So the cost of not asking is not a weaker package -- it is a medal that
becomes permanently unprovable, one month at a time. The MOVSM clock is
roughly three years; every month nobody records is a month that cannot be
counted later.

THE QUESTION ASKS FOR THE SCORED FIELDS, not for a story. Hours, how long,
who benefited, what was raised or organised -- those are the boxes both
awards are actually judged on, and asking "do you volunteer?" gets a yes
that helps nobody.

THE WORDS LIST IS NARROW ON PURPOSE. "hours" and "community" are common
enough to appear in clinical writing and would retire the question before it
was ever answered. The triggers are the specific things: volunteer, MOVSM,
PVSA, charity, fundraiser, mentored outside work.
"""
import io
import sys

P = "app/roadmap.py"
s = io.open(P, encoding="utf-8").read()
if '"key": "volunteer"' in s:
    sys.exit("already patched")

OLD = '''    {"key": "money", "ask": "Did it save or avoid any cost?",'''
NEW = '''    # THE WHOLE CATEGORY HER RECORD HAS NEVER TOUCHED. Added 2026-09-07
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
    {"key": "money", "ask": "Did it save or avoid any cost?",'''
assert OLD in s, "money measure not found"
s = s.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("roadmap.py: volunteer measure added")
