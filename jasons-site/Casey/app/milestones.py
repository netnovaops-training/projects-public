"""Her career as a rail of ribbon bars: the jacket timeline.

Jason, 2026-09-06: "a milestone timeline for casey showing a graphic to
show highlights as she inputs them ... major ones in red and minor ones
in blue with time stamping and dates ... she can look left and right on
this and she can see them ... like graduation from ROTC and many more."

MAJOR AND MINOR ARE NOT SEVERITY, THEY ARE KIND
A promotion, a pinning, a commissioning, a top-tier award: those change
what she IS, and they are red. A certification, a course, an instructor
card, a quarterly win: those build toward the next one, and they are
blue. That distinction is the whole point of the two colours -- it is
not "important" versus "less important", because the blue ones are what
make the red ones possible.

WHY THE TIMELINE IS ITS OWN TABLE AND NOT DERIVED
Her portfolio holds work she DID. A jacket holds what HAPPENED TO her --
commissioned, promoted, pinned, graduated. They overlap but they are not
the same list, and deriving one from the other would either flood the
timeline with quarterly bullets or lose the day she pinned on Major.
Wins ARE offered up from the portfolio and from her award targets, so
nothing has to be typed twice, but she confirms each one.

DATES ARE THE SPINE, SO PARTIAL DATES ARE HONEST
"2019" and "SEP 2019" and "14 SEP 2019" are all real answers about a
career, and demanding a day she does not remember would mean the entry
never gets made. Precision is stored alongside the date and shown as it
was given -- 2019, SEP 19, or 14SEP19.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime

from . import db

# kind -> (tier, label). Tier decides the colour.
KINDS = {
    # AFJROTC IS NOT AFROTC AND THE DIFFERENCE IS NOT PEDANTRY.
    # AFJROTC is the high-school programme -- citizenship and leadership,
    # and NOT a commissioning source. AFROTC is the college programme that
    # commissions officers. Writing one for the other on her own record
    # reads as not knowing her own path, which is a bad look in the one
    # document where that matters. Both are here, separately.
    "jrotc":       ("minor", "AFJROTC (high school)"),
    "rotc":        ("major", "AFROTC (commissioning programme)"),
    "commission":  ("major", "Commissioning"),
    "promotion":   ("major", "Promotion"),
    "pinned":      ("major", "Pinned on"),
    "select":      ("major", "Selected"),
    "award":       ("major", "Award"),
    "assignment":  ("major", "Assignment"),
    "degree":      ("major", "Degree"),
    # ACADEMIC HONOURS, added 2026-09-07. Jason: "I want to add her honors
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
    "credential":  ("minor", "Credential"),
    "course":      ("minor", "Course"),
    "instructor":  ("minor", "Instructor rating"),
    "quarterly":   ("minor", "Quarterly recognition"),
    "publication": ("minor", "Publication"),
    "membership":  ("minor", "Membership"),
    "other":       ("minor", "Milestone"),
}

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "ROBIN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

_ISO = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def parse_when(raw: str) -> tuple:
    """'2019' | '2019-09' | '2019-09-14' -> (iso, precision).

    Partial dates are kept partial. A career has years somebody remembers
    and days somebody does not, and demanding the day is how the entry
    never gets made at all.
    """
    m = _ISO.match((raw or "").strip())
    if not m:
        return "", ""
    y, mo, d = m.group(1), m.group(2), m.group(3)
    if d:
        return f"{y}-{mo}-{d}", "day"
    if mo:
        return f"{y}-{mo}-01", "month"
    return f"{y}-01-01", "year"


def dtg(iso: str, precision: str) -> str:
    """The date as her world writes it: 14SEP19, SEP 19, or 2019."""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except Exception:  # noqa: BLE001
        return iso[:10]
    if precision == "day":
        return f"{d.day:02d}{MONTHS[d.month - 1]}{str(d.year)[2:]}"
    if precision == "month":
        return f"{MONTHS[d.month - 1]} {d.year}"
    return str(d.year)


def add(username: str, when: str, title: str, kind: str = "other",
        detail: str = "", tier: str = "", until: str = "") -> int:
    """A milestone, which may be a POINT or a SPAN.

    Jason, 2026-09-06: "my sister doesn't do just one thing at a time."
    An assignment runs for years, a degree runs for years, and they
    overlap -- a record of points cannot show that, and the overlap is
    most of what a career actually looks like. `until` is optional: a
    pinning is a day, an assignment is a stretch.
    """
    iso, precision = parse_when(when)
    if not iso:
        raise ValueError("A milestone needs a date: 2019, 2019-09, or 2019-09-14.")
    if not (title or "").strip():
        raise ValueError("A milestone needs a name.")
    kind = kind if kind in KINDS else "other"
    tier = tier if tier in ("major", "minor") else KINDS[kind][0]
    # "OPEN" means she is still doing it. Stored as the literal, because
    # writing today's date would say she finished today -- a different
    # fact, and one that quietly becomes wrong tomorrow.
    until = (until or "").strip()
    if until.upper() == "OPEN":
        u_iso, u_prec = "OPEN", "open"
    else:
        u_iso, u_prec = parse_when(until) if until else ("", "")
    if u_iso and u_iso != "OPEN" and u_iso < iso:
        raise ValueError("That ends before it starts.")
    return db.milestone_add(username, iso, precision, title.strip(), kind,
                            tier, detail.strip(), u_iso, u_prec)


def listing() -> list:
    """Oldest first — a career reads left to right."""
    rows = db.milestone_list()
    out = []
    for r in rows:
        u = (r.get("until_iso") or "").strip()
        out.append({**r,
                    "dtg": dtg(r["when_iso"], r["precision"]),
                    "until_dtg": ("still going" if u == "OPEN"
                                  else (dtg(u, r.get("until_precision") or "month")
                                        if u else "")),
                    "span": bool(u),
                    "label": KINDS.get(r["kind"], KINDS["other"])[1],
                    "year": (r["when_iso"] or "")[:4]})
    return out


def spans() -> dict:
    """First year, last year, and where 'now' sits — the rail's extent."""
    rows = listing()
    this_year = date.today().year
    if not rows:
        return {"first": this_year - 1, "last": this_year + 1, "now": this_year}
    years = [int(r["year"]) for r in rows if r["year"].isdigit()]
    return {"first": min(years + [this_year]),
            "last": max(years + [this_year]),
            "now": this_year}


