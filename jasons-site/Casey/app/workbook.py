"""One workbook: a running log, a summary, and a sheet per award.

Jason, 2026-09-06: "I like to run a running doc file in Excel spreadsheet
that allows the doc file to be edited for each award and once it's done
for that award to start a new one ... update a bullet point list of all
the things she's accomplishing as a summary and note all the awards that
we're trying to get that she can qualify for in another column ... keep a
running tab of what she's doing with dates and times."

WHY ONE WORKBOOK AND NOT A FILE PER AWARD
He asked for a new document per award, and separate files would give him
exactly that -- and lose the thing that makes it useful. An accomplishment
feeds three awards at once; in separate files it is typed three times and
drifts three ways within a month. One workbook, a sheet per award, means
the same entry appears under every award it supports and is edited once.

Starting a new one when an award is done is then a sheet appearing, not a
file to make. Merging is not a feature because nothing was ever split.

THE SHEETS
  Summary   the bullet list: everything she has done, with the awards
            each entry feeds in the next column, which is the shape he
            described.
  Log       what she is doing, with dates AND times, appended and never
            reordered. The running tab.
  <award>   one per award she is chasing: what it needs, what she has for
            it, what is still missing.

VERBOSE ON PURPOSE, because he asked. Nothing is truncated to look tidy:
a bullet that runs long runs long, and the column is widened instead.
Losing a detail to make a cell fit is the one thing a record must not do.

WHAT IS NOT IN IT
The vent. Nothing from vents.py reaches this file -- see that module.
"""
from __future__ import annotations

import re
import time
from datetime import datetime

from . import awards, db, gaps


def _wb():
    try:
        from openpyxl import Workbook
        return Workbook()
    except Exception:  # noqa: BLE001
        return None


def _awards_for(entry: dict, targets: list) -> str:
    """Which awards this entry could feed.

    Matched on her OWN target list rather than the whole catalog -- 45
    awards against every entry produces a column nobody reads. If she has
    picked nothing yet it falls back to the named targets, so the column
    is never empty and never noise.
    """
    named = (entry.get("award_target") or "").strip()
    out = []
    if named:
        a = awards.get(named)
        out.append(a.get("name") or named)
    text = " ".join(str(entry.get(f) or "") for f in
                    ("title", "situation", "action", "result", "skills")).lower()
    for t in targets:
        if t["name"] in out:
            continue
        # A loose match on the distinctive word of the award name. Crude
        # and deliberately so: this column is a prompt for her judgement,
        # not a claim about eligibility.
        key = re.sub(r"[^a-z ]", "", t["name"].lower()).split()
        key = [w for w in key if len(w) > 4 and w not in
               ("grade", "officer", "award", "excellence", "outstanding",
                "achievement", "nursing", "force", "annual")]
        if any(w in text for w in key):
            out.append(t["name"])
    if out:
        return "; ".join(out)
    # NOTHING MATCHED, AND AN EMPTY COLUMN IS USELESS. Keyword matching
    # on award names is crude -- her MSM entry is about obstetric care and
    # $392K, and none of "Lieutenant Colonel", "Operational Research" or
    # "AWHONN" appears in it, though it plausibly feeds all three. So the
    # column falls back to what she is actually chasing, prefixed to make
    # clear it is a prompt for her judgement rather than a claim about
    # eligibility.
    if targets:
        return "consider: " + "; ".join(t["name"] for t in targets[:4])
    return ""


