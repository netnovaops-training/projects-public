#!/usr/bin/env python3
"""One-time split: 30-awards-catalog.md -> knowledge/awards/<id>.md

Jason, 2026-09-06: "give full mark downs for each pin and award ... do not
put all the MD files into one. make them individually".

AFTER THIS RUNS, THE INDIVIDUAL FILES ARE THE SOURCE. This script is the
transcription, not a generator to re-run -- running it again would
overwrite whatever she or anyone else has since edited. It stays in the
repo as the record of where each file came from.

Every [POLICY UNVERIFIED], [VERIFY] and [NEEDED] marker from the catalog
is carried through deliberately. Dropping them while reformatting would
turn "we could not confirm this" into "this is confirmed", which is the
one failure mode this whole project keeps guarding against.

Closed doors get files too. Knowing an award is shut -- and why -- is
worth a file, because otherwise it gets re-researched every few months.

Run from Casey/.
"""
import io
import os
import re
from pathlib import Path

OUT = Path("knowledge/awards")

# (id, name, tier, status, fields...)
#   status: target | open | closed | credential
A = []


def add(id, name, tier, status, **kw):
    A.append(dict(id=id, name=name, tier=tier, status=status, **kw))


# --------------------------------------------------------------- Tier 1 AFMS
AFMS_NOTE = (
    "`[POLICY UNVERIFIED]` AFMS nomination deadlines, submission format and "
    "routing are not published openly. Get them from the Chief Nurse or the "
    "MTF awards monitor.\n\n"
    "Cycle: calendar-year performance, winners announced February-March, which "
    "implies MTF suspenses roughly October-December. That is *inference*, not "
    "published policy.")

add("afms-clinical-excellence-nursing-fgo",
    "USAF Clinical Excellence in Nursing Award — Field Grade Nurse of the Year",
    1, "target", flagship=True, body="""
**This is the flagship target.** The clinical nursing award for an O-4, in the
Field Grade category specifically.

Note the category hard: several AFMS awards exist in both Company Grade and
Field Grade versions with identical names. A package filed in the Company Grade
category is returned unscored.
""", why_fits="Clinical nursing excellence as a Field Grade officer — the "
              "closest match in the catalog to what she actually does.",
    note=AFMS_NOTE)

add("afms-nursing-leadership",
    "USAF Outstanding Excellence in Nursing Leadership Award",
    1, "open", body="""
Senior nursing leadership — flight commander, element chief, chief nurse.

Skews toward Lt Col in practice, but **no rank bar was found**. A strong Major
in a leadership billet is a plausible if uphill nominee. Worth entering if she
holds a leadership billet; not worth reshaping the record around.
""", why_fits="Leadership billet holders. Uphill for a new Major but not barred.",
    note=AFMS_NOTE)

add("afms-force-development",
    "USAF Outstanding Achievement in Nursing Force Development Award",
    1, "open", body="""
Force development, readiness, and training-pipeline roles.
""", why_fits="Fits if she holds readiness, training or force-development duties.",
    note=AFMS_NOTE)

add("afms-nursing-educator", "USAF Nursing Educator of the Year",
    1, "open", body="""
Formal instructor or faculty billets.

Note the instructor-versus-provider rule that runs through this whole catalog:
holding a credential is a Whole Airman line, *certifying others* is a bullet.
An instructor card on S.T.A.B.L.E., NRP or fetal monitoring is what makes this
award reachable.
""", why_fits="Requires a formal teaching role. Instructor cards feed it.",
    note=AFMS_NOTE)

add("afms-operational-research",
    "USAF Outstanding Achievement in Operational Research Award",
    1, "target", body="""
Open beyond nursing — fits a nurse leading a clinical research or
quality-improvement effort.

**The QBL work could plausibly feed this** if it was structured as a QI project
with before/after data. That conditional is the whole thing: getting the
before/after numbers is worth more here than any amount of rewriting.
""", why_fits="QI and research work. The QBL project is the candidate, IF the "
              "outcome data exists.",
    note=AFMS_NOTE)

# --------------------------------------------------------------- Tier 2 MHS
add("mhs-nursing-leadership-midgrade",
    "MHS Military Nursing Leadership Excellence Award — Midgrade",
    2, "open", body="""
Tri-service plus USPHS. Categories are Junior / **Midgrade** / Senior for
military nominees. **A Major competes in Midgrade.**

2025 winners were announced 29 May 2026.

**Strategic implication, and it is the useful part of this file:** evidence
suggests **AFMS wins feed MHS nominations** — the same officer won the AFMS
nursing leadership award and the MHS senior award in 2025. So the route in is
winning at AFMS level first. This is not a parallel application, it is a
downstream one.

`[POLICY UNVERIFIED]` Nomination process, deadline and format were not published.
""", why_fits="Midgrade category is hers. Reached through an AFMS win rather "
              "than applied to directly.")

