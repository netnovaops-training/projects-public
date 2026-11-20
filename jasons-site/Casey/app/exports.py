"""The running document: her conversation, in formats that travel.

WHY FOUR FORMATS AND NOT ONE. They are not alternatives, they are
different destinations:

  markdown  the one to hand to ChatGPT. Her subscription carries no API
            access, so nothing here can call it -- the bridge is a clean
            document she pastes or uploads herself, and Markdown is what
            survives that trip with its structure intact. Google Docs
            imports it too.
  docx      what "a document" means to most people, and what Google Docs
            opens natively without an import step.
  xlsx      the same log as a grid, for sorting and filtering.
  csv       what Google Sheets imports directly, with no conversion.

The live Google sync sits behind all of it and turns on only when a
service account is supplied. Until then every button still works and
hands back a file, which is the point: the export must not depend on a
credential that may never arrive.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, db


def _when(ts: float) -> str:
    try:
        tz = ZoneInfo(config.TIMEZONE)
    except Exception:  # noqa: BLE001
        tz = None
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M")


def _rows(session: str = "", since: float = 0.0, limit: int = 5000) -> list[dict]:
    """Oldest first -- a conversation reads forwards."""
    rows = db.qa_list(limit=limit, session=session, since=since)
    return list(reversed(rows))


# --- markdown: the one that goes to ChatGPT ----------------------------------

def as_markdown(session: str = "", since: float = 0.0) -> str:
    rows = _rows(session, since)
    # The portfolio leads: a reviewer should meet what she DID before
    # they meet a transcript of her thinking about it.
    lead = portfolio_markdown()
    out = ([lead, ""] if lead else []) + ["# Career conversation log", ""]
    if rows:
        n = len(rows)
        out.append(f"_{n} exchange{'' if n == 1 else 's'}, "
                   f"{_when(rows[0]['ts'])} to {_when(rows[-1]['ts'])}._")
    else:
        out.append("_No exchanges recorded yet._")
    # A short brief so the document is useful the moment it is opened
    # somewhere else, without anyone having to explain what it is.
    out += ["",
            "> This is a transcript of spoken questions and the answers given,",
            "> kept so the thinking can be followed up rather than lost. Each",
            "> entry records which model answered.", ""]
    day = ""
    for r in rows:
        d = _when(r["ts"]).split(" ")[0]
        if d != day:
            day = d
            out += [f"## {d}", ""]
        out += [f"### {_when(r['ts'])}  ·  {r['question'][:90]}", "",
                f"**Asked** ({r['asked_by']}): {r['question']}", "",
                f"**Answer** ({r['model'] or 'unknown model'}):", "",
                r["answer"] or "_no answer recorded_", "", "---", ""]
    return "\n".join(out)


def write_markdown(path: Path, session: str = "", since: float = 0.0) -> Path:
    path.write_text(as_markdown(session, since), encoding="utf-8")
    return path


# --- csv: what Google Sheets imports without asking --------------------------

def write_csv(path: Path, session: str = "", since: float = 0.0) -> Path:
    rows = _rows(session, since)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["When", "Session", "Asked by", "Question", "Answer",
                    "Model"])
        for r in rows:
            w.writerow([_when(r["ts"]), r["session"], r["asked_by"],
                        r["question"], r["answer"], r["model"]])
    return path


# --- docx / xlsx: the Office pair --------------------------------------------

def write_docx(path: Path, session: str = "", since: float = 0.0) -> Path:
    """A real .docx. Falls back to Markdown beside it if python-docx is
    missing, rather than failing the download outright."""
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:
        alt = path.with_suffix(".md")
        return write_markdown(alt, session, since)
    rows = _rows(session, since)
    doc = Document()
    doc.add_heading("Career conversation log", 0)
    if rows:
        n = len(rows)
        doc.add_paragraph(f"{n} exchange{'' if n == 1 else 's'}, "
                          f"{_when(rows[0]['ts'])} to {_when(rows[-1]['ts'])}.")
    intro = doc.add_paragraph(
        "A transcript of spoken questions and the answers given, kept so "
        "the thinking can be followed up rather than lost. Each entry "
        "records which model answered.")
    intro.runs[0].italic = True
    day = ""
    for r in rows:
        d = _when(r["ts"]).split(" ")[0]
        if d != day:
            day = d
            doc.add_heading(d, level=1)
        doc.add_heading(f"{_when(r['ts'])} — {r['question'][:80]}", level=2)
        q = doc.add_paragraph()
        q.add_run(f"Asked ({r['asked_by']}): ").bold = True
        q.add_run(r["question"])
        a = doc.add_paragraph()
        a.add_run(f"Answer ({r['model'] or 'unknown model'}): ").bold = True
        a.add_run(r["answer"] or "no answer recorded")
        for run in doc.paragraphs[-1].runs:
            run.font.size = Pt(11)
    doc.save(str(path))
    return path


def write_xlsx(path: Path, session: str = "", since: float = 0.0) -> Path:
    """The log as a grid. Falls back to CSV if openpyxl is missing."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
    except ImportError:
        return write_csv(path.with_suffix(".csv"), session, since)
    rows = _rows(session, since)
    wb = Workbook()
    ws = wb.active
    ws.title = "Conversation"
    head = ["When", "Session", "Asked by", "Question", "Answer", "Model"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([_when(r["ts"]), r["session"], r["asked_by"],
                   r["question"], r["answer"], r["model"]])
    for col, width in zip("ABCDEF", (17, 14, 10, 60, 90, 20)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    # A PROGRESS TAB, first thing anyone opening the sheet sees after the
    # log. Generated from the same read the portal panel and Hermes use,
    # so the three can never disagree.
    try:
        from . import portfolio as _pf
        ps = wb.create_sheet("Progress", 0)
        ps.append(["Where things stand"])
        ps["A1"].font = Font(bold=True, size=13)
        ps.append([])
        for line in _pf.progress_lines():
            ps.append([line])
        ps.column_dimensions["A"].width = 110
        for row in ps.iter_rows():
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    except Exception:  # noqa: BLE001
        pass          # a missing tab must never cost her the export
    wb.save(str(path))
    return path


# --- the live Google pair ----------------------------------------------------
#
#  UNVERIFIED UNTIL A SERVICE ACCOUNT EXISTS. Everything above is tested
#  and needs no credentials; this needs a Google Cloud service account
#  whose JSON goes in ZEE_GOOGLE_SA_JSON, with the Doc and the Sheet
#  SHARED WITH THAT ACCOUNT'S EMAIL as an editor. Until then the caller
#  gets a plain "not configured" and the file download instead -- never a
#  stack trace, and never a silent no-op that looks like success.

def google_ready() -> tuple[bool, str]:
    if not config.GOOGLE_SA_JSON:
        return False, ("No Google service account configured. Set "
                       "ZEE_GOOGLE_SA_JSON to the JSON key, share the Doc "
                       "and Sheet with that account's email as an editor, "
                       "and set ZEE_GOOGLE_DOC_ID / ZEE_GOOGLE_SHEET_ID.")
    if not (config.GOOGLE_DOC_ID or config.GOOGLE_SHEET_ID):
        return False, "Service account is set but no Doc or Sheet id given."
    try:
        from google.oauth2 import service_account  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError:
        return False, ("google-api-python-client is not installed in this "
                       "image yet -- rebuild the casey service to add it.")
    return True, "ready"


def _google_services():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    raw = config.GOOGLE_SA_JSON
    info = json.loads(Path(raw).read_text(encoding="utf-8")
                      if raw.startswith("/") else raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/documents",
                      "https://www.googleapis.com/auth/spreadsheets"])
    return (build("docs", "v1", credentials=creds, cache_discovery=False),
            build("sheets", "v4", credentials=creds, cache_discovery=False))


def google_sync(session: str = "", since: float = 0.0) -> tuple[bool, str]:
    """Push the log into the shared Doc and Sheet. Returns (ok, message).

    The Doc is REPLACED rather than appended: a running document that is
    rebuilt from the log cannot drift out of step with it, and drift is
    the failure everybody actually hits with append-only sync.
    """
    ok, why = google_ready()
    if not ok:
        return False, why
    rows = _rows(session, since)
    try:
        docs, sheets = _google_services()
        if config.GOOGLE_DOC_ID:
            meta = docs.documents().get(documentId=config.GOOGLE_DOC_ID).execute()
            end = meta["body"]["content"][-1]["endIndex"] - 1
            reqs = []
            if end > 1:
                reqs.append({"deleteContentRange":
                             {"range": {"startIndex": 1, "endIndex": end}}})
            reqs.append({"insertText": {"location": {"index": 1},
                                        "text": as_markdown(session, since)}})
            docs.documents().batchUpdate(documentId=config.GOOGLE_DOC_ID,
                                         body={"requests": reqs}).execute()
        if config.GOOGLE_SHEET_ID:
            values = [["When", "Session", "Asked by", "Question", "Answer",
                       "Model"]]
            values += [[_when(r["ts"]), r["session"], r["asked_by"],
                        r["question"], r["answer"], r["model"]] for r in rows]
            sheets.spreadsheets().values().clear(
                spreadsheetId=config.GOOGLE_SHEET_ID, range="A:F").execute()
            sheets.spreadsheets().values().update(
                spreadsheetId=config.GOOGLE_SHEET_ID, range="A1",
                valueInputOption="RAW", body={"values": values}).execute()
        db.qa_mark_exported([r["id"] for r in rows])
        return True, f"{len(rows)} exchanges written to Google"
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "google", f"sync failed: {e}")
        return False, f"Google sync failed: {e}"

