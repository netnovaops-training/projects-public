#!/usr/bin/env python3
"""Both scholarships were high-school awards. Run inside the casey container.

Jason, 2026-09-07: "The Spanish scholarship was in high school and so was
the bright futures."

WHY THIS MATTERS MORE THAN IT LOOKS. Both were recorded at 2010, which is
also when her degree and her AFROTC start, so on the timeline they sit
inside the college block and read as things she won AT university. They are
the opposite: they are what a seventeen-year-old was awarded that PAID for
the university. That is a different claim and a better one -- it is evidence
from before anybody in the Air Force had shaped her.

THE YEAR IS STILL 2010 AND IS STILL AN INFERENCE. Her college began in 2010,
so the senior year of high school that produced these awards ended in 2010.
Both stay at year precision, and both now say in their own detail line that
this is derived from the college start rather than known, so whoever
confirms it knows exactly which fact to check.

WHAT CHANGES IS THE FRAMING: each entry now states plainly that it was won
in high school and carried to college. Nothing is invented; the same facts
are made unambiguous.
"""
import sys
sys.path.insert(0, "/app")

import sqlite3  # noqa: E402

from app import config  # noqa: E402

DB = str(getattr(config, "DB_PATH", "/data/zeeportal.db"))
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

FIXES = {
    "Florida Bright Futures Scholarship": (
        "Florida Bright Futures Scholarship (high school)",
        "WON IN HIGH SCHOOL and carried to the University of West Florida -- "
        "Jason confirmed 2026-09-07. Florida's state merit programme: "
        "published thresholds on test scores, GPA and service hours, so it "
        "is an objective statement that she cleared a bar as a teenager. "
        "[NEEDED: the award TIER -- Bright Futures names them (Academic "
        "Scholars, Medallion), and the tier is the part that says which bar.] "
        "YEAR INFERRED from the start of college (2010), which places her "
        "final year of high school -- confirm the actual award year."),
    "Spanish scholarship (high school)": (
        "Spanish scholarship (high school)",
        "WON IN HIGH SCHOOL and carried to college -- Jason confirmed "
        "2026-09-07. A subject prize, which is a narrower and sharper claim "
        "than a merit threshold: somebody judged her the strongest candidate "
        "in a field. [NEEDED: awarding body and amount.] YEAR INFERRED from "
        "the start of college (2010) -- confirm the actual award year."),
}

for old_title, (new_title, detail) in FIXES.items():
    r = c.execute("SELECT id FROM milestones WHERE title = ?",
                  (old_title,)).fetchone()
    if not r:
        print(f"  not found: {old_title}")
        continue
    c.execute("UPDATE milestones SET title = ?, detail = ? WHERE id = ?",
              (new_title, detail, r["id"]))
    print(f"  updated: {new_title}")
c.commit()

print("\nEarly record now reads:")
for r in c.execute("SELECT when_iso, until_iso, kind, title FROM milestones "
                   "WHERE when_iso < '2015' ORDER BY when_iso, kind"):
    span = f" -> {r['until_iso']}" if r["until_iso"] else ""
    print(f"  {r['when_iso']}{span}  [{r['kind']}]  {r['title']}")
