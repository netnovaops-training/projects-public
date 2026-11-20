"""Her record, in a form that survives this machine.

Jason asked how to set rsync up. The transfer turned out to be the easy
half and very nearly the wrong thing to worry about, so this module is
mostly about the other half.

THE ACTUAL RISK IS NOT THE NETWORK, IT IS THE SNAPSHOT
--------------------------------------------------------
zeeportal.db is SQLite in WAL mode. At the moment of writing this the
database was 3.6 MB with a 4.1 MB write-ahead log beside it -- meaning
MORE THAN HALF of what she has entered was living in the -wal file and
not yet folded into the .db at all.

Copy that .db with rsync, scp, cp, or a file-sync tool of any kind while
the app is running, and what you get is a torn database missing its most
recent writes. It restores. It opens. It is simply missing things, and
you find out which things at the worst possible moment. Nothing about
rsync causes that and nothing about rsync prevents it -- it is a property
of copying a live database as a file.

sqlite3's own backup API is the fix and costs one line: it walks the
database under a read lock, follows the WAL, and produces a file that is
internally consistent as of the moment it finished. THEN copy it with
whatever you like.

3.6 MB also means rsync's delta transfer -- its whole reason for
existing -- saves nothing measurable here. It was the right question and
the answer is that the tool barely matters at this size. What matters is
that the thing being copied is coherent.

WHAT GOES OUT, AND WHY IT IS THREE THINGS
1. A consistent .db  -- the restore path. Everything, exactly.
2. Markdown + CSV    -- readable by a person and by an AI with no code,
                        which is what "readable by AI" in Jason's list
                        actually needs. A SQLite file is not that.
3. A manifest        -- what was taken and when, so a restore can tell
                        whether it is holding last night or last month.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, db, exports, portfolio

BACKUP_DIR = config.DATA_DIR / "backup"
KEEP = 14                     # nightly snapshots kept on this machine


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def snapshot_db(dest: Path) -> tuple[bool, str]:
    """A consistent copy of the live database. See this module's header.

    sqlite3.Connection.backup() is the online backup API: it holds a read
    lock, follows the WAL, and either produces a coherent file or raises.
    There is no partial-success case to handle, which is the point of
    using it instead of copying bytes.
    """
    try:
        src = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True,
                              timeout=30)
        try:
            out = sqlite3.connect(str(dest))
            try:
                src.backup(out)
            finally:
                out.close()
        finally:
            src.close()
        return True, f"{dest.stat().st_size} bytes"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def run() -> dict:
    """One backup. Returns what it wrote, for the log and the manifest."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    folder = BACKUP_DIR / stamp
    folder.mkdir(exist_ok=True)
    written, failed = [], []

    ok, why = snapshot_db(folder / "zeeportal.db")
    (written if ok else failed).append(f"zeeportal.db ({why})")

    # The readable half. Each is wrapped separately: a missing docx
    # library must not cost her the markdown, and the markdown is the
    # one that matters most for reading later.
    for name, fn in (("career-log.md", exports.write_markdown),
                     ("career-log.csv", exports.write_csv)):
        try:
            fn(folder / name)
            written.append(name)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{name} ({e})")
    try:
        (folder / "portfolio.md").write_text(exports.portfolio_markdown(),
                                             encoding="utf-8")
        written.append("portfolio.md")
    except Exception as e:  # noqa: BLE001
        failed.append(f"portfolio.md ({e})")
    try:
        exports.write_portfolio_csv(folder / "portfolio.csv")
        written.append("portfolio.csv")
    except Exception as e:  # noqa: BLE001
        failed.append(f"portfolio.csv ({e})")

    # WHAT WAS TRUE WHEN THIS WAS TAKEN. A restore that cannot tell how
    # stale it is has to be trusted blindly, and nobody restores a backup
    # on a good day.
    try:
        p = portfolio.progress()
        manifest = {
            "taken_at": stamp,
            "taken_at_unix": time.time(),
            "portfolio_entries": p.get("total", 0),
            "exchanges": p.get("exchanges", 0),
            "recordings": p.get("recordings", 0),
            "ready_unsent": len(p.get("ready_unsent") or []),
            "written": written,
            "failed": failed,
        }
        (folder / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        failed.append(f"manifest.json ({e})")

    # LATEST IS A REAL DIRECTORY, NOT A SYMLINK. Whatever picks these up
    # -- rsync, rclone, scp, a Windows scheduled task -- should not have
    # to care about symlink semantics on three operating systems.
    latest = BACKUP_DIR / "latest"
    try:
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(folder, latest)
    except Exception as e:  # noqa: BLE001
        failed.append(f"latest ({e})")

    _prune()
    db.log_event("info" if not failed else "warn", "backup",
                 f"{stamp}: wrote {len(written)}"
                 + (f", FAILED {'; '.join(failed)}" if failed else ""))
    return {"stamp": stamp, "folder": str(folder),
            "written": written, "failed": failed}


def _prune() -> None:
    try:
        folders = sorted(
            (p for p in BACKUP_DIR.iterdir()
             if p.is_dir() and p.name != "latest"),
            key=lambda p: p.name)
        for old in folders[:-KEEP]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


def status() -> dict:
    """When the last one was, and whether that is recent enough to trust."""
    latest = BACKUP_DIR / "latest" / "manifest.json"
    if not latest.exists():
        return {"ok": False, "why": "No backup has been taken yet."}
    try:
        m = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"The manifest is unreadable: {e}"}
    age = time.time() - float(m.get("taken_at_unix") or 0)
    return {
        "ok": age < 48 * 3600,
        "why": ("Last backup " + ("%.1f hours" % (age / 3600) if age < 86400
                                  else "%.1f days" % (age / 86400)) + " ago."),
        "taken_at": m.get("taken_at", ""),
        "entries": m.get("portfolio_entries", 0),
        "failed": m.get("failed") or [],
    }
