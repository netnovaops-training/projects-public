#!/usr/bin/env python3
"""Promotion targets, career-field additions, and the LANGUAGE each output needs.

Jason, 2026-09-06: "one For future lieutenant Colonel as well as any
promotions as a medical officer and anything else in her career field ...
she chooses the output ... split out the correct output for that award
and the language it needs to be put out in."

THE LANGUAGE IS THE POINT AND IT IS NOT COSMETIC.
The same accomplishment is written four different ways depending on where
it is going. A 1206 wants a two-line bullet with no pronouns. AMSUS wants
narrative prose about the last 12-18 months. DAISY wants a story someone
else tells about her. A promotion board wants a career trajectory. Feed a
board the 1206 bullets and it reads as thin; feed the 1206 the narrative
and it does not fit on the form.

So every award file now carries a `format:` field and a "How this must be
written" section, and render.py uses them.

WHAT THIS SCRIPT WILL NOT DO IS INVENT PROMOTION POLICY.
Air Force officer promotion mechanics -- board timing, time-in-grade
gates, opportunity rates, the current performance-brief format -- change,
and getting one wrong would send her into a board on a false premise. Every
number below is marked and routed to the authority that actually owns it:
her MPF, her commander, AFPC, or the Nurse Corps functional. What IS said
here is the part that does not change: what a board reads, and how a
record has to be built over years rather than weeks.

Run from Casey/. Idempotent for the new files; appends format sections once.
"""
import io
import re
from pathlib import Path

OUT = Path("knowledge/awards")

# ---------------------------------------------------------------------------
#  The formats. Each award points at one of these by name.
# ---------------------------------------------------------------------------
FORMATS = {
    "1206": """
## How this must be written — AF Form 1206 bullet format

The 1206 is a **bullet** form, not a narrative one, and the bullet has a fixed
internal shape:

**ACTION — IMPACT — RESULT.** What she did, what it changed, what came of it.
A bullet with an action and no result is the single most common weak bullet.

Hard rules:
- **No first person.** Not "I led", not "my team". The subject is her rank and
  name, implied.
- **Two lines maximum per bullet**, and the second line is indented. A bullet
  that runs to three lines gets cut by whoever types it up, and they will cut
  the result.
- **Quantify or lose it.** "Improved handoff process" is invisible next to
  "cut missed handoff items 40%, 1.2K pt encounters".
- **Define every acronym on first use.** The board is not all nurses.
- Standard AF bullet shortenings are expected — `pt` for patient, `K` for
  thousand, `--` as the connector.

Sections the form asks for: **Leadership and Job Performance**, then
**Whole Airman** (base and community involvement, self-improvement, PME,
volunteering).

`[VERIFY LOCALLY]` Character-per-line limits, the exact section headings, and
how many bullets per section are set by the **wing instruction** and vary by
installation. Get the current template from the awards monitor before writing
to a limit. Do not treat any number here as the local rule.
""",

    "narrative": """
## How this must be written — narrative nomination

Prose, not bullets. Third person throughout — this is written *about* her,
usually by the person nominating her.

- **The window is recent.** These bodies recognise impact in roughly the last
  **12-18 months**, not a career retrospective. A strong thing from four years
  ago weakens the package by dating it.
- **One thread, not a list.** A narrative that tries to cover everything reads
  as a résumé. Pick the strongest piece of work and follow it through: what the
  problem was, what she did, what changed, who else it reached.
- **Numbers live inside sentences here**, not as fragments. "Missed handoff
  items fell by 40% across 1,200 patient encounters in the following quarter"
  rather than a bullet.
- **Name the scope honestly.** A unit-level change described as service-wide is
  the failure that gets a package returned. If it was one MTF, say one MTF —
  a well-evidenced unit-level result beats an inflated one.
- Someone else's voice. If a supervisor is signing it, it must sound like them.
""",

    "afms-package": """
## How this must be written — AFMS award package

`[POLICY UNVERIFIED]` The AFMS submission format and routing are **not
published openly**. The Chief Nurse or MTF awards monitor holds the current
template. Do not build a package to a format guessed from here.

What is safe to prepare regardless of the template:
- The **narrative** version of the accomplishment (see the narrative rules).
- The **bullet** version, because most AF packages want both.
- **Before/after data.** Every AFMS clinical and research award turns on
  measurable outcome, and the data is the part that cannot be written later.
- **Category discipline.** Field Grade, never Company Grade. Same names, and a
  package filed in the wrong one is returned unscored.
""",

    "story": """
## How this must be written — a story someone else tells

This is the one she cannot package for herself, and writing it like a package
is what makes it fail.

- **The nominator is a patient, family member, colleague or physician.** Their
  voice, their words, their memory of a specific moment.
- **One moment, not a summary.** "She stayed past shift change and explained
  the monitor readings to my husband until he stopped being frightened" beats
  any paragraph about dedication.
- **No metrics.** Numbers are the wrong register here entirely.
- What she can do: make sure the people around her know the nomination exists
  and how to submit one. That is the whole action.
""",

    "promotion": """
## How this must be written — a promotion record, not a package

A board does not read a submission. It reads **the record she has already
built**, so the writing happens years earlier, in the performance reports and
the decorations that accumulate.

- **Trajectory beats any single year.** Boards read for a slope: increasing
  scope, increasing responsibility, jobs that got harder.
- **Stratification language is what carries.** Where a rater has placed her
  against her peers is read closely, and it is written by someone else — which
  makes the relationship with her rater part of the preparation.
- **Developmental education is a gate, not a bonus.** See the ACSC file.
- **Gaps are read as loudly as content.** A missing year, an unexplained
  non-competitive assignment, or a thin Whole Airman line all register.
- Everything in this portal feeds this indirectly: awards, credentials and
  quantified results are the raw material her rater needs to write a strong
  report. She cannot write the report; she can make it easy to write.

`[VERIFY WITH MPF / AFPC]` Board timing, time-in-grade and time-in-service
gates, promotion opportunity rates, and the current performance-brief format
all change and are **not stated here on purpose**. Her MPF, her commander and
the Nurse Corps functional own those answers. Getting one wrong from a
secondary source is worse than not having it.
""",

    "credential": """
## How this is written — it mostly is not

A credential is obtained, not submitted. The writing happens later, when it
appears in a package:

- **On a 1206:** a Whole Airman bullet. "Certified" is one line.
- **On a narrative:** context for authority, not an achievement in itself.
- **Instructor beats provider, every time.** Where both levels exist, the
  instructor version is what supports leadership framing. "Certified" is a
  Whole Airman line; **"certifies others" is a bullet.**

Record the date obtained and the expiry, because renewal windows are the thing
that gets missed.
""",
}

