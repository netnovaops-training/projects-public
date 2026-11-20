#!/usr/bin/env python3
"""Repair `happened_on` on entries already stored. Run inside the container.

Jason, 2026-09-07: "is the backfill of dates correct?"

It was not. Normalising new entries fixes everything written from now on and
does nothing for what is already there -- and what is already there is the
record.

WHAT THIS CHANGES AND WHAT IT WILL NOT TOUCH. Only rows whose `happened_on`
cannot be read as a date, and only where a real date can be recovered from
it. A row that already holds YYYY-MM-DD is left alone. A row where nothing
parses is left alone and REPORTED, because an unreadable date is a fact
somebody should see rather than a field to quietly fill with today.

DRY RUN BY DEFAULT. Pass --write to change anything.
"""
import sqlite3
import sys

sys.path.insert(0, "/app")
from app import config, portfolio  # noqa: E402

con = sqlite3.connect(str(config.DB_PATH))
con.row_factory = sqlite3.Row

rows = con.execute(
    "SELECT id, title, happened_on, ts FROM portfolio "
    "WHERE happened_on IS NOT NULL AND happened_on != ''").fetchall()

ok = fixed = unreadable = 0
changes = []
for r in rows:
    raw = (r["happened_on"] or "").strip()
    # Already a real date -- nothing to do.
    if len(raw) == 10 and raw[4] == "-" and raw[:4].isdigit():
        ok += 1
        continue
    new = portfolio.normalise_when(raw)
    if new:
        changes.append((r["id"], raw, new, r["title"]))
        fixed += 1
    else:
        unreadable += 1
        print(f"  UNREADABLE  id={r['id']}  {raw!r}  ({(r['title'] or '')[:40]})")

print(f"\n{len(rows)} dated entries: {ok} already fine, {fixed} repairable, "
      f"{unreadable} unreadable")
for i, raw, new, title in changes:
    print(f"  id={i}  {raw!r}\n        -> {new}   ({(title or '')[:44]})")

if "--write" in sys.argv and changes:
    for i, _raw, new, _t in changes:
        con.execute("UPDATE portfolio SET happened_on = ? WHERE id = ?", (new, i))
    con.commit()
    print(f"\nwrote {len(changes)} corrections")
elif changes:
    print("\n(dry run -- pass --write to apply)")