# --------------------------------------------------------------- Tier 3 wing
add("fgo-quarter", "Field Grade Officer of the Quarter",
    3, "target", body="""
**The cheapest first win, and where the habit should be built.** Four attempts a
year and the shortest feedback loop of anything in this catalog.

- Category is explicitly **"Maj through the rank of Lt Col"** — she competes
  head-to-head against Lieutenant Colonels. As a brand-new Major she is at the
  bottom of her own category, which is exactly why scope escalation matters so
  much in her drafts.
- Ladder: Squadron → Group → Wing → NAF → MAJCOM → Air Force. Winning each tier
  feeds the next. For a nurse in an MTF the squadron is typically Medical
  Operations or Medical Support, rolling up through the Medical Group.
- Vehicle: **AF Form 1206.**
- Typical eligibility gates (locally variable — always check the wing
  instruction): held the grade more than six months during the period; minimum
  time in unit; meets fitness standards; no open UIF or pending action.
- Typical timing: packages due around the **25th-26th of the month following**
  the close of the period.

The 1206 is needed anyway, and a win feeds everything above it.
""", why_fits="Her category exactly. Highest frequency, lowest cost of entry.")

add("fgo-year", "Field Grade Officer of the Year",
    3, "open", body="""
The annual version of the quarterly award, same category and same 1206 vehicle.

Annual boards and announcements are typically in **February**. Quarterly wins
during the year are the normal route to being competitive here.
""", why_fits="Same category as the quarterly. Fed by quarterly wins.")

add("sijan", "Lance P. Sijan USAF Leadership Award — Senior Officer",
    3, "open", body="""
The most significant Air Force-level individual leadership award realistically
in play. Four categories; **a Major competes in Senior Officer (major through
colonel)**.

**This is not theoretical — the 2026 Senior Officer winner was a Major.**

Winners are authorised the Air and Space Recognition Ribbon.

`[POLICY UNVERIFIED]` A historical 30 August Air Force-level suspense is cited
in an older instruction. Confirm the current date before relying on it.
""", why_fits="Senior Officer category includes Major. Precedent exists for a "
              "Major winning it.")

# --------------------------------------------------------------- Tier 4 orgs
AMSUS_NOTE = """
**Self-nomination is not permitted. Someone else must nominate her.** This is an
action item, not a form to fill in — she needs to ask a supervisor early, months
before the window, not in November.

AMSUS recognises **recent impactful accomplishments within the past 12-18
months**, not a career retrospective. Pick recent work.

`[POLICY UNVERIFIED]` The deadline could not be retrieved (the site blocked
automated access). Check amsus.org directly. The 2026 cycle closed 20 Nov 2025
after an extension, so the next cycle is the live target.
"""

for aid, aname, fit in [
    ("amsus-nursing", "AMSUS Nursing Award",
     "The direct nursing category."),
    ("amsus-rising-star", "AMSUS Rising Star Award",
     "Early-career recognition — check the eligibility window against her "
     "commissioning date."),
    ("amsus-innovator", "AMSUS Innovator Award",
     "Fits process or practice innovation. The QBL work is the candidate."),
    ("amsus-operational-medicine", "AMSUS Operational Medicine Award",
     "Operational and readiness contributions."),
    ("amsus-research-development", "AMSUS Research & Development Award",
     "Research output. Needs a structured project with data."),
    ("amsus-training-education", "AMSUS Training and Education Award",
     "Teaching and training contributions. Instructor cards feed this."),
]:
    add(aid, aname, 4, "open", body=AMSUS_NOTE, why_fits=fit,
        nominator_required=True)

