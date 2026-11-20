# patches/

One-shot scripts that made a specific change to this application, kept
rather than deleted.

**These are history, not code.** Nothing here runs as part of the app, and
nothing imports from here. Each script was written to make one change, was
run once, and asserts on every anchor it edits — so re-running one either
does nothing (it detects its own work) or fails loudly rather than editing
the wrong thing twice.

## Why keep them

The reasoning is the point. A diff shows *what* changed; these say *why*,
in the words of the moment, including the things that were tried and
rejected. Several record a wrong turn that is worth not repeating:

- `document_date.patch.py` — entries were stamped with the upload date, so a
  2023 award was filed as September 2026.
- `normalise_dates.patch.py` — the same bug one layer deeper: the field the
  record *sorts* by was prose, and every reader silently fell back to the
  created timestamp.
- `keep_extension.patch.py` — an 80-character filename truncation dropped
  `.pdf`, and the resulting "unsupported document type" was reported to the
  user as a scan needing OCR. It was not a scan.
- `worker_uses_ask.patch.py` — the drafting path called `llm.chat()` and
  skipped the whole model chain, so every draft ever written came from the
  local model even with a working Gemini key present.
- `ocr_and_email.patch.py` — the portal told the user to go and upload the
  same file somewhere else so a different pipeline could read it.

## Running one again

You should not need to. If you do:

```bash
cd Casey && python patches/<name>.patch.py
```

They expect to be run from the application root, not from this directory.
The data-migration ones (`add_education.py`, `hs_awards.py`,
`backfill_dates.py`) run *inside* the container, because that is where the
database is; `backfill_dates.py` is a dry run unless given `--write`.
