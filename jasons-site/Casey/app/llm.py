"""Calls into the desktop's Whisper transcription service and Ollama."""
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

import httpx

from . import config, db

# --- knowledge base ----------------------------------------------------------

def knowledge_files() -> list[Path]:
    if not config.KNOWLEDGE_DIR.exists():
        return []
    # LEADING UNDERSCORE MEANS "NOT PROMPT TEXT". `_template.md` is an
    # instance's output template (see worker._template_override) and is used
    # as the shape of the answer -- concatenating it into the system prompt
    # as well would give the model the same instructions twice, once as
    # context and once as the task. Found 2026-09-07: the comment claimed
    # the underscore already excluded it, and glob("*.md") matches it
    # perfectly well.
    return sorted(p for p in config.KNOWLEDGE_DIR.glob("*.md")
                  if p.is_file() and not p.name.startswith("_"))


def load_knowledge() -> tuple[str, str]:
    """Concatenate every .md in the knowledge dir, in filename order.

    Returns (text, version) where version is a short content hash. Because the
    prompt is assembled from files on disk, editing a file changes behaviour and
    `git checkout` resets it -- that is the whole point of this design.
    """
    parts: list[str] = []
    for p in knowledge_files():
        try:
            parts.append(f"\n\n<!-- ===== {p.name} ===== -->\n" + p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            db.log_event("warn", "knowledge", f"Could not read {p.name}: {e}")
    text = "".join(parts).strip()
    version = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else "empty"
    return text, version


# --- transcription -----------------------------------------------------------

def transcribe(path: Path) -> str:
    url = config.whisper_url("/v1/audio/transcriptions")
    with open(path, "rb") as fh:
        files = {"file": (path.name, fh, "application/octet-stream")}
        data = {"response_format": "json", "language": "en"}
        r = httpx.post(url, files=files, data=data, timeout=config.WHISPER_TIMEOUT)
    r.raise_for_status()
    try:
        payload = r.json()
    except Exception:
        return r.text.strip()
    return (payload.get("text") or "").strip()


# --- text extraction from uploaded documents ---------------------------------

# --- when was this actually written? -----------------------------------------

# Dates as they appear on real documents. Ordered longest-first so
# "17 August 2023" is not matched as "8/2023" by a shorter pattern.
_DATE_PATTERNS = [
    (r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
     r"September|October|November|December)\s+(\d{4})\b", "dmy"),
    (r"\b(January|February|March|April|May|June|July|August|September|"
     r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b", "mdy"),
    (r"\b(\d{4})-(\d{2})-(\d{2})\b", "iso"),
    (r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", "us"),
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
            m = _re.match(r"D?:?(\d{4})(\d{2})(\d{2})", raw)
            if m:
                return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif suf in (".docx", ".xlsx", ".pptx"):
            import zipfile
            with zipfile.ZipFile(path) as z:
                core = z.read("docProps/core.xml").decode("utf-8", "replace")
            m = _re.search(r"<dcterms:created[^>]*>(\d{4})-(\d{2})-(\d{2})", core)
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


# --- what a photograph knows about itself ------------------------------------

def read_exif(path) -> dict:
    """DateTimeOriginal, camera and GPS from a JPEG. Stdlib only.

    OFF FOR CASEY, ON FOR JASON, and the difference is the point. She
    photographs certificates awarded years before, so the capture date is
    when she found the frame -- a confident wrong date in a career record is
    worse than none. He photographs the thing itself, so the capture date is
    the most reliable fact in the file: written by a camera at the moment,
    not by a person remembering later.

    Returns {} for anything it cannot read. Never guesses.
    """
    if not config.EXIF_DATES:
        return {}
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    if not raw.startswith(b"\xff\xd8"):
        return {}                       # not a JPEG; PNG/HEIC carry it elsewhere

    # Find the APP1/Exif segment by walking the JPEG marker chain rather
    # than searching for b"Exif" anywhere in the file -- the bytes can
    # appear inside image data, and a false hit would parse garbage.
    i, n = 2, len(raw)
    seg = b""
    while i + 4 <= n and raw[i] == 0xFF:
        marker, size = raw[i + 1], int.from_bytes(raw[i + 2:i + 4], "big")
        if size < 2 or i + 2 + size > n:
            return {}
        if marker == 0xE1 and raw[i + 4:i + 10] == b"Exif\x00\x00":
            seg = raw[i + 10:i + 2 + size]
            break
        if marker in (0xDA, 0xD9):      # start of scan / end -- no EXIF
            return {}
        i += 2 + size
    if len(seg) < 8:
        return {}

    endian = "little" if seg[:2] == b"II" else "big" if seg[:2] == b"MM" else ""
    if not endian:
        return {}

    def u16(o): return int.from_bytes(seg[o:o + 2], endian)
    def u32(o): return int.from_bytes(seg[o:o + 4], endian)

    WANT = {0x9003: "taken", 0x0132: "taken_fallback",
            0x010F: "make", 0x0110: "model"}
    out, gps_off = {}, 0

    def walk(off, depth=0):
        """One IFD. Bounds-checked at every read; depth-capped against loops."""
        nonlocal gps_off
        if depth > 2 or off <= 0 or off + 2 > len(seg):
            return
        count = u16(off)
        for k in range(count):
            e = off + 2 + k * 12
            if e + 12 > len(seg):
                return
            tag, typ, cnt, val = u16(e), u16(e + 2), u32(e + 4), u32(e + 8)
            if tag == 0x8825:                  # GPS sub-IFD pointer
                gps_off = val
            elif tag == 0x8769:                # Exif sub-IFD pointer
                walk(val, depth + 1)
            elif tag in WANT and typ == 2:     # ASCII
                start = val if cnt > 4 else e + 8
                if 0 <= start and start + cnt <= len(seg):
                    out[WANT[tag]] = (seg[start:start + cnt]
                                      .split(b"\x00")[0]
                                      .decode("ascii", "replace").strip())
        nxt = off + 2 + count * 12
        if nxt + 4 <= len(seg):
            walk(u32(nxt), depth + 1)

    try:
        walk(u32(4))
        # GPS IS READ BUT GATED. A photo of a first day at work carries the
        # employer's coordinates to six decimals. This is his own page and
        # his own data, so it is captured -- but a page that quietly prints
        # workplace coordinates is one nobody thinks about until it is
        # shared, so it needs EXIF_GPS as well.
        if gps_off and config.EXIF_GPS and gps_off + 2 <= len(seg):
            g = {}
            cnt = u16(gps_off)
            for k in range(cnt):
                e = gps_off + 2 + k * 12
                if e + 12 > len(seg):
                    break
                tag, typ, c, val = u16(e), u16(e + 2), u32(e + 4), u32(e + 8)
                if tag in (1, 3) and typ == 2:            # N/S, E/W
                    g[tag] = chr(seg[e + 8]) if e + 8 < len(seg) else ""
                elif tag in (2, 4) and typ == 5 and c == 3:   # rationals
                    parts = []
                    for j in range(3):
                        o = val + j * 8
                        if o + 8 > len(seg):
                            break
                        num, den = u32(o), u32(o + 4)
                        parts.append(num / den if den else 0.0)
                    if len(parts) == 3:
                        g[tag] = parts[0] + parts[1] / 60 + parts[2] / 3600
            if 2 in g and 4 in g:
                lat, lon = g[2], g[4]
                if g.get(1) == "S":
                    lat = -lat
                if g.get(3) == "W":
                    lon = -lon
                out["gps"] = f"{lat:.5f},{lon:.5f}"
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "exif", f"could not read {path.name}: {e}")
        return {}

    taken = out.pop("taken_fallback", "")
    if not out.get("taken") and taken:
        out["taken"] = taken
    # EXIF dates are "YYYY:MM:DD HH:MM:SS". Convert only the date half --
    # the time of day is not a career fact.
    t = out.get("taken", "")
    if len(t) >= 10 and t[4] == ":" and t[7] == ":":
        out["taken"] = t[:10].replace(":", "-")
    return {k: v for k, v in out.items() if v}


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
            if (r.status_code == 429 or "RESOURCE_EXHAUSTED" in r.text) \
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


IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    ".tif": "image/tiff", ".tiff": "image/tiff",
}

PHOTO_SYSTEM = OCR_SYSTEM + """

THIS IS A PHOTOGRAPH OF A PRINTED DOCUMENT, not a flat scan. Expect it taken
at an angle, under a lamp, with glare across part of it, a shadow, a frame,
or a thumb in one corner. Read what is legible and mark what is not.

Do NOT let the awkward image tempt you into completing anything. A citation
follows a predictable form and you will be able to guess the missing words.
Do not. Write [illegible] and let a person fill it in -- this is going into
her official record, and a sentence you completed for her is a sentence she
will submit believing it came off the certificate."""


def _ocr_image(path, api_key: str = "") -> str:
    """Read a photographed document -- the only capture device she has.

    She has years of certificates on paper and no scanner, so a phone
    photograph is the realistic input. Same contract as _ocr_pdf: returns ""
    when it cannot read it, never a guess.

    EXIF IS DELIBERATELY IGNORED. The capture date is when she photographed
    the certificate, typically years after the award, and dating an entry
    from it would put a confident wrong date in a career record. The award's
    own text carries the real date.
    """
    key = api_key or config.GEMINI_API_KEY
    if not key:
        return ""
    suffix = path.suffix.lower()
    mime = IMAGE_MIME.get(suffix)
    if not mime:
        if suffix in (".heic", ".heif"):
            return ("[This is an iPhone HEIC photo, which cannot be read "
                    "directly. On the phone: Settings -> Camera -> Formats "
                    "-> Most Compatible, or share the photo by email, which "
                    "converts it to JPEG on the way out.]")
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if len(raw) > 14 * 1024 * 1024:
        db.log_event("warn", "ocr", f"{path.name} is too large to send")
        return ""
    import base64
    body = {
        "systemInstruction": {"parts": [{"text": PHOTO_SYSTEM}]},
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": mime,
                             "data": base64.b64encode(raw).decode()}},
            {"text": "Transcribe every word visible in this photograph."},
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 8192},
    }
    url = (f"{config.GEMINI_URL}/{config.GEMINI_MODEL}"
           f":generateContent?key={key}")
    try:
        r = httpx.post(url, json=body, timeout=180)
        if r.status_code >= 400:
            if (r.status_code == 429 or "RESOURCE_EXHAUSTED" in r.text) \
                    and not api_key and config.GEMINI_API_KEY_PAID:
                db.log_event("info", "ocr", "free quota out, reading on tier 1")
                return _ocr_image(path, api_key=config.GEMINI_API_KEY_PAID)
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
    return "\n".join(out).strip()