# ---------------------------------------------------------------------------
#  What she has already told the portal, offered up rather than typed twice
# ---------------------------------------------------------------------------

def suggestions() -> list:
    """Things in her record that look like milestones but are not on the rail.

    OFFERED, NOT ADDED. The portal does not get to decide what her jacket
    says. Each of these is one tap to accept and one to dismiss.
    """
    have = {(r["title"] or "").strip().lower() for r in db.milestone_list()}
    out = []
    for r in db.portfolio_list(limit=200):
        if (r.get("status") or "") != "won":
            continue
        t = (r.get("title") or "").strip()
        if t and t.lower() not in have:
            out.append({"when": (r.get("happened_on") or "")[:10],
                        "title": t, "kind": "award",
                        "detail": (r.get("result") or "")[:200],
                        "from": "a win in your record"})
    try:
        from . import awards
        for a in awards.listing():
            if a.get("my_status") != "won":
                continue
            if a["name"].strip().lower() in have:
                continue
            out.append({"when": "", "title": a["name"], "kind": "award",
                        "detail": "", "from": "an award you marked as won"})
    except Exception:  # noqa: BLE001
        pass
    return out[:12]


# ---------------------------------------------------------------------------
#  Where a career starts
# ---------------------------------------------------------------------------
#
#  Jason, 2026-09-06: "start should start with her in highschool doing
#  AFROTC and move forward to now."
#
#  Her profile carries none of this -- prior degrees, commissioning source
#  and PME are all [FILL IN] -- and fourteen invented milestones were
#  deleted from this rail an hour ago for exactly that reason. So this is
#  a SCAFFOLD, not data: the milestones that open an officer's career, in
#  order, each waiting for a real date from her or from Jason.
#
#  Ordered rather than alphabetical, because the order IS the information.
#  Filling the first one makes the rest obvious.

STARTER = [
    ("jrotc", "AFJROTC, high school",
     "Where it started. Not a commissioning source, but it is a real line "
     "on a Whole Airman record and it shows the length of the commitment."),
    ("rotc", "AFROTC detachment",
     "The college programme. Which detachment, and what year you contracted."),
    ("degree", "BSN conferred",
     "The degree that made you eligible for the Nurse Corps."),
    ("commission", "Commissioned, Second Lieutenant",
     "The day the clock starts on everything else."),
    ("assignment", "First duty assignment",
     "Base and unit."),
    ("promotion", "Promoted to First Lieutenant", ""),
    ("promotion", "Promoted to Captain", ""),
    ("pinned", "Pinned on Major",
     "Her profile says 2026 -- confirm the month."),
]


