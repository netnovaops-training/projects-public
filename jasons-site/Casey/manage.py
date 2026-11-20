#!/usr/bin/env python3
"""Command-line admin for the portal. Run from /opt/zeeportal with the venv python.

  sudo -u zeeportal /opt/zeeportal/venv/bin/python manage.py users
  sudo -u zeeportal /opt/zeeportal/venv/bin/python manage.py wake
  sudo -u zeeportal /opt/zeeportal/venv/bin/python manage.py sleep
  sudo -u zeeportal /opt/zeeportal/venv/bin/python manage.py status
  sudo -u zeeportal /opt/zeeportal/venv/bin/python manage.py kb

NO adduser OR passwd HERE ANY MORE. This app has no login of its own -- see
app/main.py's current_user() docstring. Who can sign in at all, everywhere
including here, is the admin's own People page (Admin/auth/people.json);
who counts as an admin specifically at /casey is the ZEE_OWNERS (or shared
ADMIN_OWNERS) address list in .env. Both take effect without touching this
box's local database, which is why those two subcommands are gone rather
than kept as something that would silently do nothing useful.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config, db, desktop, llm  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Career Portal admin")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("users")
    sub.add_parser("wake")
    sub.add_parser("sleep")
    sub.add_parser("status")
    sub.add_parser("kb")

    args = p.parse_args()
    config.ensure_dirs()
    db.init_db()

    if args.cmd == "users":
        rows = db.list_users()
        if not rows:
            print("No users yet.")
        for r in rows:
            print(f"{r['username']:20} {r['role']:6} {r['display_name']}")

    elif args.cmd == "wake":
        print("Sending magic packet...")
        desktop.send_wol()
        st = desktop.wake_and_wait(on_progress=lambda m: print("  " + m))
        print(f"ollama={st.ollama} whisper={st.whisper} ssh={st.ssh} ready={st.ready}")
        return 0 if st.ready else 2

    elif args.cmd == "sleep":
        ok, msg = desktop.hibernate()
        print(("OK: " if ok else "FAILED: ") + msg)
        return 0 if ok else 2

    elif args.cmd == "status":
        st = desktop.status()
        print(f"desktop  {config.DESKTOP_IP}  mac={config.DESKTOP_MAC}")
        print(f"  ollama   {'up' if st.ollama else 'down'}")
        print(f"  whisper  {'up' if st.whisper else 'down'}")
        print(f"  ssh      {'up' if st.ssh else 'down'}")
        print(f"  ready    {st.ready}")
        print(f"models: {', '.join(llm.available_models()) or '(none/unreachable)'}")
        print(f"queued/active jobs: {db.active_job_count()}")

    elif args.cmd == "kb":
        text, version = llm.load_knowledge()
        print(f"knowledge dir: {config.KNOWLEDGE_DIR}")
        for f in llm.knowledge_files():
            print(f"  {f.name}")
        print(f"version: {version}   chars: {len(text)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
