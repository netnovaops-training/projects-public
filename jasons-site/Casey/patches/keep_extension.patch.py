#!/usr/bin/env python3
"""A long filename lost its extension, and everything downstream lied. Run from Casey/.

Jason, 2026-09-07: "I'm trying to use one of these and both give an error."

WHAT ACTUALLY HAPPENED, because the visible error blamed the wrong thing.

The upload was saved as

    1788779515_174da4c7__One_team__one_fight___Air_Force_nurse_enhances_neonatal_care_and_leadership_at_

with no `.pdf` on the end. `re.sub(...)[:80]` truncates the WHOLE name, and
that article's title is longer than 80 characters, so the extension was cut
off with the rest of it. The file on disk was a perfectly good 1.7 MB PDF --
pypdf reads 931 words out of it -- but llm.py dispatches on `suffix`, found
none, and returned the literal string

    "[Unsupported document type]"

which is three words. The guard in worker.py counted three words, correctly
refused to draft anything, and then explained the refusal by saying the file
was probably a scan and suggesting OCR. It was not a scan. Every layer
behaved reasonably and the user was told something false.

TWO FIXES, because the bug and the misleading message are separate faults.

1. TRUNCATE THE STEM, KEEP THE SUFFIX. The extension is the one part of a
   filename that is load-bearing here -- it is how the extractor knows what
   the file is -- and it was the part being thrown away. It is also already
   validated against ALLOWED_EXT a few lines above, so it is safe to append
   verbatim.

2. SAY WHICH FAILURE IT WAS. The extractors return their errors as bracketed
   strings ("[Unsupported document type]", "[Could not read PDF: ...]"), so
   "we could not open this file" and "this file has no text in it" arrive at
   the guard looking identical -- both just short. They need different
   advice: OCR fixes a scan and does nothing for a file that could not be
   opened. The guard now checks for the bracket and says which happened.

Job 1 (Award Casey.pdf) is genuinely a scan -- it kept its extension and still
extracted 0 words -- so its message was right all along. Job 2 was this bug.
"""
import io
import sys

# ---------------------------------------------------------------------------
# 1. keep the extension
# ---------------------------------------------------------------------------
P = "app/main.py"
s = io.open(P, encoding="utf-8").read()
if "keep the suffix" in s:
    print(f"  {P}: already patched")
else:
    OLD = '''        safe = re.sub(r"[^A-Za-z0-9._-]", "_", orig_name)[:80]'''
    NEW = '''        # TRUNCATE THE STEM, keep the suffix. [:80] on the whole name threw
        # away the extension of anything with a long title -- and the
        # extension is how llm.py knows what the file is. A 1.7 MB PDF whose
        # article headline ran past 80 characters was saved with no ".pdf",
        # read as "[Unsupported document type]", and reported to Casey as
        # probably being a scan that needed OCR. It was not (2026-09-07).
        # `ext` is already validated against ALLOWED_EXT above.
        stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(orig_name).stem)[:80]
        safe = f"{stem}{ext}"'''
    assert OLD in s, "upload truncation not found"
    s = s.replace(OLD, NEW, 1)

    OLD2 = '''        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]'''
    NEW2 = '''        # Same fix as the document upload above: the suffix is load-bearing
        # and must survive truncation. `ext` is validated against AUDIO_EXT.
        stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).stem)[:80]
        safe = f"{stem}{ext}"'''
    assert OLD2 in s, "recording truncation not found"
    s = s.replace(OLD2, NEW2, 1)

    io.open(P, "w", encoding="utf-8", newline="\n").write(s)
    print(f"  {P}: extension preserved on both upload paths")

# ---------------------------------------------------------------------------
# 2. say which failure it was
# ---------------------------------------------------------------------------
P2 = "app/worker.py"
w = io.open(P2, encoding="utf-8").read()
if "could not be opened at all" in w:
    print(f"  {P2}: already patched")
    sys.exit(0)

OLD3 = """    if len(combined.split()) < 12:
        raise RuntimeError(
            "There was nothing readable in that. It came back with \""""
NEW3 = """    # WHICH FAILURE WAS IT. The extractors report their own errors as
    # bracketed strings -- "[Unsupported document type]", "[Could not read
    # PDF: ...]" -- so a file that could not be OPENED and a file with no
    # TEXT IN IT both arrive here looking the same: short. They need
    # opposite advice, and getting it wrong sent Jason to OCR a PDF that was
    # never a scan (2026-09-07). If the extractor left a bracketed complaint,
    # repeat it instead of guessing.
    stripped = combined.strip()
    if stripped.startswith("[") and len(combined.split()) < 12:
        raise RuntimeError(
            f"That file could not be opened at all: {stripped}\\n\\n"
            "This is not the same as a scan with no text in it -- running it "
            "through OCR will not help. It usually means the file is not the "
            "type its name says, or it arrived damaged. Try uploading it "
            "again, or open it and re-save it as a PDF first.\\n\\n"
            "Nothing was drafted: a model handed an error message will write "
            "around it and that would go into your record under your name.")

    if len(combined.split()) < 12:
        raise RuntimeError(
            "There was nothing readable in that. It came back with \""""
assert OLD3 in w, "guard not found"
w = w.replace(OLD3, NEW3, 1)
io.open(P2, "w", encoding="utf-8", newline="\n").write(w)
print(f"  {P2}: guard now distinguishes 'could not open' from 'no text'")
