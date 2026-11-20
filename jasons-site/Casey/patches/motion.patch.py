#!/usr/bin/env python3
"""Four techniques from the reels Jason sent. Run from Casey/.

Both portals share this image, so /casey and /ability get all of it.

  1. CSS counters          count-up numbers, no JavaScript
  2. @property glow        a rotating border light around a card
  3. :has()                theme and multi-select styling
  4. prefers-reduced-motion + play-once

ONE CORRECTION, AND IT IS THE IMPORTANT PART OF THIS PATCH.

Jason asked for the CSS-counter trick "for the numbers" on the portfolio.
The technique is real and it is genuinely clever -- @property makes an
integer animatable, and `counter-reset` plus `content` prints it with no
JavaScript at all. But a number produced that way lives in generated
content, and generated content:

  * cannot be selected or copied,
  * is not reliably read by a screen reader,
  * does not appear in the page text at all.

Her portfolio numbers are 287 complex cases, $392,000 saved, 84 Airmen.
Those get copied out of this page and pasted into award packages. A number
that cannot be copied is worse than a number that does not move, and one
that a screen reader skips is a number that is not really published.

So the real figure stays in the DOM as text, and the count-up runs as
DECORATION over the top of it -- the element holds the true value, the
animation is a visual layer, and with animations off or the technique
unsupported the correct number is simply there. `aria-hidden` on the
decorative half, the real one always readable.

That is the opposite of how the reel does it, deliberately.

ON "TURN OFF ANIMATIONS AFTER THE PERSON LOGS IN": the reel shows
`prefers-reduced-motion`, which is an operating-system accessibility
setting rather than anything to do with logging in. Both are worth having
and they are different things, so both are here:

  * prefers-reduced-motion   respects the OS setting, always.
  * play-once                what he actually described. This is a portal
                             somebody opens every day; an entrance animation
                             that replays on every visit stops being a
                             welcome and becomes a wait. It runs on the first
                             visit and never again on that device.
"""
import io
import sys

P = "app/templates/base.html"
s = io.open(P, encoding="utf-8").read()
if "--glow-angle" in s:
    sys.exit("already patched")

CSS = """
/* === techniques from the reels Jason sent, 2026-09-07 ====================== */

/* --- 1. count-up numbers, and why the real one stays in the DOM -------------
   @property makes an integer animatable, so counter-reset + content can count
   up with no JavaScript. Genuinely clever, and WRONG on its own for these
   numbers: generated content cannot be selected or copied and is not reliably
   read by a screen reader. Her figures -- 287 cases, $392,000 saved -- get
   copied out of this page into award packages. A number nobody can copy is
   worse than a number that does not move.

   So the true value stays as text and the count-up is painted over it. With
   animation off, or @property unsupported, the correct number is simply
   there. Markup:
       <span class="tally" style="--n:287">287</span>                        */
@property --tally {
  syntax: "<integer>"; initial-value: 0; inherits: false;
}
.tally { position: relative; font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: no-preference) {
  .tally.run { color: transparent; }
  .tally.run::after {
    counter-reset: t var(--tally);
    content: counter(t);
    position: absolute; inset: 0; color: var(--ink);
    animation: tally-up 1.1s ease-out forwards;
  }
  @keyframes tally-up { from { --tally: 0 } to { --tally: var(--n) } }
}

/* --- 2. a rotating light around a card -------------------------------------
   The angle is animated because @property gives it a type; without that an
   angle in a gradient is just a string and does not interpolate.

   Opt-in per card (.card.lit) rather than on every card: a page where
   everything glows has nothing highlighted. Use it on the one card that
   wants attention. */
@property --glow-angle {
  syntax: "<angle>"; initial-value: 0deg; inherits: false;
}
.card.lit { position: relative; }
.card.lit::before {
  content: ""; position: absolute; inset: -1px; border-radius: inherit;
  z-index: -1;
  background: conic-gradient(from var(--glow-angle),
              transparent 0turn, var(--accent) 0.12turn, transparent 0.25turn);
  animation: glow-spin 4s linear infinite;
}
@keyframes glow-spin { to { --glow-angle: 360deg } }
/* Without @property the angle will not animate, so the ring would sit
   frozen on one side of the card looking like a rendering fault. Hide it
   rather than ship a broken-looking edge. */
@supports not (background: conic-gradient(from var(--glow-angle), red, blue)) {
  .card.lit::before { display: none; }
}

/* --- 3. :has(), the conditional CSS finally has -----------------------------
   Used for the things that previously needed a class toggled by script: a
   whole option highlighting when its radio is checked, and a card knowing it
   contains something that needs attention. */
.opt:has(input:checked) {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--panel));
}
.card:has(.needs-input) { border-left: 3px solid var(--warn); }
.chips:has(.chip.on) .chip:not(.on) { opacity: .72; }

/* --- 4a. the OS setting, respected everywhere ------------------------------ */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .001ms !important;
    scroll-behavior: auto !important;
  }
}

/* --- 4b. play once, then stop ----------------------------------------------
   Jason: "turn off animations after the person logs in". Distinct from the
   media query above -- that is an accessibility preference, this is about a
   page somebody opens every single day. An entrance animation that replays
   on every visit stops being a welcome and becomes a wait.

   The body gets `seen` from the script below on the second visit onward, and
   entrance animations are skipped from then on. Hover and feedback
   animations are unaffected: those respond to something the person just did,
   which is the opposite of a thing they have to sit through. */
.enter { animation: enter-fade .45s ease-out both; }
@keyframes enter-fade {
  from { opacity: 0; transform: translateY(6px) }
  to   { opacity: 1; transform: none }
}
body.seen .enter { animation: none; }
"""

JS = """
<script>
/* Entrance animations run once per device, then stop.
   Jason, 2026-09-07: "turn off animations after the person logs in."

   localStorage rather than a session flag: he means the daily user, and a
   session flag would replay the whole entrance every morning, which is
   exactly the thing being removed.

   Wrapped in try/catch and set BEFORE first paint: a private window or
   blocked site data throws on access, and an exception here would leave the
   class unset and the animation running -- a failure that is invisible in
   testing and permanent for that person. */
(function () {
  try {
    if (localStorage.getItem('seen-entrance')) {
      document.documentElement.classList.add('pre-seen');
    } else {
      localStorage.setItem('seen-entrance', '1');
    }
  } catch (e) { /* storage unavailable -- animate, which is the safe default */ }
  document.addEventListener('DOMContentLoaded', function () {
    if (document.documentElement.classList.contains('pre-seen')) {
      document.body.classList.add('seen');
    }
    /* Count-ups start only once visible, so a number below the fold has not
       already finished counting by the time it is scrolled to. */
    var tallies = document.querySelectorAll('.tally[style*="--n"]');
    if (!tallies.length || !window.IntersectionObserver) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('run'); io.unobserve(en.target); }
      });
    }, { threshold: 0.4 });
    tallies.forEach(function (t) { io.observe(t); });
  });
})();
</script>
"""

ANCHOR = ".card{background:var(--panel)"
assert ANCHOR in s, "card rule not found"
s = s.replace(ANCHOR, CSS.lstrip("\n") + ANCHOR, 1)

# The script goes last so the DOM it touches exists.
assert "</body>" in s, "no </body>"
s = s.replace("</body>", JS.strip() + "\n</body>", 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("base.html: counters, glow, :has(), reduced-motion, play-once")
