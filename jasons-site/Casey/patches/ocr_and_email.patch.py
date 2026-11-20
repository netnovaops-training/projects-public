#!/usr/bin/env python3
"""Read scans automatically, and accept email. Run from Casey/.

Jason, 2026-09-07: "the ocr did not catch and I want to be able to read
emails and docx docs files ... I don't want her to be going back and forth
and having me diagnose these problems."

THE REAL FAULT WAS THE DESIGN, NOT THE EXTRACTION. When a PDF had no text
layer the portal stopped and told her to go and upload it somewhere else,
under Documents, so the archive's OCR could read it first. That is the
system handing its own routing problem to the person using it -- and it is
worse than it sounds, because she is the one person here who should never
have to know that "Log an accomplishment" and "Documents" run different
pipelines. Jason then gets asked to diagnose it. Every time.

So the scan gets read where it was dropped.

WHY GEMINI AND NOT TESSERACT. The obvious answer is to install tesseract
and ocrmypdf in this image. That is another ~400 MB of container, another
thing to keep patched, and tesseract on a photographed citation -- angled,
shadowed, printed on a textured background -- is genuinely poor. Gemini
already has the key, already reads PDFs natively as pages rather than as
character soup, and handles exactly the awkward cases this will get: phone
photographs of framed certificates.

THE FABRICATION GUARD IS THE REASON THIS IS SAFE TO DO AT ALL. A model
asked to read a blank page will write a plausible one -- that already
happened here once, and an entire invented accomplishment reached her
record. So the transcription prompt forbids inference in the strongest
terms available, and the existing word-count guard in worker.py still runs
afterwards on whatever comes back. OCR that fails still cannot fabricate;
it just fails, the same as before.

EMAIL, .eml AND .msg. She has years of work described in mail -- award
nominations, thank-yous from a commander, the paper trail of the extra
duties Jason wants shown. .eml is stdlib (`email` + `policy.default`), so
it costs a parser and no dependency. .msg is Outlook's own format, which is
a compound binary file and needs `extract_msg`; it is guarded so a missing
package degrades to a clear message instead of a traceback.

BOTH STRIP THE QUOTED CHAIN. A forwarded thread repeats itself five times,
and five copies of the same paragraph is what makes a model summarise the
signature block instead of the citation.
"""
import io
import sys

# ---------------------------------------------------------------------------
# 1. the extractor: OCR fallback + email
# ---------------------------------------------------------------------------
P = "app/llm.py"
s = io.open(P, encoding="utf-8").read()
if "_ocr_pdf" in s:
    sys.exit("already patched")