# ---------------------------------------------------------------------------
#  New files: promotion and career-field additions
# ---------------------------------------------------------------------------
NEW = [
    dict(id="promotion-o5-lt-col", name="Promotion to Lieutenant Colonel (O-5)",
         tier=0, status="target", fmt="promotion", flagship=True,
         why="The next promotion. Everything else in this portal is raw "
             "material for the record a board will read.",
         body="""
This is the long target, and the one that is *not* an application.

**What a board actually reads** is the record already built — performance
reports, decorations, the jobs she has held and the order she held them in.
Nothing written the month before a board changes it. That is why the log in
this portal matters more than any single package: it makes her rater's job
easy, and her rater writes the thing the board reads.

## What moves the needle, in rough order

1. **Trajectory.** Increasing scope across assignments. A board reads for a
   slope, not a peak.
2. **Stratification.** Where her rater ranks her against peers. This is written
   by someone else, which makes the rater relationship part of the preparation
   rather than a soft skill.
3. **Developmental education.** Air Command and Staff College is the tier
   matched to O-4 — see `acsc.md`. In-residence carries Distinguished Graduate
   recognition; distance learning does not.
4. **Awards.** Not for their own sake — a wing-level or AFMS win is external
   evidence a rater can point at, which is worth more than the same claim
   unsupported.
5. **Whole Airman.** Volunteering, additional duties, community. Thin here is
   noticed.
6. **The Master's**, once finished. In progress it is a trajectory line; held,
   it is a gate cleared. Never state it as held before it is.

## What this portal should be feeding it

Every quantified result in her log is a sentence her rater can lift. Every
credential is a line. Every award win is external corroboration. The point of
two minutes a week is that in three years there is something to write from.

`[VERIFY WITH MPF / AFPC / NURSE CORPS FUNCTIONAL]` Time in grade, time in
service, board convening dates, opportunity rates, and the current performance
brief format are **deliberately not stated here**. They change, and a wrong
number from a secondary source is worse than no number. Ask the MPF.
"""),

    dict(id="promotion-o6-colonel", name="Promotion to Colonel (O-6) — the long view",
         tier=0, status="open", fmt="promotion",
         why="Two promotions out. Listed because some of what it needs has to "
             "start now, not later.",
         body="""
Listed not because it is near, but because **parts of it have long lead times**
and starting them at O-5 is late.

- **Intermediate and senior developmental education.** The sequence matters and
  the windows are narrow.
- **Breadth of assignment.** Staff time, joint time, or a headquarters tour is
  commonly part of the profile. These are assignment decisions made years ahead.
- **Advanced degree completed**, not in progress.
- **Sustained award record**, not a single win.

The useful action at Major is not to chase this. It is to notice which
assignments build breadth and which do not, and to raise that in career
conversations early.

`[VERIFY WITH MPF / AFPC]` Everything about O-6 boards, gates and timing.
Nothing here is a policy statement.
"""),

    dict(id="opr-epb-performance-report",
         name="Officer performance report — the thing boards actually read",
         tier=0, status="open", fmt="promotion",
         why="Not an award, but the highest-leverage document in her career. "
             "Everything in this portal exists partly to feed it.",
         body="""
The single most consequential document she does not write herself.

**She cannot write it. She can make it easy to write.** A rater with a folder
of quantified results writes a strong report; a rater with nothing writes a
generic one, and generic reads as weak at a board.

## The practical action

- Keep a **running list of quantified results** — this portal is that list.
- Give the rater the material **before** the report is due, not after they ask.
- Push for **specifics over adjectives** in her own input. "Dedicated" is
  filler; "cut missed handoff items 40%" is not.
- Watch the **scope language**. A rater writing generously can overstate scope,
  and that is her risk to carry at a board, not theirs.

`[VERIFY WITH MPF]` Current form, cycle, static close-out dates and the
stratification rules in force. These have changed more than once and are not
stated here.
"""),

    dict(id="qbl-project", name="The QBL work — her strongest single asset",
         tier=0, status="target", fmt="afms-package",
         why="Named repeatedly across the catalog as the thing most likely to "
             "win something, IF the outcome data exists.",
         body="""
This is not an award. It is the piece of work that several awards in this
catalog are waiting on, which is why it gets its own file.

It is named as a candidate for:
- **AFMS Outstanding Achievement in Operational Research** — if it was
  structured as a QI project with before/after data.
- **AMSUS Innovator** and **AMSUS Research & Development**.
- **AWHONN Practice** and **AWHONN Innovation** — two of the seven categories
  are close to a description of it.

## The whole thing turns on one question

**Does the before/after data exist?**

If it does, this is the strongest single asset in her record and several
packages can be built from it. If it does not, it is a good story with no
evidence, and every one of the awards above weakens accordingly.

**Getting those numbers is worth more than any amount of rewriting.** If they
were never captured, the next best action is to start capturing now — a
partial forward-looking dataset beats none.

## What to record here

- What the problem was, in numbers, before.
- What changed, and when exactly.
- What the numbers were after, and over what period.
- Who else adopted it, and at what level. (Scope, honestly stated.)
- Anyone who would corroborate it.
"""),

    dict(id="publication-route", name="Getting published — the rare differentiator",
         tier=5, status="open", fmt="narrative",
         why="Rare among clinical nurses, so it separates her from the field "
             "more than another certification would.",
         body="""
Expanded from the credential line because it is a *route*, not a box to tick.

**Military Medicine** is AMSUS's journal, which makes a publication there do
two jobs: a credential line, and a relationship with the body running six of
the awards in this catalog.

## The realistic path from where she is

1. The **QBL work**, written up as a QI project, is the obvious candidate —
   see `qbl-project.md`. QI writeups are a normal journal format and do not
   require a research degree.
2. A **case report** or clinical practice piece in a specialty journal
   (obstetric or neonatal nursing) is a lower bar than an original study.
3. **Co-authorship** counts. Joining someone else's project is a legitimate and
   much faster route than leading one.

`[VERIFY]` Submission requirements, review timelines and any DoD or MTF public
release clearance requirement. **Military and MTF-affiliated work usually
requires public affairs or command clearance before submission** — confirm the
local process before sending anything out.
"""),

    dict(id="volunteer-whole-airman", name="Whole Airman — volunteering and community",
         tier=5, status="open", fmt="1206",
         why="An explicit section on the 1206 and read at boards. Thin here is "
             "noticed, and it is the easiest section to fix.",
         body="""
Not an award, but a scored section on the 1206 and part of what a board reads.

**This is the cheapest section to be strong in and the most commonly thin.**

What counts:
- Base and community volunteering, with hours and what came of it.
- Additional duties held within the unit.
- Professional organisation involvement — which doubles as the AWHONN and Sigma
  membership those awards require.
- Self-improvement: PME, degree progress, certifications.

Written as bullets, same action-impact-result shape as everything else on the
form. "Volunteered at X" is weak; "organised Y for Z families, raised $N" is a
bullet.

`[NEEDED]` `10-profile.md` still has `[FILL IN]` on additional duties and
volunteering. Those two lines are worth more to a package than most of this
catalog.
"""),
]