def starter_gaps() -> list:
    """Which career-opening milestones are still missing.

    Matched loosely on the distinctive word, because she will write
    "Commissioned USAF" or "2d Lt commissioning" rather than the exact
    label offered here, and prompting her twice for something she has
    already entered is how a scaffold becomes an annoyance.
    """
    have = " | ".join((r.get("title") or "").lower() for r in db.milestone_list())
    out = []
    for kind, title, why in STARTER:
        key = {"jrotc": "jrotc", "rotc": "rotc", "degree": "bsn",
               "commission": "commission", "assignment": "assignment",
               "pinned": "major"}.get(kind, title.split()[-1].lower())
        if kind == "promotion":
            key = title.split()[-1].lower()
        if key in have:
            continue
        out.append({"kind": kind, "title": title, "why": why})
    return out


# ---------------------------------------------------------------------------
#  Lanes: the overlap is the point
# ---------------------------------------------------------------------------
#
#  Jason, 2026-09-06: "the time line is horizontal like a line graph
#  showing inner lapping things because my sister doesn't do just one
#  thing at a time."
#
#  He is right, and it is the difference between a list of dates and a
#  picture of a career. Her assignment ran Aug 2023 to Jul 2026. Her
#  Master's is still running. Her MSM covers the same three years. Drawn
#  as points those are three unrelated ticks; drawn as bars they are
#  three overlapping stretches, which is what actually happened.
#
#  PACKED GREEDILY, EARLIEST FIRST. Each span goes in the topmost lane
#  where it does not touch what is already there. That keeps the number
#  of lanes to the real maximum overlap rather than one per item -- and
#  the lane count itself becomes information: three lanes deep means she
#  was doing three things at once that year.

def lanes(pad_days: int = 45) -> dict:
    """Milestones packed into non-overlapping lanes, plus the time window.

    pad_days keeps two spans that merely touch from looking joined, and
    gives a point milestone enough width to be clickable.
    """
    from datetime import date as _d, timedelta as _td

    rows = listing()
    if not rows:
        return {"lanes": [], "first": "", "last": "", "depth": 0}

    def d(iso):
        try:
            return _d.fromisoformat(iso[:10])
        except Exception:  # noqa: BLE001
            return None

    today = _d.today()
    items = []
    for r in rows:
        start = d(r["when_iso"])
        if not start:
            continue
        end = d(r.get("until_iso") or "") or start
        # An OPEN span -- something she is still doing -- runs to today and
        # is marked, because "ongoing" and "ended today" are different
        # facts and the second one would be a lie.
        ongoing = bool(r.get("until_iso") == "OPEN")
        if ongoing:
            end = today
        items.append({**r, "_s": start, "_e": end, "ongoing": ongoing})

    items.sort(key=lambda i: (i["_s"], i["_e"]))
    first = min(i["_s"] for i in items)
    last = max(max(i["_e"] for i in items), today)
    total = max(1, (last - first).days)

    packed = []          # lane index -> end date currently occupying it
    for i in items:
        placed = False
        for n, busy in enumerate(packed):
            if i["_s"] > busy + _td(days=pad_days):
                packed[n] = i["_e"]
                i["lane"] = n
                placed = True
                break
        if not placed:
            packed.append(i["_e"])
            i["lane"] = len(packed) - 1
        i["x"] = round(((i["_s"] - first).days / total) * 100, 3)
        i["w"] = round(max(0.9, ((i["_e"] - i["_s"]).days / total) * 100), 3)
        i["_s"] = i["_s"].isoformat()
        i["_e"] = i["_e"].isoformat()

    # Year gridlines, so the bars sit against something readable.
    years = []
    for y in range(first.year, last.year + 1):
        mark = _d(y, 1, 1)
        if mark < first:
            continue
        years.append({"year": y,
                      "x": round(((mark - first).days / total) * 100, 3)})

    return {"lanes": items, "first": first.isoformat(), "last": last.isoformat(),
            "depth": len(packed), "years": years,
            "now_x": round(((today - first).days / total) * 100, 3)}