def _extract_eml(path) -> str:
    """A .eml, via the standard library -- no dependency."""
    import email
    from email import policy
    try:
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    except Exception as e:  # noqa: BLE001
        return f"[Could not read the email: {e}]"
    head = "\n".join(
        f"{k}: {msg.get(k)}" for k in ("From", "To", "Cc", "Date", "Subject")
        if msg.get(k))
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        body = part.get_content() if part else ""
    except Exception:  # noqa: BLE001
        body = ""
    if not body.strip():
        body = str(msg.get_payload())
    return (head + "\n\n" + _strip_quoted(body)).strip()


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
        head = "\n".join(x for x in (
            f"From: {m.sender}" if m.sender else "",
            f"To: {m.to}" if m.to else "",
            f"Date: {m.date}" if m.date else "",
            f"Subject: {m.subject}" if m.subject else "") if x)
        return (head + "\n\n" + _strip_quoted(m.body or "")).strip()
    except Exception as e:  # noqa: BLE001
        return f"[Could not read the Outlook message: {e}]"


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md", ".rtf"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        try:
            import zipfile
            from xml.etree import ElementTree as ET
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml")
            # A .docx is a zip somebody hands us, and its XML is parsed
            # by expat, which happily expands internal entities -- the
            # billion-laughs shape, where a few kilobytes becomes
            # gigabytes of memory and takes the container with it.
            # ElementTree does not fetch EXTERNAL entities, so this is a
            # denial of service rather than a data leak, but a document
            # that declares entities at all has no business in a career
            # portal. Refused rather than parsed, and with no new
            # dependency to do it.
            if b"<!ENTITY" in xml[:20000] or b"<!DOCTYPE" in xml[:20000]:
                return ("[This .docx declares XML entities and was not "
                        "opened. Re-save it from Word or paste the text.]")
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            root = ET.fromstring(xml)
            paras = []
            for p in root.iter(f"{ns}p"):
                text = "".join(t.text or "" for t in p.iter(f"{ns}t"))
                if text.strip():
                    paras.append(text)
            return "\n".join(paras)
        except Exception as e:  # noqa: BLE001
            return f"[Could not read .docx: {e}]"
    if suffix == ".pdf":
        text = ""
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
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
    # A PHOTOGRAPH OF A CERTIFICATE IS A DOCUMENT. She has years of awards
    # on paper and no scanner, so the phone is the capture device -- and an
    # input the portal refuses is a part of her record that never exists.
    if suffix in IMAGE_MIME or suffix in (".heic", ".heif"):
        shot = _ocr_image(path)
        if shot:
            db.log_event("info", "extract",
                         f"read {path.name} as a photograph "
                         f"({len(shot.split())} words)")
        return shot or "[Nothing readable in that photo.]"
    if suffix == ".eml":
        return _extract_eml(path)
    if suffix == ".msg":
        return _extract_msg(path)
    return "[Unsupported document type]"


