#!/usr/bin/env python3
"""Replace the record line-chart with a month grid. Run from Casey/.

Jason, 2026-09-07: "I want this graph to be more beautiful, it doesn't seem
to look very helpful."

Both true, and they have the same cause: it is the wrong FORM for the data.

WHY THE LINE CHART FAILS HERE. A line chart draws a continuous quantity and
interpolates between its points -- the segment between two dots asserts that
values existed in between. "Entries added per month" has no in-between: it
is a count of discrete events at discrete times. With one entry in
twenty-four months the chart renders a flat line along zero and a single
spike at the end, which is not a picture of her record. It is a picture of
an axis.

It also gets less useful as it gets more correct. Because the series is
cumulative, every quiet month is drawn as a flat segment, so a year of
steady work and a year of nothing look nearly identical at a glance -- the
one question the graph should answer.

WHAT REPLACES IT. A month grid: one cell per month, laid out on calendar
columns so January is always column one, shaded by how much went in. This
is the standard form for sparse periodic activity for a reason:

  * It reads correctly at ONE entry. Twenty-three quiet cells and one lit
    one is an honest, legible picture, where a line chart had to invent a
    slope to draw anything at all.
  * Consistency becomes the visible thing. Gaps, runs and rhythm are the
    shape of the grid, which is what somebody actually wants to know about
    their own record.
  * It stays readable as it fills up, where the cumulative line only ever
    approaches a diagonal.

THE HEADLINE NUMBERS ARE THE OTHER HALF. "1 entry over 24 months" told her
the two least useful facts available. Active months, the busiest month and
when she last added something are what the picture cannot show and what she
would actually act on.

ENCOURAGEMENT WITHOUT LYING. The old caption said "the line only goes up --
a quiet month costs you nothing", which was doing real work: this is a
career record kept by somebody with children, a move and a new job, and a
chart that reads as failure gets closed. The grid keeps that, but says it
with an empty cell that is simply quiet rather than a flat line that looks
like a stall.
"""
import io
import sys

P = "app/templates/dashboard.html"
s = io.open(P, encoding="utf-8").read()
if "record-grid" in s:
    sys.exit("already patched")

OLD_START = "  {% set w = 640 %}{% set h = 120 %}{% set n = growth.series|length %}"
OLD_END = """  <p class="small muted" style="margin:.5rem 0 0">
    Every dot is a month you added something. The line only goes up &mdash; a
    quiet month costs you nothing.
  </p>"""

i = s.find(OLD_START)
j = s.find(OLD_END)
assert i > 0, "chart start not found"
assert j > i, "caption not found"
j += len(OLD_END)