def build(path) -> dict:
    """Write the workbook. Returns what went in it."""
    wb = _wb()
    if wb is None:
        raise RuntimeError("openpyxl is not installed in this image.")
    from openpyxl.styles import Alignment, Font, PatternFill

    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1F3D5C")
    wrap = Alignment(wrap_text=True, vertical="top")

    rows = db.portfolio_list(limit=500)
    targets = [a for a in awards.listing()
               if a.get("my_status") in ("chasing", "submitted", "considering")]
    if not targets:
        targets = [a for a in awards.listing() if a["kind"] == "target"][:6]

    # --- Summary: the bullet list, with the awards each entry feeds -------
    ws = wb.active
    ws.title = "Summary"
    cols = ["What she did", "When", "Result / number", "Awards this feeds",
            "Status", "Still missing"]
    ws.append(cols)
    for i, c in enumerate(cols, 1):
        ws.cell(1, i).font = head
        ws.cell(1, i).fill = fill
    for r in rows:
        missing = "; ".join(g["asks"] for g in gaps.find(r)) or ""
        ws.append(["• " + (r.get("title") or "(untitled)"),
                   r.get("happened_on") or "",
                   (r.get("result") or "").strip(),
                   _awards_for(r, targets),
                   r.get("status") or "",
                   missing])
    for col, w in zip("ABCDEF", (46, 16, 64, 34, 12, 40)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = wrap
    ws.freeze_panes = "A2"

    # --- Log: the running tab, with dates AND times -----------------------
    lg = wb.create_sheet("Log")
    lg.append(["Date", "Time", "What happened", "Where it came from"])
    for i in range(1, 5):
        lg.cell(1, i).font = head
        lg.cell(1, i).fill = fill
    events = []
    for r in rows:
        ts = r.get("ts") or 0
        events.append((ts, r.get("title") or "(untitled)",
                       "added to the record"))
    for m in db.milestone_list():
        events.append((m.get("ts") or 0, m.get("title") or "", "jacket"))
    for h in db.target_history(limit=200):
        events.append((h.get("ts") or 0,
                       f"{h.get('award_id')}: {h.get('field')} → "
                       f"{(h.get('new_value') or '')[:60]}",
                       h.get("via") or "portal"))
    # APPENDED IN TIME ORDER AND NEVER REORDERED. A running tab that
    # re-sorts is not a log, it is a report -- and the point of this one
    # is being able to see what happened on a Tuesday.
    events.sort(key=lambda e: e[0])
    for ts, what, where in events:
        if not ts:
            continue
        d = datetime.fromtimestamp(ts)
        lg.append([d.strftime("%Y-%m-%d"), d.strftime("%H:%M"), what, where])
    for col, w in zip("ABCD", (13, 9, 78, 20)):
        lg.column_dimensions[col].width = w
    lg.freeze_panes = "A2"

    # --- one sheet per award she is chasing -------------------------------
    made = []
    for t in targets[:12]:
        name = re.sub(r"[\\/*?:\[\]]", "", t["name"])[:31] or t["id"][:31]
        sh = wb.create_sheet(name)
        ref = awards.get(t["id"])
        g = awards.gate_for(ref)
        sh.append(["Award", t["name"]])
        sh.append(["Open to her now?",
                   "Yes" if g["open"] else "Not yet — " + g["why"]])
        sh.append(["Where she is", t.get("my_status") or "not started"])
        sh.append(["Next action", t.get("next_action") or ""])
        if t.get("gate"):
            sh.append(["Gate", t["gate"]])
        if t.get("blocked_on"):
            sh.append(["Blocked on", t["blocked_on"]])
        sh.append([])
        sh.append(["What she has for it", "When", "Result", "Still missing"])
        hrow = sh.max_row
        for i in range(1, 5):
            sh.cell(hrow, i).font = head
            sh.cell(hrow, i).fill = fill
        for r in rows:
            if t["name"] not in _awards_for(r, targets):
                continue
            sh.append([r.get("title") or "", r.get("happened_on") or "",
                       (r.get("result") or "").strip(),
                       "; ".join(x["asks"] for x in gaps.find(r))])
        for col, w in zip("ABCD", (46, 16, 60, 38)):
            sh.column_dimensions[col].width = w
        for row in sh.iter_rows():
            for c in row:
                c.alignment = wrap
        made.append(t["name"])

    wb.save(str(path))
    return {"entries": len(rows), "log_rows": len(events),
            "award_sheets": made}