add("awhonn-excellence", "AWHONN Awards of Excellence",
    4, "target", body="""
The professional body for her exact specialty. Seven categories: **Leadership,
Clinical Education, Scholarly Education, Practice, Research, Global Health,
Innovation.** Two of them — **Practice** and **Innovation** — are close to a
description of the QBL work.

## The gate is a three-year clock, and it is the most consequential fact here

Nominees must be an **active voting AWHONN member for at least three consecutive
years before nomination**, and hold membership through the nomination year.

If she is not already a member, all seven categories are shut to her until three
years after she joins, no matter how good the record gets. **So the action is
not "apply" — it is "join now, so the clock starts."** It costs a membership fee
and nothing else.

If she IS a member, find out **what year she joined**, because that decides
whether September 2027 is open to her or September 2028.

Deadline: **1 September, annually.** The 2026 cycle closed 1 Sep 2026.

Source: awhonn.org (Awards of Excellence).
""", why_fits="Her exact specialty. Practice and Innovation match the QBL work.",
    gate="Three consecutive years of active voting membership before nomination.")

add("march-of-dimes", "March of Dimes Nurse of the Year",
    4, "open", body="""
State and regional chapter programs, with categories that map unusually well
onto her specialty — **Women's Health, Maternal/Obstetric and Neonatal**
categories are common.

The 2026 window ran **4 May – 19 Jul**; it is closed. Next opens around May 2027.
Events are typically November-December.

`[NEEDED: what state is she stationed in?]` — availability and the category list
are state-specific, so this cannot be pinned down until that is answered. It is
also one of the eight blanks still open in `10-profile.md`.

Source: heroesinaction.marchofdimes.org.
""", why_fits="Category list maps directly onto labour and delivery.",
    blocked_on="Which state she is stationed in.")

add("daisy", "DAISY Award for Extraordinary Nurses",
    4, "open", body="""
Facility-based and awarded **continuously** rather than on an annual cycle —
there is no window to miss.

Nominations come from **patients, families, colleagues and physicians**. This is
the one award she essentially cannot package for herself.

**Her MTF must be a DAISY partner facility** for her to be eligible. Confirmed
live at military treatment facilities in 2026 — Naval Hospital Twentynine Palms
awarded it in May 2026, with one winner from maternal-infant nursing.

The right question is **"Is your MTF a DAISY partner?"** — not "do you want to
apply?"
""", why_fits="Continuous nomination, no cycle. Entirely dependent on the MTF "
              "being a partner facility.",
    blocked_on="Whether her MTF is a DAISY partner facility.",
    nominator_required=True)

add("daisy-nurse-leader", "DAISY Nurse Leader Award",
    4, "open", body="""
The leadership variant of the DAISY Award. Same facility-partnership
prerequisite as the main award.
""", why_fits="Leadership variant, same partnership gate.",
    blocked_on="Whether her MTF is a DAISY partner facility.",
    nominator_required=True)

add("sigma-chapter", "Sigma Theta Tau International — chapter awards",
    4, "open", body="""
Chapter-level awards are a **lower-barrier entry point** and usually require
local chapter membership. International-level awards focus on nursing research
and leadership.

See also the credential file for Sigma induction — it is both an awards route
and a genuine pin.
""", why_fits="Lowest barrier of the professional bodies. Chapter membership "
              "is the prerequisite.")

# ------------------------------------------------------- Tier 5 credentials
add("masters-womens-health", "Master's in Women's Health", 5, "credential",
    body="""
**IN PROGRESS. Never state that she holds it.**

Track and cite *progress*: credits completed, clinical hours, expected
completion date. Progress is citable; completion is not, until it is.

This is also the gate that makes Sigma induction plausible, and it is a
prerequisite for the APRN route that would open the Privileged Advanced Practice
Nurse award — though the privileging, not the degree, is the actual gate there.
""", why_fits="Whole Airman material while in progress. Do not overstate it.")

add("rnc-ob", "RNC-OB — Inpatient Obstetric Nursing", 5, "credential",
    body="""
NCC certification, and the core credential for her specialty.

`[VERIFY]` Eligibility hours, renewal cycles and testing windows change — check
nccwebsite.org directly. Do not state a requirement as fact.

`[VERIFY]` No authoritative source was found for a monetary certification
incentive specific to Air Force nurses. Do not claim one exists.
""", why_fits="The core specialty certification. Letters after her name.",
    body_extra="")

add("c-efm", "C-EFM — Electronic Fetal Monitoring", 5, "credential",
    body="""
NCC certification. **Distinct from AWHONN's fetal monitoring *courses*** — this
is a certification with letters after her name, not a course completion.

Commonly held alongside RNC-OB.

`[VERIFY]` Check eligibility and testing windows at nccwebsite.org.
""", why_fits="Certification rather than course completion. Pairs with RNC-OB.")