# --- the portfolio, in the same documents ------------------------------------
#
#  This is the half somebody else actually reads. It leads the document
#  for that reason: a reviewer should meet what she DID before they meet
#  a transcript of her thinking about it.

def portfolio_markdown() -> str:
    rows = db.portfolio_list(limit=500)
    if not rows:
        return ""
    out = ["# Portfolio", "",
           f"_{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}._", ""]
    for e in rows:
        when = e["happened_on"] or _when(e["ts"]).split(" ")[0]
        out += [f"## {e['title'] or 'Untitled'}", "",
                f"*{when} · {e['category']} · {e['status']}"
                + (f" · toward {e['award_target']}" if e["award_target"] else "")
                + "*", ""]
        for label, key in (("Situation", "situation"), ("Task", "task"),
                           ("Action", "action"), ("Result", "result"),
                           ("Evidence", "evidence"), ("Skills", "skills")):
            if e.get(key):
                out += [f"**{label}.** {e[key]}", ""]
        out += ["---", ""]
    return "\n".join(out)


def write_portfolio_csv(path: Path) -> Path:
    rows = db.portfolio_list(limit=500)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["When", "Title", "Category", "Status", "Award target",
                    "Situation", "Task", "Action", "Result", "Evidence",
                    "Skills"])
        for e in rows:
            w.writerow([e["happened_on"] or _when(e["ts"]).split(" ")[0],
                        e["title"], e["category"], e["status"],
                        e["award_target"], e["situation"], e["task"],
                        e["action"], e["result"], e["evidence"], e["skills"]])
    return path