# --- generation --------------------------------------------------------------

def chat(system: str, user: str, model: Optional[str] = None,
         num_ctx: Optional[int] = None, temperature: float = 0.4,
         think: Optional[bool] = None) -> str:
    """One-shot chat completion against Ollama on the desktop.

    Current-generation models (Qwen3.5, Gemma 4) are reasoning models with
    thinking ON by default, which wastes tokens and latency on structured
    drafting work. `think: false` turns it off at the API level; strip_thinking()
    below is the belt-and-braces fallback for models that ignore the flag.
    """
    model = model or config.OLLAMA_MODEL
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": config.OLLAMA_THINK if think is None else think,
        "options": {
            "num_ctx": num_ctx or config.OLLAMA_NUM_CTX,
            "temperature": temperature,
        },
    }
    r = httpx.post(config.ollama_url("/api/chat"), json=body, timeout=config.OLLAMA_TIMEOUT)
    if r.status_code == 400 and "think" in r.text.lower():
        body.pop("think", None)  # older Ollama build that doesn't know the flag
        r = httpx.post(config.ollama_url("/api/chat"), json=body,
                       timeout=config.OLLAMA_TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    content = (payload.get("message") or {}).get("content", "")
    return strip_thinking(content).strip()


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Reasoning models (Qwen3.x et al) emit <think> blocks. Drop them."""
    text = _THINK_RE.sub("", text)
    # Unterminated think block: keep only what follows the last </think>, else all.
    if "<think>" in text.lower():
        idx = text.lower().rfind("</think>")
        text = text[idx + 8:] if idx != -1 else text.split("<think>")[0]
    return text


def available_models() -> list[str]:
    try:
        r = httpx.get(config.ollama_url("/api/tags"), timeout=5)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except Exception:
        return []


# --- output parsing ----------------------------------------------------------

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json(text: str):
    """Pull the first JSON object/array out of a model response, tolerating fences."""
    m = _JSON_BLOCK.search(text)
    candidates = [m.group(1)] if m else []
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except Exception:
            continue
    return None

# --- Claude ------------------------------------------------------------------

def ask_claude(system: str, user: str, history: Optional[list] = None,
               model: Optional[str] = None, temperature: float = 0.4) -> str:
    """One turn against the Anthropic API, over plain HTTP.

    No SDK on purpose: this is one POST with three headers, and httpx is
    already a dependency. A missing key is a clear error rather than a
    silent fall-through, because 'why does it sound worse today' is a
    horrible thing to have to debug from the outside.
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("no ANTHROPIC_API_KEY set")
    msgs = list(history or [])
    msgs.append({"role": "user", "content": user})
    # PROMPT CACHING, and it is the whole cost story (2026-09-04). Her
    # knowledge base is about ten thousand tokens of IDENTICAL text on
    # every single turn -- the awards catalog, the writing rules, her
    # profile. Sent plainly, that is what she pays for; cached, a repeat
    # read costs about a tenth. The cache lives ~5 minutes and refreshes
    # on each hit, so a working session pays full price once.
    #
    # Marked on the SYSTEM block only. The conversation changes every
    # turn and would never hit.
    body = {
        "model": model or config.ANTHROPIC_MODEL,
        "max_tokens": config.ANTHROPIC_MAX_TOKENS,
        "temperature": temperature,
        "system": [{"type": "text", "text": system,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": msgs,
    }
    r = httpx.post(config.ANTHROPIC_URL, json=body,
                   headers={"x-api-key": config.ANTHROPIC_API_KEY,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json"},
                   timeout=config.ANTHROPIC_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"Anthropic {r.status_code}: {r.text[:300]}")
    payload = r.json()
    u = payload.get("usage") or {}
    if u:
        # Written down so the saving is observable rather than assumed.
        db.log_event("info", "claude",
                     "in=%s cache_write=%s cache_read=%s out=%s" % (
                         u.get("input_tokens"),
                         u.get("cache_creation_input_tokens"),
                         u.get("cache_read_input_tokens"),
                         u.get("output_tokens")))
    parts = [b.get("text", "") for b in payload.get("content", [])
             if b.get("type") == "text"]
    return "".join(parts).strip()


# Raised when a key has no quota left, and ONLY then -- see ask() for why
# that distinction is the whole point of this class existing.
class GeminiQuotaExhausted(RuntimeError):
    pass


def ask_gemini(system: str, user: str, history=None,
               temperature: float = 0.4, api_key: str = "") -> str:
    """One turn against Gemini, over plain HTTP -- no SDK, same as Claude.

    The cheap middle of the chain. Gemini names the roles differently
    ("model", not "assistant") and carries the system prompt in its own
    field, which is the only real difference from the Claude call above.
    """
    # The caller passes the key so the same function serves both tiers.
    # Defaults to the free one, which is every existing call site.
    key = api_key or config.GEMINI_API_KEY
    if not key:
        raise RuntimeError("no GEMINI_API_KEY set")
    contents = []
    for m in (history or []):
        contents.append({
            "role": "user" if m.get("role") == "user" else "model",
            "parts": [{"text": m.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": user}]})
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"temperature": temperature,
                             "maxOutputTokens": config.ANTHROPIC_MAX_TOKENS},
    }
    url = (f"{config.GEMINI_URL}/{config.GEMINI_MODEL}"
           f":generateContent?key={key}")
    r = httpx.post(url, json=body, timeout=config.ANTHROPIC_TIMEOUT)
    if r.status_code >= 400:
        # TELL "OUT OF QUOTA" APART FROM EVERYTHING ELSE. Only the former
        # is worth retrying on a paid key; a bad request or a safety
        # refusal fails the same way on both and retrying would spend
        # money to get the identical error twice.
        body_text = r.text[:300]
        out_of_quota = r.status_code == 429 or (
            r.status_code == 403
            and ("RESOURCE_EXHAUSTED" in r.text or "quota" in r.text.lower()))
        if out_of_quota:
            raise GeminiQuotaExhausted(f"Gemini {r.status_code}: {body_text}")
        raise RuntimeError(f"Gemini {r.status_code}: {body_text}")
    d = r.json()
    parts = d["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


def ask(system: str, user: str, history: Optional[list] = None,
        temperature: float = 0.4) -> tuple[str, str]:
    """Ask whoever is on duty. Returns (answer, which_model).

    Claude when a key is present, the house model otherwise -- and the
    house model also catches a Claude failure, so a rate limit or an
    outage costs her the better answer, not the answer.
    """
    # CLAUDE FIRST -- WHEN THERE IS A KEY, AND TODAY THERE IS NOT.
    # ANTHROPIC_API_KEY and ZEE_ANTHROPIC_API_KEY are both empty in .env
    # and LiteLLM's Claude entry is commented out, so this branch has
    # never run: every answer she has had came from Gemini. Nothing is
    # broken, the chain simply starts one rung down until a key exists.
    # Written down because a chain that LOOKS wired and is not is worse
    # than one that is obviously off.
    if config.ANTHROPIC_API_KEY:
        try:
            return ask_claude(system, user, history, temperature=temperature), \
                   config.ANTHROPIC_MODEL
        except Exception as e:  # noqa: BLE001
            db.log_event("warn", "llm", f"Claude failed, stepping down: {e}")
    # The cheap middle. Already keyed on this machine, and measurably
    # better than the local 8B at following a strict format.
    if config.GEMINI_API_KEY:
        try:
            return (ask_gemini(system, user, history, temperature=temperature),
                    config.GEMINI_MODEL)
        except GeminiQuotaExhausted as e:
            # THE FREE KEY IS DRY -- the one failure worth paying to retry.
            # Jason, 2026-09-07: "let's use tier 1 when free tier is out of
            # credits." Free first so the paid key is spillover rather than
            # the default, which is both what he asked for and what costs
            # least. Any OTHER Gemini failure skips this and drops to the
            # house model, because it would fail identically on a paid key.
            if config.GEMINI_API_KEY_PAID:
                db.log_event("info", "llm",
                             f"free Gemini quota exhausted, using tier 1: {e}")
                try:
                    return (ask_gemini(system, user, history,
                                       temperature=temperature,
                                       api_key=config.GEMINI_API_KEY_PAID),
                            f"{config.GEMINI_MODEL} (tier 1)")
                except Exception as e2:  # noqa: BLE001
                    db.log_event("warn", "llm",
                                 f"tier 1 Gemini failed too, house model: {e2}")
            else:
                db.log_event("warn", "llm",
                             "free Gemini quota exhausted and no paid key set "
                             "(GEMINI_API_KEY_PAID) -- using the house model")
        except Exception as e:  # noqa: BLE001
            db.log_event("warn", "llm", f"Gemini failed, using the house model: {e}")
    joined = user
    if history:
        prior = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)
        joined = f"Earlier in this conversation:\n{prior}\n\nNow: {user}"
    return chat(system, joined, temperature=temperature), config.OLLAMA_MODEL


# --- the voice back ----------------------------------------------------------

def _voice_key(text: str, voice: str) -> str:
    """One name for one rendering. Same words + same voice = same file."""
    h = hashlib.sha256(f"{voice}|{text}".encode("utf-8")).hexdigest()[:20]
    return f"say-{h}.mp3"


def speak_cached(text: str, folder: Path, voice: Optional[str] = None) -> Optional[Path]:
    """Render once, keep forever (Jason, 2026-09-04): "I want them saved
    as a mp3 ... I don't have to re render to save money."

    The filename IS the cache key -- a hash of the words and the voice --
    so an answer that has been spoken before is served off disk with no
    engine call at all. Repeats are not rare here: the between-step
    patter, the briefing, an answer she plays twice. Every one of those
    used to cost a render.

    Returns the path, or None if it could not be made. Never raises: a
    silent answer is a degraded answer, not a failed one, because the
    words are already on screen by the time this runs.
    """
    text = (text or "").strip()
    if not text:
        return None
    voice = voice or config.VOICE_NAME
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / _voice_key(text, voice)
    if dest.exists() and dest.stat().st_size > 800:
        return dest                      # already said, in this voice
    return dest if speak(text, dest, voice=voice) else None


def speak(text: str, out: Path, voice: Optional[str] = None) -> bool:
    """Render an answer to audio. False (not an exception) when it cannot.

    A silent answer is a degraded answer, not a failed one -- the words
    are already on screen by the time this runs.
    """
    if not text.strip():
        return False
    try:
        r = httpx.post(config.VOICE_URL,
                       json={"model": "tts-1",
                             "voice": voice or config.VOICE_NAME,
                             "input": text[:4000], "normalize": True},
                       timeout=config.VOICE_TIMEOUT)
        if r.status_code >= 400:
            db.log_event("warn", "voice", f"TTS {r.status_code}: {r.text[:160]}")
            return False
        out.write_bytes(r.content)
        return True
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "voice", f"TTS failed: {e}")
        return False