TIER_NAME = {
    0: "Promotion and the record a board reads",
    1: "Tier 1 — Air Force Medical Service annual awards",
    2: "Tier 2 — DoD / Military Health System",
    3: "Tier 3 — Wing and installation recognition",
    4: "Tier 4 — Professional organisations",
    5: "Tier 5 — Credentials and pins that feed packages",
}

STATUS_LINE = {
    "target": "A named target. Worth building the record around.",
    "open": "Open to her. Worth entering when the record supports it.",
    "closed": "CLOSED to her. This file exists so it is not re-researched.",
    "credential": "A credential or pin — something she can go and get, "
                  "rather than be nominated for.",
}

# Which existing files get which format.
ASSIGN = {
    "1206": ["fgo-quarter", "fgo-year", "sijan"],
    "afms-package": ["afms-clinical-excellence-nursing-fgo",
                     "afms-nursing-leadership", "afms-force-development",
                     "afms-nursing-educator", "afms-operational-research",
                     "mhs-nursing-leadership-midgrade"],
    "narrative": ["amsus-nursing", "amsus-rising-star", "amsus-innovator",
                  "amsus-operational-medicine", "amsus-research-development",
                  "amsus-training-education", "awhonn-excellence",
                  "march-of-dimes", "sigma-chapter"],
    "story": ["daisy", "daisy-nurse-leader"],
    "credential": ["masters-womens-health", "rnc-ob", "c-efm", "rnc-mnn",
                   "stable", "nrp", "awhonn-fetal-monitoring", "acls-bls",
                   "sigma-induction", "acsc", "publication-military-medicine",
                   "medical-badge"],
}


