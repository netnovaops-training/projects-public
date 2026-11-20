#!/usr/bin/env python3
"""Make `happened_on` an actual date. Run from Casey/.

Jason, 2026-09-07: "is the backfill of dates correct and going forward, and
for Casey, Jason and Mom and everyone else, is the information correct for the
dates?"

NO, AND ONE LAYER DEEPER THAN THE FIX EARLIER TODAY. That one corrected the
heading on the draft. This is the field the record actually sorts by, and it
is wrong in a way that hides itself.

Her Commendation Medal entry stores:

    happened_on = "17 August 2023 to 15 July 2026"

The prompt asks for `YYYY-MM-DD if the text says when, otherwise ""`, and the
model answered with the award's period in prose instead -- which is a
reasonable thing to say and an unusable thing to store. `growth_series()`
requires `YYYY-MM`:

    if len(when) >= 7 and when[:4].isdigit() and when[5:7].isdigit():

so anything else falls through to the row's `ts` -- when it was ADDED. The
record grid therefore shows that award in September 2026 rather than August
2023, and nothing anywhere reports a problem. A record that quietly sorts by
filing date is worse than one that admits it has no date.

THE FIX IS AT THE DOOR, not in the reader. Every entry is normalised as it
is written:

  1. already YYYY-MM-DD  -> kept
  2. prose, single date  -> parsed ("17 August 2023" -> 2023-08-17)
  3. prose, a RANGE      -> the START. An award covering 2023-2026 belongs at
                            the point the work began; filing it at the end
                            would put three years of effort in the month the
                            certificate was printed.
  4. nothing usable      -> "" and left empty, honestly, rather than filled
                            with today

WHY NOT FIX growth_series() INSTEAD: because every other reader -- the
workbook, the exports, the jacket, anything added later -- would each need
the same leniency, and one of them would forget. Normalising once on the way
in means every reader can trust the column.

THIS APPLIES TO ALL THREE PORTALS. Casey's, Jason's /ability, and anybody added
later run the same image, so the same guarantee holds for all of them.
"""
import io
import sys

# --- 1. the normaliser ------------------------------------------------------
P = "app/portfolio.py"
s = io.open(P, encoding="utf-8").read()
if "def normalise_when" in s:
    sys.exit("already patched")

FN = '''

def normalise_when(raw: str) -> str:
    """Whatever the model said about when, as YYYY-MM-DD or "".

    THE COLUMN THE RECORD SORTS BY HAS TO BE A DATE. The prompt asks for
    YYYY-MM-DD and the model reasonably answers things like
    "17 August 2023 to 15 July 2026" -- true, useful to read, and unusable
    to sort. Stored as-is it fell through every reader to the row's created
    timestamp, so an award earned in 2023 appeared in the record as 2026.

    A RANGE RESOLVES TO ITS START. An award covering 2023 to 2026 belongs at
    the point the work began; filing it at the end would put three years of
    effort in the month the certificate was printed.

    Returns "" when there is genuinely nothing to parse. Empty and honest
    beats today's date wearing a disguise.
    """
    import datetime as _dt
    import re as _re

    raw = (raw or "").strip()
    if not raw:
        return ""

    # Already correct -- the common case once the model gets it right.
    m = _re.match(r"^(\\d{4})-(\\d{2})-(\\d{2})$", raw)
    if m:
        return raw
    m = _re.match(r"^(\\d{4})-(\\d{2})$", raw)
    if m:
        return f"{raw}-01"
    if _re.match(r"^\\d{4}$", raw):
        return f"{raw}-01-01"

    months = {mn: i for i, mn in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"], 1)}
    found = []
    for pat, kind in (
        (r"\\b(\\d{1,2})\\s+([A-Za-z]{3,9})\\s+(\\d{4})\\b", "dmy"),
        (r"\\b([A-Za-z]{3,9})\\s+(\\d{1,2}),?\\s+(\\d{4})\\b", "mdy"),
        (r"\\b(\\d{4})-(\\d{2})-(\\d{2})\\b", "iso"),
    ):
        for mm in _re.finditer(pat, raw):
            try:
                if kind == "dmy":
                    d, mo, y = int(mm.group(1)), months[mm.group(2).lower()[:9]], int(mm.group(3))
                elif kind == "mdy":
                    mo, d, y = months[mm.group(1).lower()[:9]], int(mm.group(2)), int(mm.group(3))
                else:
                    y, mo, d = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
                if 1960 <= y <= _dt.date.today().year + 1:
                    found.append(_dt.date(y, mo, d))
            except (ValueError, KeyError):
                continue
    if found:
        # The EARLIEST, which is the start of a range -- see the note above.
        return min(found).isoformat()

    # A bare "August 2023" with no day.
    mm = _re.search(r"\\b([A-Za-z]{3,9})\\s+(\\d{4})\\b", raw)
    if mm and mm.group(1).lower()[:9] in months:
        return f"{int(mm.group(2)):04d}-{months[mm.group(1).lower()[:9]]:02d}-01"

    return ""
'''
s = s.rstrip("\n") + "\n" + FN
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("portfolio.py: normalise_when() added")

# --- 2. every write goes through it ----------------------------------------
D = "app/db.py"
d = io.open(D, encoding="utf-8").read()
OLD = "def portfolio_add(username: str, entry: dict, source_kind: str = \"\","
assert OLD in d, "portfolio_add not found"
i = d.index(OLD)
# Insert normalisation as the first statement of the function body.
body_start = d.index(":\n", d.index(")", i)) + 2
# Skip an existing docstring if there is one.
rest = d[body_start:]
import re as _re
m = _re.match(r'(\s*(?:"""|\'\'\')(?:.|\n)*?(?:"""|\'\'\')\n)', rest)
insert_at = body_start + (len(m.group(1)) if m else 0)
NEW = '''    # THE DATE THE RECORD SORTS BY MUST BE A DATE. The model answers this
    # field in prose often enough -- "17 August 2023 to 15 July 2026" -- and
    # stored raw it fell through every reader to the row's created timestamp,
    # so an award earned in 2023 showed up in the record as 2026 with nothing
    # reporting a problem. Normalised here, at the one door every entry comes
    # through, rather than leniently in each reader where one would forget.
    from . import portfolio as _pf
    if isinstance(entry, dict) and entry.get("happened_on"):
        entry = dict(entry)
        entry["happened_on"] = _pf.normalise_when(entry["happened_on"])
'''
d = d[:insert_at] + NEW + d[insert_at:]
io.open(D, "w", encoding="utf-8", newline="\n").write(d)
print("db.py: portfolio_add normalises happened_on")
