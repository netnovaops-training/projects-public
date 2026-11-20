#!/usr/bin/env python3
"""A stat row on the portfolio page, with the count-up. Run from Casey/.

Jason, 2026-09-07, twice: "for the portfolio page use this code for the
numbers."

The count-up had nowhere to go. "Where things stand" is prose -- sentences
from progress_lines() -- and the only bare number on the page was
`unmirrored`, which appears solely when something has failed to archive.
Applying an animation to that would mean the page counts up only when
something is wrong.

So the page gets the thing the technique is actually for: a row of counts
that answers "where am I" at a glance, before the sentences explain it.

FOUR NUMBERS, and each is chosen because it changes what she does next:

  entries      how much is in the record at all
  with a number  entries carrying a real figure. This is the one that
               decides packages -- a board reads numbers, and an entry
               without one is a story
  archived     how many reached Paperless, so "working copy only" is
               visible as a count rather than as a status word
  still asking  open [NEEDED:] markers. The work left, in one number

WHAT IS NOT HERE: a percentage or a score. roadmap.py already refuses to
produce one, and for a good reason written down there -- a readiness
percentage that ignored her grade once reported "7 of 7 ready" for an award
a Captain cannot enter. Counts state a fact; a score implies a judgement the
page has not earned.

THE REAL NUMBER STAYS IN THE DOM on every one of them, as the span's own
text. The animation paints over it. Selectable, copyable, and read correctly
by a screen reader -- which matters here more than anywhere, because these
are the figures that get pasted into a 1206.
"""
import io
import sys

# --- 1. the counts ----------------------------------------------------------
P = "app/main.py"
s = io.open(P, encoding="utf-8").read()
if '"stat_entries"' in s:
    sys.exit("already patched")

OLD = '''        "progress": portfolio.progress(),
        "progress_lines": portfolio.progress_lines(),'''
NEW = '''        "progress": portfolio.progress(),
        "progress_lines": portfolio.progress_lines(),
        # THE STAT ROW (2026-09-07). Counts, not a score: roadmap.py refuses
        # to produce a readiness percentage and says why -- one that ignored
        # her grade once reported "7 of 7 ready" for an award a Captain
        # cannot enter. A count states a fact; a score implies a judgement.
        #
        # Computed over the WHOLE record, not the filtered `rows` above, so
        # the numbers do not change meaning when she picks a category.
        **portfolio.stat_counts(),'''
assert OLD in s, "portfolio context not found"
s = s.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("main.py: stat counts passed to the template")

# --- 2. computing them ------------------------------------------------------
Q = "app/portfolio.py"
q = io.open(Q, encoding="utf-8").read()
FN = '''

# --- the four numbers on the portfolio page ---------------------------------

def stat_counts() -> dict:
    """Counts for the stat row. Four facts, no score.

    Jason asked for the count-up animation "for the numbers" on this page,
    and the page had none -- "Where things stand" is prose, and the only
    bare figure was `unmirrored`, which only appears when something has
    FAILED to archive. Animating that would count up only when something is
    wrong.

    Each of these changes what she does next:
      entries       how much is in the record at all
      quantified    entries carrying a real figure -- the one that decides
                    packages, because a board reads numbers and an entry
                    without one is a story
      archived      how many reached Paperless, so "working copy only" is a
                    count rather than a status word
      asking        open [NEEDED:] markers -- the work left, in one number

    Over the WHOLE record rather than the current filter, so the numbers do
    not quietly change meaning when she picks a category.
    """
    import re as _re
    rows = db.portfolio_list(limit=2000)
    num = _re.compile(r"\\d")
    need = _re.compile(r"\\[(NEEDED|FILL IN)", _re.I)

    quantified = asking = 0
    for r in rows:
        blob = " ".join(str(r.get(f) or "") for f in
                        ("situation", "task", "action", "result", "evidence"))
        # A number anywhere in the substance of the entry. Deliberately
        # generous: a date is a number too, and an entry with a date is
        # further along than one with nothing.
        if num.search(" ".join(str(r.get(f) or "") for f in ("result", "action"))):
            quantified += 1
        asking += len(need.findall(blob))

    return {
        "stat_entries": len(rows),
        "stat_quantified": quantified,
        "stat_archived": max(0, len(rows) - db.portfolio_unmirrored()),
        "stat_asking": asking,
    }
'''
if "def stat_counts" not in q:
    q = q.rstrip("\n") + "\n" + FN
    io.open(Q, "w", encoding="utf-8", newline="\n").write(q)
    print("portfolio.py: stat_counts() added")

# --- 3. the row itself ------------------------------------------------------
T = "app/templates/portfolio.html"
t = io.open(T, encoding="utf-8").read()
OLDT = '''  <h2 style="margin-top:0">Where things stand</h2>'''
NEWT = '''  <h2 style="margin-top:0">Where things stand</h2>

  {#
    THE NUMBERS, COUNTING UP. Jason, 2026-09-07: "for the portfolio page use
    this code for the numbers."

    The real value is the span's own text and the animation paints over it,
    so every one of these stays selectable, copyable and readable by a
    screen reader. That matters more here than anywhere else on the site:
    these are the figures that get pasted into a 1206.
  #}
  <div class="statrow">
    <div><span class="tally" style="--n:{{ stat_entries }}">{{ stat_entries }}</span>
      <em>{{ 'entry' if stat_entries == 1 else 'entries' }}</em></div>
    <div><span class="tally" style="--n:{{ stat_quantified }}">{{ stat_quantified }}</span>
      <em>carry a number</em></div>
    <div><span class="tally" style="--n:{{ stat_archived }}">{{ stat_archived }}</span>
      <em>archived</em></div>
    {% if stat_asking %}
    <div><span class="tally" style="--n:{{ stat_asking }}">{{ stat_asking }}</span>
      <em>still asking</em></div>
    {% endif %}
  </div>
  <style>
    .statrow { display:flex; flex-wrap:wrap; gap:1.6rem; margin:.9rem 0 1.1rem; }
    .statrow > div { display:flex; flex-direction:column; }
    .statrow .tally { font-size:1.6rem; font-weight:600; line-height:1.05;
                      font-variant-numeric:tabular-nums; }
    .statrow em { font-style:normal; font-size:.68rem; color:var(--muted);
                  text-transform:uppercase; letter-spacing:.07em; }
  </style>
'''
assert OLDT in t, "Where things stand heading not found"
t = t.replace(OLDT, NEWT, 1)
io.open(T, "w", encoding="utf-8", newline="\n").write(t)
print("portfolio.html: stat row added")
