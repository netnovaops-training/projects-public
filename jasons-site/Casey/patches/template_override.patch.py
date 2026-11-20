#!/usr/bin/env python3
"""Let each instance define its own output shape. Run from Casey/.

Found 2026-09-07 by running a real upload through /ability before Jason
started using it. The draft came back correct in structure and wrong in
vocabulary:

    **Scope:** [NEEDED: ...], echelon: [NEEDED: unit / group / wing / MAJCOM]

MAJCOM, in a State of New York IT record. The knowledge base was swapped for
his instance but `TASK_PROMPTS` in worker.py is hardcoded, so every draft on
every instance is shaped by an Air Force template regardless of whose record
it is. Also hardcoded in it:

  * "what SHE personally did"          -- assumes Casey
  * "AF Form 1206 performance-statement style"
  * "Third person, 'Maj Owner ...'"   -- see below
  * "Category fit: which 1206 category"
  * "Awards this could feed"           -- there is no catalog on his side

THE "Maj Owner" LINE IS A LIVE BUG ON HER SIDE TOO, and it explains
something Jason reported days ago. Her profile is explicit that she is
`Capt Foster` -- Captain, not Major, and Foster since she married -- with a
note that writing her as a Major misrepresents the rank she held when she
did the work. But this template instructs the model to write "Maj Owner"
by name, which is how the career log ended up saying exactly that. The
knowledge base said one thing and the template said another, and the
template is nearer the model.

THE FIX: the template becomes overridable per instance. If
`KNOWLEDGE_DIR/_template.md` exists it is used; otherwise the built-in
applies unchanged, so nothing about her instance moves unless a file is
put there deliberately.

And the hardcoded name goes. The template now says to use the name and rank
from the profile rather than naming a person in the prompt -- so the day her
rank changes, one line in one file changes, which is what the profile
already promises.
"""
import io
import sys

P = "app/worker.py"
s = io.open(P, encoding="utf-8").read()
if "_template.md" in s:
    sys.exit("already patched")

# --- 1. the hardcoded name and rank -----------------------------------------
OLD = ('<ONE standalone sentence in AF Form 1206 performance-statement style. '
       'Third person, "Maj Owner ...". Must contain at least one number.')
NEW = ('<ONE standalone sentence in AF Form 1206 performance-statement style. '
       'Third person, using EXACTLY the name and rank given in the profile '
       'section above -- do not substitute a different rank or surname, and '
       'do not promote her. Must contain at least one number.')
if OLD in s:
    s = s.replace(OLD, NEW, 1)
    print("  removed the hardcoded 'Maj Owner' -- it now follows the profile")
else:
    print("  WARNING: the 'Maj Owner' string was not where expected")

# --- 2. the template becomes overridable ------------------------------------
import re
m = re.search(r"^TASK_PROMPTS\s*=", s, re.M)
assert m, "TASK_PROMPTS not found"

OVERRIDE = '''
def _template_override() -> str:
    """An instance's own output template, if it ships one.

    Found by running a real upload through /ability before it was used: the
    knowledge base had been swapped for Jason but the output template had
    not, so his State IT record came back asking for the "echelon: unit /
    group / wing / MAJCOM". The knowledge base is per-instance; the shape of
    the answer was not.

    If `KNOWLEDGE_DIR/_template.md` exists, its contents replace the `log`
    template. Absent -- which is Casey's case -- nothing changes at all, so
    this cannot alter her drafts by accident.

    The leading underscore keeps it out of `knowledge_files()`, which globs
    `*.md` into the system prompt. Without that the template would be
    concatenated into the prompt as well as used as the template, and the
    model would see the instructions twice.
    """
    try:
        p = config.KNOWLEDGE_DIR / "_template.md"
        if p.is_file():
            t = p.read_text(encoding="utf-8").strip()
            if len(t) > 80:            # a stub or an empty file is not a template
                return t
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "template", f"could not read _template.md: {e}")
    return ""


'''
s = s[:m.start()] + OVERRIDE.lstrip("\n") + s[m.start():]

# Apply it where the task text is chosen.
OLD2 = """    mode = job["mode"] if job["mode"] in TASK_PROMPTS else "log"
    task = TASK_PROMPTS[mode].format("""
NEW2 = """    mode = job["mode"] if job["mode"] in TASK_PROMPTS else "log"
    # An instance may ship its own output shape -- see _template_override().
    # Only the default `log` mode is overridable; the specialised modes stay
    # as they are until something needs otherwise.
    _tpl = _template_override() if mode == "log" else ""
    task = (_tpl or TASK_PROMPTS[mode]).format("""
assert OLD2 in s, "task selection not found"
s = s.replace(OLD2, NEW2, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("worker.py: per-instance output template")