add("rnc-mnn", "RNC-MNN — Maternal Newborn Nursing", 5, "credential",
    body="""
NCC certification. An alternative or addition to RNC-OB depending on where she
actually works within the unit.

`[VERIFY]` Check eligibility and testing windows at nccwebsite.org.
""", why_fits="Alternative to RNC-OB. Which one fits depends on her actual "
              "duties within the unit.")

add("stable", "S.T.A.B.L.E. — neonatal pre-transport stabilisation",
    5, "credential", body="""
Widely held in labour and delivery. A Provider or Instructor card is common.

**Instructor is the version that reads as leadership.** Where a credential has
both levels, the instructor version is the one that supports the framing her
packages need: "certified" is a Whole Airman line, "certifies others" is a
bullet.

`[VERIFY]` Check requirements with the S.T.A.B.L.E. Program directly.
""", why_fits="Common in her specialty. Take the Instructor level.")

add("nrp", "Neonatal Resuscitation Program", 5, "credential", body="""
Relevant to labour and delivery. Has both provider and instructor levels — take
the instructor level where possible, for the same reason as S.T.A.B.L.E.
""", why_fits="Specialty-relevant. Instructor level is the one that counts.")

add("awhonn-fetal-monitoring",
    "AWHONN Intermediate and Advanced Fetal Monitoring", 5, "credential",
    body="""
Course completions, **not certifications** — see the C-EFM file for the
certification version of this competency. Both are worth holding; only one puts
letters after her name.
""", why_fits="Course completion. C-EFM is the certification equivalent.")

add("acls-bls", "ACLS / BLS", 5, "credential", body="""
Baseline resuscitation credentials. Instructor levels exist and are the version
worth holding.
""", why_fits="Baseline. Instructor level is the differentiator.")

add("sigma-induction", "Sigma Theta Tau International — induction",
    5, "credential", body="""
Both an awards route and a genuine **pin** and credential line.

Nomination is usually chapter-driven and tied to a graduate programme — **her
Master's makes her a candidate.**
""", why_fits="Her Master's makes her eligible. Chapter-driven nomination.",
    nominator_required=True)

add("acsc", "Air Command and Staff College (PME)", 5, "credential", body="""
The developmental education tier matched to O-4.

**In-residence students can earn Distinguished Graduate recognition; distance
learning does not carry it.** That distinction matters when writing it up.
""", why_fits="The O-4 PME tier. DG recognition only via in-residence.")

add("publication-military-medicine",
    "Publication in Military Medicine or a specialty journal", 5, "credential",
    body="""
**Disproportionately valuable and rare among clinical nurses.**

*Military Medicine* is AMSUS's journal, which makes a publication there
doubly useful — it is both a credential line and a connection to the body that
runs six of the awards in this catalog.
""", why_fits="Rare among clinical nurses, so it differentiates hard. Feeds "
              "the AMSUS relationship too.")

add("medical-badge", "Air Force medical badge (Basic / Senior / Chief)",
    5, "credential", body="""
`[POLICY UNVERIFIED]` Medical badge upgrades are tied to time in service and
qualifications, and **the specific year thresholds were not confirmed** in this
research.

Ask the unit training manager rather than relying on a number from here.
""", why_fits="Time-in-service driven. Thresholds unconfirmed — ask the UTM.",
    blocked_on="Confirmed thresholds from her unit training manager.")

# ------------------------------------------------------------------- closed
add("privileged-apn", "USAF Privileged Advanced Practice Nurse of the Year",
    1, "closed", body="""
**Not open to her.** Requires a *privileged* APRN — NP, CNS, CNM or CRNA. A
clinical nurse is not eligible.

This becomes relevant only if she completes an advanced practice degree **and**
is credentialed and privileged at her MTF. **A Master's in Women's Health does
not by itself qualify her — the privileging is the gate.**
""", why_fits="Closed: requires APRN privileging, not just a Master's.")

add("cgo-categories", "Any Company Grade nursing category", 1, "closed",
    body="""
**Closed. She is a Major — Field Grade.**

Several awards exist in both Company Grade and Field Grade versions **with
identical names**. The category, not the name, is what matters. A package filed
in a Company Grade category is returned unscored.

This file exists so that mistake gets caught at the target-picking stage rather
than after submission.
""", why_fits="Closed: Field Grade officer. Category mismatch is fatal.")

add("aerial-achievement-medal", "Aerial Achievement Medal", 3, "closed",
    body="""
**Closed.** Requires assignment to a unit with a flying mission — flight nurse
or CCATT only.
""", why_fits="Closed: requires a flying-mission billet.")

