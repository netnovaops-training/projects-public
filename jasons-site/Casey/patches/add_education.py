#!/usr/bin/env python3
"""Her degree, her scholarships and her clinicals. Run inside the casey container.

Jason, 2026-09-07: "she did clinicals ... she won a Spanish scholarship too
in high school to go to college ... she also won the bright futures from
Florida to go to UWF."

WHAT WAS ALREADY THERE: her college AFROTC, 2010 to May 2014.
WHAT WAS MISSING: the degree that ran alongside it, the two scholarships
that paid for it, and the clinical hours that made her a nurse. Her
BACHELOR'S DEGREE was not on the record at all -- the only degree entry was
the Master's still in progress.

DATES, AND WHERE THEY COME FROM. Jason gave no years, so nothing here
invents one. The college span is taken from the AFROTC milestone already on
the record (2010-01-01 to 2014-05-01) because AFROTC ran "through college to
commissioning", which pins the same four years. Everything derived that way
is recorded with YEAR precision, not a fabricated month and day, and says in
its own detail line that it was inferred and from what. `parse_when` maps a
bare year to year precision, so the jacket will render "2010" rather than
pretending to know a date.

The two scholarships are dated 2010 for the same reason: both are awarded on
leaving high school, to be taken up at college, and her college began in
2010. That is an inference from how these awards work, and it is labelled as
one.

WHY THE SCHOLARSHIPS ARE WORTH THE ROW. Both are competitive and neither is
decoration. Florida Bright Futures is a state merit programme with a
published threshold -- test scores, GPA, service hours -- so it is an
objective statement that she cleared a bar as a teenager. A Spanish
scholarship is a subject prize, which says something narrower and sharper:
somebody judged her the best candidate in a field. A board reading a Field
Grade package is trying to work out how long she has been performing at this
level, and these answer it from before she was in uniform.

CLINICALS ARE A SPAN WITH A HOLE IN IT, deliberately. That she did them is
certain -- she is a nurse, they are not optional. WHEN, HOW MANY HOURS and
IN WHICH SPECIALTIES are unknown, and those are the only parts a board
actually reads. So the entry exists and says plainly what is missing, rather
than being left out (invisible) or filled with a plausible number (worse).
"""
import sys
sys.path.insert(0, "/app")

from app import db, milestones  # noqa: E402

USER = "person2@example.com"

existing = {(m.get("title") or "").lower() for m in db.milestone_list()}

WANT = [
    # The bachelor's -- absent entirely until now. Spans the same four years
    # as the AFROTC entry already on the record, which is where the dates
    # come from.
    dict(when="2010", until="2014-05", kind="degree", tier="major",
         title="BSN, University of West Florida",
         detail="Bachelor of Science in Nursing. Ran alongside AFROTC "
                "through to commissioning in May 2014. YEARS INFERRED from "
                "the AFROTC milestone (2010 - May 2014), not from a "
                "document -- confirm against her transcript or diploma."),

    # Florida's state merit programme. Objective, published thresholds.
    dict(when="2010", kind="scholarship", tier="minor",
         title="Florida Bright Futures Scholarship",
         detail="State of Florida merit scholarship, taken up at the "
                "University of West Florida. Awarded on leaving high "
                "school. YEAR INFERRED from the start of college (2010) -- "
                "confirm the award year and the exact award tier, which "
                "Bright Futures names (e.g. Academic Scholars / Medallion). "
                "The tier is worth having: it states which bar she cleared."),

    # A subject prize -- narrower than a merit programme and sharper for it.
    dict(when="2010", kind="scholarship", tier="minor",
         title="Spanish scholarship (high school)",
         detail="Won in high school, to be taken up at college. AWARDING "
                "BODY AND AMOUNT UNKNOWN -- worth capturing: a subject "
                "prize means somebody judged her the strongest candidate in "
                "a field, which is a different and sharper claim than a "
                "merit threshold. YEAR INFERRED from the start of college."),

    # Certain that it happened; the parts a board reads are the unknowns.
    dict(when="2010", until="2014-05", kind="course", tier="minor",
         title="Nursing clinical rotations",
         detail="Clinical hours toward the BSN. [NEEDED: which years, how "
                "many hours, and which specialties -- med-surg, OB, peds, "
                "psych, critical care.] Those three are the only parts of "
                "clinicals a board reads, and an obstetric rotation here "
                "would be the earliest evidence of the speciality she has "
                "built a career in. SPAN INFERRED from the degree; clinicals "
                "usually sit in the final two years, so this will narrow."),
]

added = 0
for row in WANT:
    if row["title"].lower() in existing:
        print(f"  already there: {row['title']}")
        continue
    milestones.add(USER, row["when"], row["title"], kind=row["kind"],
                   detail=row["detail"], tier=row["tier"],
                   until=row.get("until", ""))
    print(f"  added: {row['title']}")
    added += 1

print(f"\n{added} added. Milestones now:")
for m in sorted(db.milestone_list(), key=lambda x: x.get("when_iso") or ""):
    span = f" -> {m['until_iso']}" if m.get("until_iso") else ""
    print(f"  {m.get('when_iso')}{span}  [{m.get('kind')}]  {m.get('title')}")
