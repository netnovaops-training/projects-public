#!/usr/bin/env python3
"""Date an entry by the document, not by the upload. Run from Casey/.

Jason, 2026-09-07: "when importing PDFs, Word and other things, will the
original creation exif data be preserved, or if it's an essay or letter will
the date be read?"

Neither, until now, and it produced a visible wrong answer. Her Air and
Space Commendation Medal covers 17 August 2023 to 15 July 2026, and the
entry the portal wrote for it reads:

    ### 07 Sep 2026 -- Award of Air and Space Commendation Medal

07 September 2026 is the day she uploaded it. `worker.py` passed
`_now_local()` as the date, so every entry is stamped with when it was
FILED rather than when it HAPPENED -- and a career record sorted by filing
date tells you the order she got round to things, which is not a fact
anybody wants.

PAPERLESS ALREADY GETS THIS RIGHT and is worth copying rather than
reinventing: Tika reads the embedded metadata and Paperless dates from it.
Measured today -- the CIS 111 .docx records `dcterms:created
2022-01-11T16:27Z` and Paperless dated the document 2022-01-11 exactly.

FOUR SOURCES, MOST TRUSTWORTHY FIRST. The order is the whole design:

  1. EMBEDDED METADATA -- PDF `/CreationDate`, docx `dcterms:created`.
     Written by the software that made the file, at the moment it was made.
     Nobody typed it and nobody can misremember it.

  2. EXIF DateTimeOriginal -- for photographs, and only where the instance
     has EXIF_DATES on. That is Jason's, not Casey's, and the reason is in
     config.py: she photographs certificates years after the award, so her
     capture date is when she found the frame.

  3. A DATE IN THE TEXT -- the essay-or-letter case he asked about. Real
     dates on a page ("17 August 2023", "January 11, 2022") beat a file
     timestamp, because a document that was re-saved in 2026 still says on
     its face when it was written. So this is tried BEFORE falling back,
     and the EARLIEST plausible date is taken -- a citation names its
     period start first and its signature date last.

  4. TODAY, and only then. Marked as a fallback in the log so a wrongly
     dated entry can be found later rather than looking deliberate.

WHAT THIS DOES NOT DO: it does not overrule her. The date lands in the
draft, and the draft is hers to correct. Being roughly right and visible
beats being confidently wrong and invisible.
"""
import io
import sys

P = "app/llm.py"
s = io.open(P, encoding="utf-8").read()
if "def document_date" in s:
    sys.exit("already patched")