add("aacn-circle-excellence", "AACN Circle of Excellence", 4, "closed",
    body="""
**Closed.** Critical care focused; requires AACN membership *and* a member
nominator. Her specialty routes to AWHONN, not AACN.
""", why_fits="Closed: critical care, wrong specialty body.")

add("prap-competent-medical-authority",
    "PRAP Competent Medical Authority of the Year", 4, "closed", body="""
**Closed.** Nuclear-mission bases only.
""", why_fits="Closed: nuclear-mission bases only.")

add("afa", "Air & Space Forces Association awards", 4, "closed", body="""
**Not useful, despite common assumptions.**

Every AFA field award recognises service *to AFA* — by chapters, states and AFA
volunteers. **There is no AFA national award for medical or nursing
performance.**
""", why_fits="Closed: AFA awards recognise service to AFA, not nursing.")

add("moaa", "MOAA awards", 4, "closed", body="""
**Not useful, despite common assumptions.**

Council/chapter awards and the ROTC awards program only. **No national
individual award for an active-duty officer's professional performance.**

MOAA is useful for scholarships and transition support, not as an awards target.
""", why_fits="Closed: no individual performance award for active duty.")

# ---------------------------------------------------------------------------
TIER_NAME = {
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


def yaml_escape(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    return '"' + s.replace('"', '\\"') + '"'


def write_one(a):
    fm = [
        "---",
        f"id: {a['id']}",
        f"name: {yaml_escape(a['name'])}",
        f"tier: {a['tier']}",
        f"status: {a['status']}",
    ]
    if a.get("flagship"):
        fm.append("flagship: true")
    if a.get("nominator_required"):
        fm.append("nominator_required: true")
    if a.get("gate"):
        fm.append(f"gate: {yaml_escape(a['gate'])}")
    if a.get("blocked_on"):
        fm.append(f"blocked_on: {yaml_escape(a['blocked_on'])}")
    fm.append("---")

    parts = ["\n".join(fm), "", f"# {a['name']}", ""]
    parts.append(f"*{TIER_NAME[a['tier']]}*")
    parts.append("")
    parts.append(f"**{STATUS_LINE[a['status']]}**")
    parts.append("")
    if a.get("why_fits"):
        parts.append(f"**Why it fits her:** {a['why_fits']}")
        parts.append("")
    parts.append(a["body"].strip())
    parts.append("")
    if a.get("note"):
        parts.append("---")
        parts.append("")
        parts.append(a["note"].strip())
        parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(
        "*Split out of `30-awards-catalog.md` on 6 September 2026. Every\n"
        "`[POLICY UNVERIFIED]`, `[VERIFY]` and `[NEEDED]` marker above came\n"
        "from that file and means exactly what it says: confirm it before\n"
        "acting on it. Her own progress against this award is kept in the\n"
        "portal, not in this file.*")
    parts.append("")
    (OUT / f"{a['id']}.md").write_text("\n".join(parts), encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ids = set()
    for a in A:
        assert a["id"] not in ids, f"duplicate id {a['id']}"
        ids.add(a["id"])
        write_one(a)
    # An index, so the directory reads as a catalog rather than a pile.
    lines = ["# Awards and pins — one file each", "",
             "Split out of `30-awards-catalog.md` on 6 September 2026 at "
             "Jason's request. The individual files are the source now; the "
             "old catalog is kept for its calendar and its reasoning.", ""]
    for tier in (1, 2, 3, 4, 5):
        rows = [a for a in A if a["tier"] == tier and a["status"] != "closed"]
        if not rows:
            continue
        lines += [f"## {TIER_NAME[tier]}", ""]
        for a in sorted(rows, key=lambda r: (r["status"] != "target", r["name"])):
            mark = " **(flagship)**" if a.get("flagship") else ""
            lines.append(f"- [{a['name']}]({a['id']}.md){mark}")
        lines.append("")
    closed = [a for a in A if a["status"] == "closed"]
    lines += ["## Closed to her — kept so they are not re-researched", ""]
    for a in sorted(closed, key=lambda r: r["name"]):
        lines.append(f"- [{a['name']}]({a['id']}.md)")
    lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(A)} award files + README to {OUT}")
    for st in ("target", "open", "credential", "closed"):
        print(f"  {st:11s} {sum(1 for a in A if a['status'] == st)}")


if __name__ == "__main__":
    main()
