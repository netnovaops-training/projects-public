"""One award per file, one state per award, and a markdown that round-trips.

Jason, 2026-09-06: "I want to give her a MD file that she can export or
import ... For each individual award or promotion ... do not put all the
MD files into one."

TWO HALVES THAT MUST NOT BE CONFUSED
--------------------------------------
knowledge/awards/<id>.md is the REFERENCE: what the award is, who may
enter, what is still unverified. It is research, it changes rarely, and
it is the same for anyone reading it.

The targets table is HER STATE: whether she is chasing it, what she has
done, what is next. It changes constantly and belongs to her.

export_markdown() glues them into one file she can read, hand to ChatGPT,
or edit on a plane. import_markdown() reads that file back and updates
ONLY her half.

WHY THE IMPORT IGNORES THE REFERENCE HALF
An edited copy that has been through another tool is not a trustworthy
source for the eligibility rules -- a model asked to "tidy this up" will
cheerfully smooth `[POLICY UNVERIFIED]` into a confident sentence, and
that is precisely the failure this project keeps guarding against. So the
reference half is regenerated from disk on every export and discarded on
every import. Only what is between the state markers can come back in.

THE MARKERS ARE LOAD-BEARING
Her half sits between two HTML comments. They are comments so they render
as nothing in every markdown viewer, ChatGPT included, and survive being
copied through a chat window -- which is the actual path this file takes.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config, db

AWARDS_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "awards"

BEGIN = "<!-- CASEY:STATE:BEGIN -- everything below is yours; edit freely -->"
END = "<!-- CASEY:STATE:END -->"

STATUSES = ["considering", "chasing", "submitted", "won", "not_this_year",
            "closed"]

STATUS_LABEL = {
    "considering": "Considering",
    "chasing": "Working on it",
    "submitted": "Submitted",
    "won": "Won",
    "not_this_year": "Not this cycle",
    "closed": "Closed to me",
}

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_KV = re.compile(r'^([a-z_]+):\s*(.*)$')


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1].replace('\\"', '"')
    return v


def _parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = {}, text
    m = _FM.match(text)
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            kv = _KV.match(line.strip())
            if kv:
                meta[kv.group(1)] = _unquote(kv.group(2))
    meta["body"] = body.strip()
    meta.setdefault("id", path.stem)
    meta.setdefault("name", path.stem)
    meta.setdefault("tier", "5")
    meta.setdefault("status", "open")
    try:
        meta["tier"] = int(meta["tier"])
    except (TypeError, ValueError):
        meta["tier"] = 5
    return meta


_cache: dict = {"at": 0.0, "data": {}}


def all_awards(refresh: bool = False) -> dict:
    """{id: reference}. Read from disk, cached briefly.

    Cached rather than read per request because the dropdown, the export
    and the action API all want the whole set, and it is 39 small files.
    """
    import time as _t
    if refresh or _t.time() - _cache["at"] > 60:
        data = {}
        if AWARDS_DIR.is_dir():
            for p in sorted(AWARDS_DIR.glob("*.md")):
                if p.stem.lower() == "readme":
                    continue
                try:
                    a = _parse(p)
                    data[a["id"]] = a
                except Exception:  # noqa: BLE001 -- one bad file is not all of them
                    continue
        _cache["data"] = data
        _cache["at"] = _t.time()
    return _cache["data"]


def get(award_id: str) -> dict:
    return all_awards().get(award_id, {})


def listing() -> list[dict]:
    """Everything, with her state attached — what the dropdown renders.

    Ordered the way she would pick: named targets first, then open ones,
    then credentials, and the closed doors last. A dropdown sorted
    alphabetically would put a closed award above her flagship.
    """
    states = db.target_all()
    rank = {"target": 0, "open": 1, "credential": 2, "closed": 3}
    out = []
    for a in all_awards().values():
        st = states.get(a["id"], {})
        out.append({
            "id": a["id"],
            "name": a["name"],
            "tier": a["tier"],
            "kind": a["status"],
            "flagship": str(a.get("flagship", "")).lower() == "true",
            "nominator_required": str(a.get("nominator_required", "")).lower() == "true",
            "gate": a.get("gate", ""),
            "blocked_on": a.get("blocked_on", ""),
            "my_status": st.get("status", ""),
            "next_action": st.get("next_action", ""),
            "updated_at": st.get("updated_at"),
            "updated_via": st.get("updated_via", ""),
        })
    out.sort(key=lambda r: (rank.get(r["kind"], 9), not r["flagship"],
                            r["tier"], r["name"]))
    return out


# ---------------------------------------------------------------------------
#  The markdown that goes out and comes back
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
#  What a single award file has to carry into a cold chat window
# ---------------------------------------------------------------------------

# Read from the profile at export time rather than hard-coded, because it
# has already been wrong once: the file said Major for weeks and every
# draft opened "Maj Owner" until her own citation contradicted it.
# ---------------------------------------------------------------------------
#  Her grade, read once; the award's requirement, read from the award
# ---------------------------------------------------------------------------
#
#  This was baked into 45 files and it should never have been. A fact
#  about HER lived in files about AWARDS, so a promotion cost 45 edits and
#  the day one was missed she had a file telling her the wrong thing about
#  her own eligibility. It happened twice in one afternoon.
#
#  Now: the award states which grade it is FOR (stable -- Field Grade
#  Officer of the Quarter will always want a Field Grade officer), her
#  grade lives in one line of 10-profile.md, and the gate is worked out
#  where it is shown.

_GRADE_CACHE = {"at": 0.0, "v": ""}


def my_grade() -> str:
    """'fgo' | 'cgo' | '' -- from the one line in her profile."""
    import time as _t
    if _t.time() - _GRADE_CACHE["at"] < 60 and _GRADE_CACHE["v"]:
        return _GRADE_CACHE["v"]
    grade = ""
    try:
        from . import llm as _llm
        for p in _llm.knowledge_files():
            if not p.name.startswith("10-"):
                continue
            t = p.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"\*\*Officer category:\*\*\s*\*?\*?([^\n*.]+)", t)
            if m:
                v = m.group(1).lower()
                grade = "fgo" if "field" in v else ("cgo" if "company" in v else "")
            break
    except Exception:  # noqa: BLE001
        pass
    _GRADE_CACHE.update({"at": _t.time(), "v": grade})
    return grade


def gate_for(a: dict) -> dict:
    """Is THIS award open to her at the grade she holds today?

    Returns {open, why}. "any" awards are open on grade -- most of the
    catalog has no grade split at all, and pretending otherwise would put
    a warning on 41 files that do not need one.
    """
    want = (a.get("grade_for") or "any").lower()
    mine = my_grade()
    if want == "any" or not mine:
        return {"open": True, "prepare": False, "why": ""}
    if want == mine:
        return {"open": True, "prepare": False, "why": ""}
    if want == "fgo":
        # NOT SIMPLY A CLOSED DOOR. She is Major-select and pins later this
        # year, so this is the one she should be building the record for
        # right now -- starting from nothing on the day she pins is how a
        # whole cycle gets missed. Said as "prepare", not "no".
        return {"open": False, "prepare": True,
                "why": "Field Grade — opens when you pin on Major, later "
                       "this year. Build the record for it NOW; the first "
                       "cycle after pinning comes round fast."}
    return {"open": False, "prepare": False,
            "why": "This is a COMPANY GRADE award and she is Field Grade. "
                   "It closed when she pinned on Major -- look for the Field "
                   "Grade version, which usually has the same name."}


def _who_she_is() -> dict:
    import re as _re
    from . import llm as _llm
    out = {"name": "", "rank": "", "grade": "", "unit": ""}
    try:
        for p in _llm.knowledge_files():
            if not p.name.startswith("10-"):
                continue
            t = p.read_text(encoding="utf-8", errors="replace")
            for key, pat in (
                    ("name", r"\*\*How she is referred to in drafts:\*\*\s*`?([^`\n—]+)"),
                    ("rank", r"\*\*Rank / grade:\*\*\s*\*?\*?([^\n*]+)"),
                    ("grade", r"\*\*Officer category:\*\*\s*\*?\*?([^\n*.]+)"),
                    ("unit", r"\*\*Unit:\*\*\s*([^\n]+)")):
                m = _re.search(pat, t)
                if m:
                    # Trim trailing punctuation: the profile lines end in
                    # their own full stops and commas, and the sentence
                    # built from them added another -- "Captain (O-3)..",
                    # "99th Medical Group,.".
                    out[key] = m.group(1).strip().strip("*` ").rstrip(" .,;:")
            break
    except Exception:  # noqa: BLE001
        pass
    return out


def _grade_gate(a: dict) -> str:
    """Whether THIS award is open to her at the grade she holds today.

    Computed from her profile and the award's own grade_for, rather than
    read out of prose baked into the file -- see gate_for().
    """
    g = gate_for(a)
    if not g["open"]:
        return "**NOT OPEN TO HER AT HER CURRENT GRADE.** " + g["why"]
    return ("Open to her at her current grade. Still confirm the category on "
            "submission: several awards exist in both versions under identical "
            "names, and the wrong one is returned unscored.")


def _grade_gate_old(a: dict) -> str:
    body = (a.get("body") or "")
    if "NOT open to her yet" in body:
        return ("**This award is FIELD GRADE and is NOT open to her yet.** She "
                "is a Captain. It opens the day she pins on Major. If you draft "
                "for it anyway, say clearly at the top that it cannot be "
                "submitted yet.")
    if "COMPANY GRADE target and it is OPEN" in body:
        return ("**This award is COMPANY GRADE and is open to her now.** That is "
                "the category to submit in.")
    return ("Confirm the category before submitting. Several awards exist in "
            "both Company Grade and Field Grade versions under identical names, "
            "and the wrong one is returned unscored.")


def _chatgpt_briefing(a: dict) -> str:
    """The header that makes one award file usable on its own.

    Everything here is a fact that changes the OUTPUT rather than
    background colour. A model that does not know her grade drafts into a
    category that returns the package; one that does not know the register
    writes narrative prose onto a bullet form.
    """
    me = _who_she_is()
    fmt = (a.get("format") or "").strip()
    register = {
        "1206": "AF Form 1206 BULLETS. Two lines each, action–impact–result, "
                "no first person, quantified, acronyms defined on first use. "
                "Not prose.",
        "narrative": "NARRATIVE PROSE, third person, in the nominator's voice. "
                     "Recent work only — these bodies look at the last 12–18 "
                     "months, not a career. Numbers inside sentences, not as "
                     "fragments.",
        "afms-package": "BOTH a narrative and a bullet version, because AFMS "
                        "packages usually want both. Before/after data is the "
                        "part that cannot be written later.",
        "story": "A STORY SOMEONE ELSE TELLS about one moment — a patient, a "
                 "family member, a colleague. Their words. NO metrics; numbers "
                 "are the wrong register here entirely.",
        "promotion": "NOT a submission. A board reads the record she has "
                     "already built, so the useful work is material her rater "
                     "can lift into a report.",
        "credential": "Not written, obtained. It appears later as a Whole "
                      "Airman line — and 'certifies others' is a bullet where "
                      "'certified' is only a line.",
    }.get(fmt, "No specific register is recorded for this target.")

    return "\n".join([
        "> ## Read this first if you are ChatGPT",
        ">",
        "> This is one award from a serving officer's own career portal. She "
        "may paste it here alone, with nothing else. Everything below is real.",
        ">",
        f"> **Who she is:** {me.get('name') or 'Capt Foster'} — "
        f"{me.get('rank') or 'Captain (O-3)'}. "
        f"{me.get('grade') or 'Company Grade Officer (CGO)'}."
        + (f" {me['unit']}." if me.get("unit") and "FILL IN" not in me["unit"] else ""),
        ">",
        f"> **Grade gate on this one:** {_grade_gate(a)}",
        ">",
        f"> **How this one is written:** {register}",
        ">",
        "> **Five rules that decide whether her work is wasted:**",
        "> 1. Write the rank she held AT THE TIME. Her Meritorious Service "
        "Medal covers Aug 2023 – Jul 2026 as a **Captain**. Pinning on Major "
        "later does not make her a Major in 2024.",
        "> 2. Her Master's in Women's Health is **in progress**. Never write "
        "it as held.",
        "> 3. Never widen scope. One unit is one unit. A unit-level result "
        "described as service-wide is the most common reason a package comes "
        "back.",
        "> 4. Never invent a number, a date or an award name. If a figure is "
        "missing, say so and ask her.",
        "> 5. Keep patient-identifying detail out entirely.",
        ">",
        "> **Working with her:** ask one question at a time — she does this in "
        "gaps, between shifts. The most useful thing you can do is push for "
        "numbers: \"how many?\" and \"over what period?\" beat any amount of "
        "rewriting.",
        ">",
        "> **Going back:** edit only the section marked MY PROGRESS at the "
        "bottom, and keep the `award_id` line at the top. She uploads this "
        "same file to her portal and only that section is read back in — so "
        "she can move between here and there as often as she likes without "
        "losing either side.",
    ])


def export_markdown(award_id: str) -> str:
    a = get(award_id)
    if not a:
        raise KeyError(award_id)
    st = db.target_get(award_id)
    # EACH FILE HAS TO STAND ALONE IN A CHAT WINDOW.
    #
    # Jason, 2026-09-06: "make sure the different .md for each award and
    # promotion is fully tailored to each one ready to export with chatgpt
    # ... and that she can go seamlessly between the two."
    #
    # She will paste ONE of these into a fresh chat, with no portal, no
    # knowledge base and no memory of the last conversation behind it. So
    # each carries the small number of facts that decide whether the
    # resulting draft is usable: who she is TODAY, the grade gate on this
    # particular award, and the register this particular award is written
    # in. Without them a model writes fluent prose that gets the package
    # returned -- and it is her name on it, not the model's.
    #
    # These are regenerated on every export, so a correction to the
    # profile reaches every award file the next time she downloads one.
    lines = [
        f"# {a['name']}",
        "",
        f"`award_id: {award_id}`",
        "",
        _chatgpt_briefing(a),
        "",
        "> This file has two halves. Everything above the line marked "
        "**MY PROGRESS** is reference — it is regenerated from the portal "
        "every time you export, so edits to it are discarded on import. "
        "Everything below that line is yours, and comes back in when you "
        "upload this file.",
        "",
        "---",
        "",
        "## Reference",
        "",
        a.get("body", "").strip(),
        "",
        "---",
        "",
        "## MY PROGRESS",
        "",
        BEGIN,
        "",
        f"**Status:** {st.get('status') or 'considering'}",
        f"*(one of: {', '.join(STATUSES)})*",
        "",
        "**Next action:**",
        "",
        (st.get("next_action") or "").strip() or "_(nothing written yet)_",
        "",
        "**Notes:**",
        "",
        (st.get("notes") or "").strip() or "_(nothing written yet)_",
        "",
        "**Who needs to nominate me / who I have asked:**",
        "",
        (st.get("owner_note") or "").strip() or "_(nothing written yet)_",
        "",
        "**Dates I have confirmed myself:**",
        "",
        (st.get("deadline_note") or "").strip() or "_(nothing written yet)_",
        "",
        END,
        "",
    ]
    # NOTHING GOES AFTER END. See the note on `stamp` above for why: a
    # line here becomes her answer the first time a marker fails to
    # survive a trip through a chat window.
    return "\n".join(lines)


_FIELD_RE = {
    "status": re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.M),
}

_SECTIONS = [
    ("next_action", "Next action"),
    ("notes", "Notes"),
    ("owner_note", "Who needs to nominate me / who I have asked"),
    ("deadline_note", "Dates I have confirmed myself"),
]

_PLACEHOLDER = re.compile(r"^_?\(nothing written yet\)_?$", re.I)


def parse_markdown(text: str) -> dict:
    """Pull her half back out of an edited file.

    Tolerant on purpose. This file will have been through a chat window,
    a phone keyboard and possibly a model that reflowed it, so anything
    that insists on exact formatting will fail on the normal case. What
    it will NOT do is guess: a section it cannot find is left alone
    rather than blanked, because silently erasing her notes because a
    heading lost its bold is a far worse outcome than ignoring an edit.
    """
    out = {}
    aid = re.search(r"award_id:\s*([a-z0-9-]+)", text)
    if aid:
        out["award_id"] = aid.group(1)

    body = text
    if BEGIN in text and END in text:
        body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    elif "MY PROGRESS" in text:
        body = text.split("MY PROGRESS", 1)[1]
    # STRIP COMMENTS WHATEVER SURVIVED. When only one of the two markers
    # comes back -- which is what happened in testing, BEGIN lost and END
    # kept -- the split above cannot bracket the block, and the last
    # field then swallows the leftover `<!-- CASEY:STATE:END -->` and saves
    # it as her answer. Removing every comment costs nothing: none of
    # them is ever content.
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)

    m = _FIELD_RE["status"].search(body)
    if m:
        v = m.group(1).strip().strip("`*_").lower().replace(" ", "_")
        if v in STATUSES:
            out["status"] = v

    # FIND EVERY HEADING FIRST, THEN SLICE BETWEEN THEM.
    #
    # The obvious implementation -- one regex per field, capturing up to
    # the next `**` -- has a failure that is worse than not parsing at
    # all. Strip the bold off ONE heading (which a chat window or a model
    # reflow does routinely) and the field above it captures its own text
    # PLUS the whole orphaned section, then writes that back as her
    # answer. Caught in testing: losing the bold on "Notes" made
    # "Next action" swallow the notes.
    #
    # Locating all the headings first means a heading that lost its
    # formatting still acts as a boundary, so the damage from a mangled
    # file is a field not updated rather than two fields corrupted.
    marks = []
    for key, heading in _SECTIONS:
        h = re.escape(heading)
        pat = re.compile(r"^[ \t]*(?:\*\*|__)?" + h + r":?(?:\*\*|__)?[ \t]*$",
                         re.M | re.I)
        m2 = pat.search(body)
        if m2:
            marks.append((m2.start(), m2.end(), key))
    # Any other bold line is a boundary too, even one we do not know --
    # it is still not part of the answer above it.
    for m2 in re.finditer(r"^[ \t]*\*\*.+?\*\*[ \t]*$", body, re.M):
        if not any(s <= m2.start() < e for s, e, _ in marks):
            marks.append((m2.start(), m2.end(), None))
    marks.sort()
    for i, (start, end, key) in enumerate(marks):
        if key is None:
            continue
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        val = body[end:stop].strip()
        val = re.sub(r"^\*\(one of:.*?\)\*\s*", "", val).strip()
        if not val or _PLACEHOLDER.match(val):
            continue
        out[key] = val
    return out


def import_markdown(text: str, via: str = "upload", username: str = "",
                    award_id: str = "") -> dict:
    """Read an edited file back in. Returns what changed."""
    parsed = parse_markdown(text)
    aid = award_id or parsed.pop("award_id", "")
    parsed.pop("award_id", None)
    if not aid:
        raise ValueError(
            "That file does not say which award it is for. The line "
            "`award_id: ...` near the top is how it is recognised -- keep it "
            "when editing.")
    if aid not in all_awards():
        raise ValueError(f"There is no award called {aid!r}.")
    if not parsed:
        return {"award_id": aid, "changed": [], "why":
                "Nothing in that file was different from what is already saved."}
    before = db.target_get(aid)
    db.target_set(aid, via=via, username=username, **parsed)
    changed = [k for k, v in parsed.items()
               if str((before or {}).get(k) or "") != str(v)]
    return {"award_id": aid, "changed": changed,
            "why": f"Updated {', '.join(changed)}." if changed
                   else "Nothing was different."}
