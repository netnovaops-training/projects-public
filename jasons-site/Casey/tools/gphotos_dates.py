#!/usr/bin/env python3
"""Pull per-photo capture dates out of a Google Photos share link.

Jason gave two share links for her ROTC graduation and a Google API key.

THE API KEY IS NOT USED AND CANNOT BE. Google Photos needs OAuth, not an
API key, and since 2025 the Library API only reaches media the calling app
itself created -- so no key of any kind would read her album. It also does
not need to: a share link is public to whoever holds it, and the share
page carries the dates in its own payload.

WHERE THE DATES COME FROM. The page embeds its data in
AF_initDataCallback blobs. Each photo carries a capture time in epoch
MILLISECONDS. Those are what EXIF became once Google ingested the file --
Google strips EXIF from the bytes it serves, so the served JPEG has no
date in it at all and reading the image would find nothing.

Sanity bounds are applied because the same blobs contain other epoch-like
numbers -- upload times, edit times, ids. Anything outside 1990..now is
not a photograph being taken.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

LINKS = [
    "https://photos.app.goo.gl/WDNmtra4QBXNV9Dd7",
    "https://photos.app.goo.gl/ErD7U8X9JRTuWPzW8",
]

LOW = int(datetime(1990, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HIGH = int(datetime.now(timezone.utc).timestamp() * 1000)


def fetch(url: str) -> str:
    r = subprocess.run(
        ["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0", url],
        capture_output=True, text=True, errors="replace")
    return r.stdout


for url in LINKS:
    html = fetch(url)
    title = re.search(r'og:title" content="([^"]+)"', html)
    print("=" * 66)
    print(url)
    print("album says:", title.group(1) if title else "(no title)")

    # 13-digit epoch-ms values inside the data blobs
    stamps = set()
    for m in re.finditer(r"\b(1[0-9]{12})\b", html):
        v = int(m.group(1))
        if LOW <= v <= HIGH:
            stamps.add(v)

    # The photo ids in this album, so we can say how many there are
    ids = set(re.findall(r'"(AF1Qip[A-Za-z0-9_\-]{20,})"', html))

    when = sorted(datetime.fromtimestamp(s / 1000, timezone.utc)
                  for s in stamps)
    print("distinct timestamps found:", len(when),
          "| media ids:", len(ids))
    if when:
        print("range:", when[0].strftime("%d %b %Y"),
              "->", when[-1].strftime("%d %b %Y"))
        print("all of them:")
        for d in when:
            print("   ", d.strftime("%d %b %Y  %H:%M UTC"))
    print()
