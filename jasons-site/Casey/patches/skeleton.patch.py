#!/usr/bin/env python3
"""Shimmer placeholders for anything not loaded yet. Run from Casey/.

Jason, 2026-09-07, with the technique in two screenshots: "for all my cards
and links and pills and everything not loaded yet use this code."

THE TECHNIQUE, from the reel he sent:

    background: linear-gradient(90deg, #1a1a3a 25%, #2a2a52 50%, #1a1a3a 75%);
    background-size: 200% 100%;
    animation: sweep 1.2s linear infinite;
    @keyframes sweep { to { background-position: -200% 0; } }

It works because the gradient is painted at twice the element's width and
then slid across it -- there is no moving element, just a moving paint
origin, so it costs one compositor property and never touches layout.

TWO THINGS CHANGED FROM THE REEL, BOTH ON PURPOSE.

1. HER TOKENS, NOT THOSE HEX VALUES. #1a1a3a and #2a2a52 are a purple-navy
   that belongs to that video's design. Dropped into this portal they would
   shimmer purple over a light theme in the morning and be nearly invisible
   in the dark one. The gradient is built from --line and --panel instead,
   so it is the right two greys in whichever theme is showing, and it stays
   right if the palette is ever changed.

2. IT RESPECTS prefers-reduced-motion. A 1.2s infinite sweep across every
   card on the page is exactly the pattern that triggers vestibular
   symptoms, and this is a page somebody with a headache after a night
   shift may be reading. Under that setting the placeholder still appears
   as a flat block -- the information "this is still loading" survives, only
   the movement goes.

A SKELETON MUST HAVE A SIZE OR IT IS INVISIBLE. An empty div has no height,
so the classes below carry their own dimensions: `.sk-line` for text,
`.sk-pill` matched to the nav pills, `.sk-card` for a card-shaped block.

WHAT THIS DOES NOT DO. It adds the vocabulary; it does not decide which
screens use it. Wiring it in belongs with each slow thing -- the jacket
timeline, the record grid, an upload that is still being read -- and a
skeleton on something that renders instantly is worse than none, because it
puts a flicker where there was nothing wrong.
"""
import io
import sys

P = "app/templates/base.html"
s = io.open(P, encoding="utf-8").read()
if "sk-line" in s:
    sys.exit("already patched")

CSS = """
/* --- placeholders for anything still loading -------------------------------
   Jason, 2026-09-07: "for all my cards and links and pills and everything not
   loaded yet use this code", with the shimmer technique attached.

   The gradient is painted at twice the element's width and slid across it, so
   nothing moves except a paint origin -- one compositor property, no layout.

   BUILT FROM THE THEME TOKENS, not the hex values in the original. Those were
   a purple-navy belonging to somebody else's design; here they would shimmer
   purple over the light theme and vanish in the dark one. --line and --panel
   are the right two greys in whichever theme is showing, and they stay right
   if the palette changes.

   A skeleton needs its own size -- an empty div has no height -- so each
   class below carries dimensions. */
.sk {
  background: linear-gradient(90deg,
              var(--line) 25%, var(--panel) 50%, var(--line) 75%);
  background-size: 200% 100%;
  animation: sk-sweep 1.2s linear infinite;
  border-radius: 6px;
  display: block;
}
@keyframes sk-sweep { to { background-position: -200% 0; } }

.sk-line   { height: .8rem; margin: .55rem 0; }
.sk-line.w40{ width: 40% } .sk-line.w60{ width: 60% } .sk-line.w80{ width: 80% }
/* Matched to the real nav pills so the page does not resize when they land. */
.sk-pill   { height: 2.1rem; width: 7.5rem; border-radius: 999px;
             display: inline-block; margin: 0 .35rem .5rem 0; }
.sk-card   { height: 7rem; border-radius: var(--radius); margin-bottom: 1rem; }

/* A 1.2s infinite sweep across every card is the pattern that triggers
   vestibular symptoms, and this is a page somebody may read with a headache
   after a night shift. The block still says "loading"; only the motion goes. */
@media (prefers-reduced-motion: reduce) {
  .sk { animation: none; background: var(--line); }
}
"""

# Drop it in beside the card rules, which is where the rest of the component
# CSS lives.
ANCHOR = ".card{background:var(--panel)"
assert ANCHOR in s, "card rule not found"
s = s.replace(ANCHOR, CSS.lstrip("\n") + ANCHOR, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("base.html: .sk placeholder classes added")