CODE = '''
# --- when was this actually written? -----------------------------------------

# Dates as they appear on real documents. Ordered longest-first so
# "17 August 2023" is not matched as "8/2023" by a shorter pattern.
_DATE_PATTERNS = [
    (r"\\b(\\d{1,2})\\s+(January|February|March|April|May|June|July|August|"
     r"September|October|November|December)\\s+(\\d{4})\\b", "dmy"),
    (r"\\b(January|February|March|April|May|June|July|August|September|"
     r"October|November|December)\\s+(\\d{1,2}),?\\s+(\\d{4})\\b", "mdy"),
    (r"\\b(\\d{4})-(\\d{2})-(\\d{2})\\b", "iso"),
    (r"\\b(\\d{1,2})/(\\d{1,2})/(\\d{4})\\b", "us"),
]
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def _dates_in_text(text: str) -> list:
    """Every plausible date on the page, oldest first.

    THE EARLIEST IS USUALLY THE RIGHT ONE for the documents this sees. A
    citation names the period it covers before it names the day it was
    signed; a letter is dated at the top. Taking the earliest is not always
    right, but it is right more often than taking the last thing on the page,
    which is typically a print date or a footer.
    """
    import datetime as _dt
    import re as _re
    out = []
    for pat, kind in _DATE_PATTERNS:
        for m in _re.finditer(pat, text[:20000], _re.I):
            try:
                if kind == "dmy":
                    d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
                elif kind == "mdy":
                    mo, d, y = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
                elif kind == "iso":
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                else:
                    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                # A career record has no dates before living memory and none
                # in the future. Both filters catch OCR noise reliably.
                if not (1960 <= y <= _dt.date.today().year):
                    continue
                out.append(_dt.date(y, mo, d))
            except (ValueError, KeyError):
                continue
    return sorted(set(out))


def _embedded_date(path):
    """The date the FILE says it was created. The most trustworthy source.

    Written by the software that made the document, at the moment it was
    made -- nobody typed it and nobody can misremember it. This is what
    Paperless uses via Tika, and it dated the CIS 111 docx correctly to
    2022-01-11 from exactly this field.
    """
    import datetime as _dt
    import re as _re
    suf = path.suffix.lower()
    try:
        if suf == ".pdf":
            from pypdf import PdfReader
            info = PdfReader(str(path)).metadata or {}
            raw = str(info.get("/CreationDate") or "")
            # PDF dates are "D:YYYYMMDDHHmmSS+ZZ'zz'"
            m = _re.match(r"D?:?(\\d{4})(\\d{2})(\\d{2})", raw)
            if m:
                return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif suf in (".docx", ".xlsx", ".pptx"):
            import zipfile
            with zipfile.ZipFile(path) as z:
                core = z.read("docProps/core.xml").decode("utf-8", "replace")
            m = _re.search(r"<dcterms:created[^>]*>(\\d{4})-(\\d{2})-(\\d{2})", core)
            if m:
                return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:  # noqa: BLE001
        pass
    return None


def document_date(path, text: str = "") -> tuple:
    """(date, where it came from). Never guesses silently.

    Four sources, most trustworthy first -- see this module's notes. The
    caller decides what to do with a weak answer; this only reports which
    kind it found.
    """
    import datetime as _dt

    d = _embedded_date(path)
    if d:
        return d, "the file's own creation date"

    if config.EXIF_DATES:
        e = read_exif(path) or {}
        taken = e.get("taken", "")
        if len(taken) == 10:
            try:
                y, m, dd = (int(x) for x in taken.split("-"))
                return _dt.date(y, m, dd), "the photograph's capture date"
            except ValueError:
                pass

    # The essay-or-letter case: a document re-saved last week still says on
    # its face when it was written, so the text beats a file timestamp that
    # has been touched since.
    found = _dates_in_text(text or "")
    if found:
        return found[0], "a date written in the document"

    return _dt.date.today(), "today (nothing in the document said otherwise)"

'''

ANCHOR = "# --- what a photograph knows about itself ---"
assert ANCHOR in s, "exif section anchor not found"
s = s.replace(ANCHOR, CODE.lstrip("\n") + "\n" + ANCHOR, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("llm.py: document_date() added")

# --- worker uses it ---------------------------------------------------------
W = "app/worker.py"
w = io.open(W, encoding="utf-8").read()
OLD = """    task = (_tpl or TASK_PROMPTS[mode]).format(
        date=_now_local().strftime("%d %b %Y"),"""
NEW = """    # DATE THE ENTRY BY THE DOCUMENT, NOT BY THE UPLOAD. This passed
    # _now_local() until 2026-09-07, so her 2023 Commendation Medal was
    # written up as "07 Sep 2026" -- the day she happened to upload it. A
    # career record sorted by filing date tells you the order she got round
    # to things, which is not a fact anybody wants.
    #
    # document_date() tries the file's own creation metadata first, then a
    # photograph's capture date, then a date written on the page, and only
    # then today. Whichever it used is logged, so a wrong date can be found
    # later rather than looking deliberate.
    _doc_date, _date_src = llm.document_date(Path(job["stored_path"]), combined) \\
        if job.get("stored_path") else (_now_local().date(), "today")
    db.log_event("info", f"job:{job_id}", f"dated from {_date_src}: {_doc_date}")
    task = (_tpl or TASK_PROMPTS[mode]).format(
        date=_doc_date.strftime("%d %b %Y"),"""
assert OLD in w, "task format call not found"
w = w.replace(OLD, NEW, 1)
if "from pathlib import Path" not in w:
    w = w.replace("import re", "import re\nfrom pathlib import Path", 1)
io.open(W, "w", encoding="utf-8", newline="\n").write(w)
print("worker.py: entries dated from the document")
