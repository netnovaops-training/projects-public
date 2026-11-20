#!/usr/bin/env python3
"""Read a photograph of an award. Run from Casey/.

Jason, 2026-09-07: "I would like my sister to be able to take a photo as a
jpg and send it for OCR ... she has many other awards, just no way to scan
them."

This is the constraint that actually decides how much of her record ever
gets captured. She has years of certificates and citations on paper, in
frames, in a folder somewhere, and no scanner -- so the only realistic
capture device is the phone already in her hand. If a photograph is not an
accepted input, those awards do not exist as far as the portal is concerned,
and no amount of drafting quality makes up for the record being empty.

The scanned-PDF reader built earlier today does the hard part already. A
photograph is the same job with a different mime type, so this is mostly
plumbing -- but three things are specific to photos and worth doing properly:

  * HEIC. An iPhone photographs in HEIC by default and Gemini does not
    accept it. Accepting the extension and failing later would be the worst
    outcome; it is accepted, and if the conversion is unavailable the
    message says to send it as JPEG rather than leaving her guessing.

  * THE PROMPT ADMITS IT IS A PHOTOGRAPH. A framed citation is shot at an
    angle, under a lamp, with glare across the middle and a thumb in the
    corner. Telling the model that is what it is looking at measurably
    changes what it does with the blurred line at the bottom -- and the
    instruction to write [illegible] rather than guess matters far more
    here than on a flat scan.

  * EXIF IS LEFT ALONE, deliberately. It is tempting to read the capture
    date off the photo and date the accomplishment with it. That date is
    when she photographed the certificate, which is usually years after the
    award, and a plausible wrong date in a career record is worse than no
    date. The award's own text carries the real one.

Everything downstream is unchanged: the same transcription rules, the same
fabrication guard afterwards. A photo that cannot be read fails; it never
invents.
"""
import io
import sys

P = "app/llm.py"
s = io.open(P, encoding="utf-8").read()
if "_ocr_image" in s:
    sys.exit("already patched")

NEW_FN = '''
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
            if (r.status_code == 429 or "RESOURCE_EXHAUSTED" in r.text) \\
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

'''

ANCHOR = "# --- email ----------------------------------------------------------"
assert ANCHOR in s, "email section anchor not found"
s = s.replace(ANCHOR, NEW_FN.lstrip("\n") + "\n" + ANCHOR, 1)

OLD = '''    if suffix == ".eml":'''
NEW = '''    # A PHOTOGRAPH OF A CERTIFICATE IS A DOCUMENT. She has years of awards
    # on paper and no scanner, so the phone is the capture device -- and an
    # input the portal refuses is a part of her record that never exists.
    if suffix in IMAGE_MIME or suffix in (".heic", ".heif"):
        shot = _ocr_image(path)
        if shot:
            db.log_event("info", "extract",
                         f"read {path.name} as a photograph "
                         f"({len(shot.split())} words)")
        return shot or "[Nothing readable in that photo.]"
    if suffix == ".eml":'''
assert OLD in s, "eml branch not found"
s = s.replace(OLD, NEW, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("llm.py: photographs read as documents")

C = "app/config.py"
c = io.open(C, encoding="utf-8").read()
OLDC = '''    ".eml", ".msg",'''
NEWC = '''    ".eml", ".msg",
    # photographs, added 2026-09-07. Jason: "she has many other awards, just
    # no way to scan them." The phone is the only capture device she has, so
    # a format the portal refuses is a part of her record that never exists.
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff",'''
assert OLDC in c, "email ext line not found"
c = c.replace(OLDC, NEWC, 1)
io.open(C, "w", encoding="utf-8", newline="\n").write(c)
print("config.py: photo formats accepted")