OCR = '''
# --- reading a scan ----------------------------------------------------------

OCR_SYSTEM = """You are transcribing a scanned document, exactly as it appears.

Return ONLY the text that is actually printed or written on the page.

ABSOLUTE RULES, and the first one matters more than all the others:
* NEVER infer, complete, guess or continue anything. If a word is
  illegible, write [illegible]. If a number is unclear, write [unclear]
  rather than a plausible number.
* NEVER add anything that is not on the page -- no summary, no headings you
  invented, no commentary, no "here is the text".
* If the page has no readable text at all, reply with exactly: NO TEXT FOUND
* Preserve the order things appear in. Keep names, ranks, dates, unit
  designations and figures EXACTLY as written, including punctuation.

This is going into somebody's official career record under their name. A
detail you invented is worse than a detail that is missing."""


def _ocr_pdf(path, api_key: str = "") -> str:
    """Read a scanned PDF by sending the pages to Gemini.

    WHY THIS EXISTS: a PDF with no text layer used to stop the upload dead
    and tell the user to go and upload it somewhere else instead. That is
    the system handing its routing problem to the person using it. Now the
    scan is read where it was dropped.

    Returns "" when it cannot read it -- never a guess. The caller's word
    count guard then behaves exactly as it did before.
    """
    key = api_key or config.GEMINI_API_KEY
    if not key:
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    # Gemini's inline limit is about 20MB for the whole request, and base64
    # inflates by a third. Anything near that is refused here with an empty
    # string rather than sent to be rejected with a 400.
    if len(raw) > 14 * 1024 * 1024:
        db.log_event("warn", "ocr",
                     f"{path.name} is {len(raw) // 1048576}MB -- too large to "
                     "send for reading; split it and try again")
        return ""
    import base64
    body = {
        "systemInstruction": {"parts": [{"text": OCR_SYSTEM}]},
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "application/pdf",
                             "data": base64.b64encode(raw).decode()}},
            {"text": "Transcribe this document."},
        ]}],
        # Zero temperature: this is a reading task, and every degree of
        # creativity here is a degree of invention in somebody's record.
        "generationConfig": {"temperature": 0, "maxOutputTokens": 8192},
    }
    url = (f"{config.GEMINI_URL}/{config.GEMINI_MODEL}"
           f":generateContent?key={key}")
    try:
        r = httpx.post(url, json=body, timeout=180)
        if r.status_code >= 400:
            # A quota error here is worth retrying on the paid key, same as
            # anywhere else in the chain.
            if (r.status_code == 429 or "RESOURCE_EXHAUSTED" in r.text) \\
                    and not api_key and config.GEMINI_API_KEY_PAID:
                db.log_event("info", "ocr", "free quota out, reading on tier 1")
                return _ocr_pdf(path, api_key=config.GEMINI_API_KEY_PAID)
            db.log_event("warn", "ocr", f"could not read {path.name}: "
                                        f"{r.status_code} {r.text[:200]}")
            return ""
        parts = r.json()["candidates"][0]["content"]["parts"]
        out = "".join(p.get("text", "") for p in parts).strip()
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "ocr", f"could not read {path.name}: {e}")
        return ""
    if out.strip().upper().startswith("NO TEXT FOUND"):
        return ""
    return out


# --- email -------------------------------------------------------------------

def _strip_quoted(text: str) -> str:
    """Drop the quoted chain below a reply.

    A forwarded thread repeats itself, sometimes five times over, and five
    copies of the same paragraph is what makes a model summarise the
    signature block instead of the citation.
    """
    out = []
    for line in text.splitlines():
        st = line.strip()
        if st.startswith(">"):
            continue
        if st.lower().startswith(("-----original message", "________________",
                                  "from:", "on ", "sent from my")) and out:
            # Only once real content has been seen, so a mail that OPENS
            # with "From:" is not thrown away entirely.
            if st.lower().startswith(("-----original message", "____")):
                break
        out.append(line)
    return "\\n".join(out).strip()


def _extract_eml(path) -> str:
    """A .eml, via the standard library -- no dependency."""
    import email
    from email import policy
    try:
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    except Exception as e:  # noqa: BLE001
        return f"[Could not read the email: {e}]"
    head = "\\n".join(
        f"{k}: {msg.get(k)}" for k in ("From", "To", "Cc", "Date", "Subject")
        if msg.get(k))
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        body = part.get_content() if part else ""
    except Exception:  # noqa: BLE001
        body = ""
    if not body.strip():
        body = str(msg.get_payload())
    return (head + "\\n\\n" + _strip_quoted(body)).strip()


def _extract_msg(path) -> str:
    """Outlook's own .msg -- a compound binary file, so this needs a package.

    Guarded: a missing dependency becomes a sentence somebody can act on
    rather than a traceback in a job record.
    """
    try:
        import extract_msg
    except ImportError:
        return ("[This is an Outlook .msg file and the reader for it is not "
                "installed. Open it in Outlook and use File -> Save As -> "
                "Text Only, or forward it to yourself and save as .eml.]")
    try:
        m = extract_msg.Message(str(path))
        head = "\\n".join(x for x in (
            f"From: {m.sender}" if m.sender else "",
            f"To: {m.to}" if m.to else "",
            f"Date: {m.date}" if m.date else "",
            f"Subject: {m.subject}" if m.subject else "") if x)
        return (head + "\\n\\n" + _strip_quoted(m.body or "")).strip()
    except Exception as e:  # noqa: BLE001
        return f"[Could not read the Outlook message: {e}]"

'''

ANCHOR = "def extract_text("
assert ANCHOR in s, "extract_text not found"
s = s.replace(ANCHOR, OCR.lstrip("\n") + "\n" + ANCHOR, 1)

# --- the PDF branch now falls back to OCR ----------------------------------
OLD = '''    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception as e:  # noqa: BLE001
            return f"[Could not read PDF: {e}]"
    return "[Unsupported document type]"'''
NEW = '''    if suffix == ".pdf":
        text = ""
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception as e:  # noqa: BLE001
            db.log_event("warn", "extract", f"pypdf failed on {path.name}: {e}")
        # NO TEXT LAYER MEANS A SCAN, AND A SCAN GETS READ HERE. It used to
        # stop and tell her to upload the same file somewhere else so a
        # different pipeline could OCR it -- the system handing its routing
        # problem to the person using it, and Jason diagnosing it afterwards.
        # Twenty-five words rather than zero because a scanned page often
        # carries a stray header or a page number through pypdf, which is
        # not text anybody can write from.
        if len(text.split()) < 25:
            scanned = _ocr_pdf(path)
            if scanned:
                db.log_event("info", "extract",
                             f"{path.name} had no text layer; read it as a "
                             f"scan ({len(scanned.split())} words)")
                return scanned
        return text
    if suffix == ".eml":
        return _extract_eml(path)
    if suffix == ".msg":
        return _extract_msg(path)
    return "[Unsupported document type]"'''
assert OLD in s, "pdf branch not found"
s = s.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("llm.py: scanned-PDF OCR + .eml/.msg readers")

# ---------------------------------------------------------------------------
# 2. accept the new types
# ---------------------------------------------------------------------------
C = "app/config.py"
c = io.open(C, encoding="utf-8").read()
OLDC = '''    ".pdf", ".docx", ".txt", ".md", ".rtf",'''
NEWC = '''    ".pdf", ".docx", ".txt", ".md", ".rtf",
    # email, added 2026-09-07. Jason: "I want to be able to read emails and
    # docx docs files". Years of the work he wants shown -- award
    # nominations, a note from a commander, the paper trail behind an extra
    # duty -- exists only as mail. .eml costs a stdlib parser; .msg is
    # Outlook's compound-binary format and degrades to a clear message if
    # its reader is not installed.
    ".eml", ".msg",'''
assert OLDC in c, "ALLOWED_EXT documents line not found"
c = c.replace(OLDC, NEWC, 1)
io.open(C, "w", encoding="utf-8", newline="\n").write(c)
print("config.py: .eml and .msg accepted")