def write_new(a):
    fm = ["---", f"id: {a['id']}", f'name: "{a["name"]}"',
          f"tier: {a['tier']}", f"status: {a['status']}",
          f"format: {a['fmt']}"]
    if a.get("flagship"):
        fm.append("flagship: true")
    fm.append("---")
    parts = ["\n".join(fm), "", f"# {a['name']}", "",
             f"*{TIER_NAME[a['tier']]}*", "",
             f"**{STATUS_LINE[a['status']]}**", "",
             f"**Why it fits her:** {a['why']}", "",
             a["body"].strip(), "",
             FORMATS[a["fmt"]].strip(), "", "---", "",
             "*Written 6 September 2026. Every `[VERIFY]` and `[POLICY\n"
             "UNVERIFIED]` marker means exactly what it says. Her own progress\n"
             "against this is kept in the portal, not in this file.*", ""]
    (OUT / f"{a['id']}.md").write_text("\n".join(parts), encoding="utf-8")


def add_format(award_id, fmt):
    p = OUT / f"{award_id}.md"
    if not p.exists():
        return False
    s = p.read_text(encoding="utf-8")
    if "## How this must be written" in s or "## How this is written" in s:
        return False
    # frontmatter gets format:
    if "\nformat:" not in s.split("---")[1]:
        s = s.replace("\nstatus:", f"\nformat: {fmt}\nstatus:", 1)
    marker = "\n---\n\n*Split out of"
    block = "\n" + FORMATS[fmt].strip() + "\n"
    s = s.replace(marker, block + marker, 1) if marker in s else s + block
    p.write_text(s, encoding="utf-8")
    return True


def main():
    for a in NEW:
        write_new(a)
    print(f"wrote {len(NEW)} new promotion/career files")
    n = 0
    for fmt, ids in ASSIGN.items():
        for i in ids:
            n += bool(add_format(i, fmt))
    print(f"added format guidance to {n} existing files")


if __name__ == "__main__":
    main()
