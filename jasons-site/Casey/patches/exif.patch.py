#!/usr/bin/env python3
"""Read a photo's EXIF -- for Jason's page, not Casey's. Run from Casey/.

Jason, 2026-09-07: "/ability that I will fill in with how I progressed. mine
will include pictures that will also show exif data, job gotten and lost and
my progress with my life using the timeline."

THE SAME CODE MAKES THE OPPOSITE DECISION FOR THE TWO OF THEM, and that is
the whole point of this patch being conditional rather than universal.

For Casey, EXIF is deliberately IGNORED. She photographs certificates she was
awarded years earlier, so the capture date is when she found the frame, not
when she earned the medal -- and a confident wrong date in a career record
is worse than no date. The citation's own text carries the truth.

For Jason, the photograph IS the record. He is not shooting a document about
an event, he is shooting the event: the office on the first day, the badge,
the machine he built. The capture date is the primary fact, and throwing it
away would discard the most reliable thing in the file -- a timestamp written
by a camera at the moment, not by a person remembering afterwards.

So EXIF is read when `EXIF_DATES=1`, which his instance sets and hers does
not. One image, two configurations, and the reasoning for each sits next to
the switch.

WHAT IS TAKEN, AND WHAT IS NOT.
  Taken:    DateTimeOriginal (when the shutter fired), camera make/model,
            and the GPS coordinates if they are there.
  Not taken: everything else. Lens, exposure, ISO and orientation say
            nothing about a career.

GPS IS EXTRACTED BUT DELIBERATELY NOT SHOWN BY DEFAULT. A photo from a first
day at work carries the employer's coordinates to six decimal places. That is
Jason's own page and his own data, so it is captured -- but it is put behind
`EXIF_GPS=1` rather than printed next to the picture, because a page that
quietly publishes home and workplace coordinates is a page nobody thinks
about until it is shared.

STDLIB ONLY. Pillow is not installed in this image (found earlier today when
pypdf could not extract an image without it), so the EXIF block is parsed
directly. That is a hundred lines nobody wants to own -- but the alternative
is a new dependency in the container that reads her medical documents, and
this parser only ever walks a byte range it has bounds-checked.
"""
import io
import sys

P = "app/llm.py"
s = io.open(P, encoding="utf-8").read()
if "def read_exif" in s:
    sys.exit("already patched")

CODE = '''
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
    if not raw.startswith(b"\\xff\\xd8"):
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
        if marker == 0xE1 and raw[i + 4:i + 10] == b"Exif\\x00\\x00":
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
                                      .split(b"\\x00")[0]
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

'''

ANCHOR = "# --- reading a scan --------------------------------------------------------"
assert ANCHOR in s, "ocr section anchor not found"
s = s.replace(ANCHOR, CODE.lstrip("\n") + "\n" + ANCHOR, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("llm.py: read_exif() added")

C = "app/config.py"
c = io.open(C, encoding="utf-8").read()
if "EXIF_DATES" in c:
    print("config.py: already has the switches")
else:
    add = '''
# --- what a photograph is allowed to tell us --------------------------------
#
# THE SAME CODE MAKES THE OPPOSITE DECISION FOR THE TWO PEOPLE USING IT.
#
# Casey photographs certificates she was awarded years earlier, so the capture
# date is when she found the frame, not when she earned the medal. A
# confident wrong date in a career record is worse than no date, so her
# instance leaves this OFF and takes dates from the citation text.
#
# Jason photographs the thing itself -- the office on the first day, the
# badge, the machine he built. There the capture date is the most reliable
# fact in the file, written by a camera at the moment rather than by a
# person remembering afterwards. His instance sets EXIF_DATES=1.
EXIF_DATES = os.getenv("EXIF_DATES", "").strip().lower() in ("1", "true", "yes")

# GPS SEPARATELY, AND OFF BY DEFAULT EVEN WHEN DATES ARE ON. A photo from a
# first day at work carries the employer's coordinates to six decimal
# places. It is his own page and his own data, so it can be captured -- but
# a page that quietly prints workplace and home coordinates is one nobody
# thinks about until the day it gets shared.
EXIF_GPS = os.getenv("EXIF_GPS", "").strip().lower() in ("1", "true", "yes")
'''
    c = c.rstrip("\n") + "\n" + add
    io.open(C, "w", encoding="utf-8", newline="\n").write(c)
    print("config.py: EXIF_DATES and EXIF_GPS added")
