#!/usr/bin/env python3
"""Make the portal ask about the work officers never volunteer. Run from Casey/.

Jason, 2026-09-07: "when she was at Vacaville she did a whole bunch of extra
things that an officer did, like extra duties, awards and other volunteer
things that she was responsible for. I want to show that not only was she
responsible for extra duties, but she went above and beyond and picked up
extra things as well."

THIS IS ALREADY IDENTIFIED AS THE GAP AND STILL NOT ASKED FOR. Two lines in
knowledge/10-profile.md have been sitting empty since it was written:

    - Additional duties / leadership roles: [FILL IN]
    - Volunteer and community involvement: [FILL IN -- hours, organization, role]

and knowledge/30-awards-catalog.md says of exactly these two fields that
they "are precisely the eligibility gates for most of what" she can apply
for. So the system knows they decide which awards she qualifies for, has
somewhere to put them, and has never once asked.

The follow-up prompt is where that gets fixed, because it is the only place
the portal asks her anything unprompted. Today it requires two questions on
leadership scope, two on quantification and one on whether the impact
travelled upward -- all good, and all about the accomplishment she just
described. None of them can surface a duty she held alongside it.

WHY IT HAS TO BE ASKED RATHER THAN WAITED FOR. followups.py already says it:
she "will not think to volunteer it -- you have to" ask. Additional duties
are the clearest case of that. Being the unit's awards monitor, or running
the booster club, is not what an officer thinks of when asked "what did you
achieve" -- it is background, it is what everyone does, it is the thing you
did on top of your actual job. It is also, per the awards catalog, the
thing a board is scoring.

ONE QUESTION, NOT A SECTION. The prompt already asks for three to seven and
every slot spent is one not spent on a number. This takes exactly one, and
only when the draft has not already covered it.
"""
import io
import sys

P = "app/worker.py"
s = io.open(P, encoding="utf-8").read()
if "additional duty" in s.lower():
    sys.exit("already patched")

OLD = """- At least ONE question must probe whether the impact travelled upward: was it"""
NEW = """- At least ONE question must probe ADDITIONAL DUTIES OR VOLUNTEER WORK she
  held at the same time -- awards monitor, unit training manager, safety
  representative, mentoring, a base or community programme she ran. Ask what
  she was responsible for ALONGSIDE this, and for how long. She will not
  raise these herself: they are the things done on top of the actual job, so
  they read to her as background rather than as achievements. They are also
  the eligibility gates for most of the awards she is chasing, which is the
  opposite of background. Skip this only if the draft already names one.
- At least ONE question must probe whether the impact travelled upward: was it"""
assert OLD in s, "followup rules not found"
s = s.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("worker.py: follow-ups now ask about additional duties and volunteering")