NEW = """  {#
    A MONTH GRID, NOT A LINE (2026-09-07). A line chart interpolates between
    its points -- it asserts values existed in between -- and "entries this
    month" has no in-between. At one entry in twenty-four months the old
    chart drew a flat line along zero and one spike, which pictured the axis
    rather than her record. Worse, being cumulative, a quiet year and a busy
    year looked nearly alike, which is the one question it should answer.

    Cells sit on calendar columns so January is always column one. Reading
    down a column compares the same month across years; reading across a row
    is a year. Neither is possible with a line.
  #}
  {% set active = growth.series | selectattr('added') | list %}
  {% set busiest = (active | map(attribute='added') | max) if active else 0 %}
  {% set last = active[-1] if active else None %}
  {% set MONTHS = ['J','F','M','A','M','J','J','A','S','O','N','D'] %}

  <style>
    .record-grid { margin-top: .9rem; }
    .record-grid .yr {
      display: grid;
      grid-template-columns: 2.6rem repeat(12, minmax(0, 1fr));
      gap: 4px; align-items: center; margin-bottom: 4px;
    }
    .record-grid .yr-label {
      font-size: .72rem; color: var(--muted); letter-spacing: .04em;
      font-variant-numeric: tabular-nums;
    }
    .record-grid .cell {
      aspect-ratio: 1 / 1; border-radius: 3px;
      background: var(--line); border: 1px solid transparent;
      transition: transform .12s ease;
    }
    /* Four steps, not a continuous ramp: with counts this small a reader
       compares cells to each other, and discrete steps are easier to tell
       apart than a gradient. */
    .record-grid .l1 { background: color-mix(in srgb, var(--accent) 32%, var(--line)); }
    .record-grid .l2 { background: color-mix(in srgb, var(--accent) 62%, var(--line)); }
    .record-grid .l3 { background: var(--accent); }
    .record-grid .cell:hover { transform: scale(1.18); }
    /* The current month, marked so "now" is locatable without a label. */
    .record-grid .now { border-color: var(--ink); }
    .record-grid .months {
      display: grid; grid-template-columns: 2.6rem repeat(12, minmax(0, 1fr));
      gap: 4px; margin-top: 2px;
    }
    .record-grid .months span {
      font-size: .6rem; color: var(--muted); text-align: center;
    }
    .record-stats {
      display: flex; flex-wrap: wrap; gap: 1.4rem; margin-top: .9rem;
    }
    .record-stats .n {
      font-size: 1.5rem; font-weight: 600; line-height: 1.1;
      font-variant-numeric: tabular-nums;
    }
    .record-stats .k {
      font-size: .68rem; color: var(--muted); text-transform: uppercase;
      letter-spacing: .07em;
    }
    .record-key {
      display: flex; align-items: center; gap: .35rem; margin-left: auto;
      font-size: .68rem; color: var(--muted);
    }
    .record-key i { width: 10px; height: 10px; border-radius: 2px; display: block; }
    @media (prefers-reduced-motion: reduce) {
      .record-grid .cell { transition: none; }
      .record-grid .cell:hover { transform: none; }
    }
  </style>

  <div class="record-grid">
    {% for yr, items in growth.series | groupby('year') %}
    <div class="yr">
      <span class="yr-label">{{ yr }}</span>
      {% for p in items %}
        {% set lvl = 'l3' if p.added >= 4 else ('l2' if p.added >= 2 else ('l1' if p.added == 1 else '')) %}
        <div class="cell {{ lvl }}{{ ' now' if loop.last and yr == growth.series[-1].year else '' }}"
             style="grid-column: {{ p.month + 1 }}"
             title="{{ p.year }}-{{ '%02d'|format(p.month) }} &mdash; {{ p.added }} added, {{ p.total }} in the record by then"></div>
      {% endfor %}
    </div>
    {% endfor %}
    <div class="months">
      <span></span>
      {% for m in MONTHS %}<span>{{ m }}</span>{% endfor %}
    </div>
  </div>

  {#
    THE NUMBERS THE PICTURE CANNOT SHOW. "1 entry over 24 months" told her
    the two least useful facts available. How many months she actually
    touched it, her best month, and how long since the last one are the
    things worth acting on.
  #}
  <div class="record-stats">
    <div>
      <div class="n">{{ growth.total }}</div>
      <div class="k">{{ 'entry' if growth.total == 1 else 'entries' }}</div>
    </div>
    <div>
      <div class="n">{{ active|length }}<span class="small muted" style="font-weight:400">/{{ growth.months }}</span></div>
      <div class="k">months active</div>
    </div>
    {% if busiest %}
    <div>
      <div class="n">{{ busiest }}</div>
      <div class="k">best month</div>
    </div>
    {% endif %}
    {% if last %}
    <div>
      <div class="n" style="font-size:1.05rem;padding-top:.35rem">{{ last.year }}-{{ '%02d'|format(last.month) }}</div>
      <div class="k">last added</div>
    </div>
    {% endif %}
    <div class="record-key">
      <span>quiet</span>
      <i style="background:var(--line)"></i>
      <i class="l1" style="background:color-mix(in srgb, var(--accent) 32%, var(--line))"></i>
      <i class="l2" style="background:color-mix(in srgb, var(--accent) 62%, var(--line))"></i>
      <i style="background:var(--accent)"></i>
      <span>busy</span>
    </div>
  </div>

  {#
    The old caption was doing real work and is kept in spirit. This is a
    record kept by somebody with children, a move and a new job; a chart
    that reads as failure gets closed. An empty cell is quiet, not a stall.
  #}
  <p class="small muted" style="margin:.8rem 0 0">
    {% if growth.total == 0 %}
      Nothing here yet. One line about something you did this week is enough
      to light the first square.
    {% elif active|length <= 2 %}
      Each square is a month. Add something and this month lights up &mdash;
      quiet months cost you nothing, they just stay dark.
    {% else %}
      Each square is a month, brighter when you added more. The gaps are not
      failures; the pattern is what a record looks like being kept.
    {% endif %}
  </p>"""

s = s[:i] + NEW + s[j:]

# The header line said the two least useful facts. The stats block now
# carries them properly, so the header stops repeating a worse version.
OLD_H = """    <span class="small muted">{{ growth.total }} entr{{ 'y' if growth.total == 1 else 'ies' }}
      over {{ growth.months }} months</span>"""
NEW_H = """    <span class="small muted">last {{ growth.months }} months</span>"""
assert OLD_H in s, "header span not found"
s = s.replace(OLD_H, NEW_H, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("dashboard.html: line chart -> month grid")
