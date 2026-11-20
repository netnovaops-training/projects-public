#!/usr/bin/env python3
"""Self-test for the portal. Run before deploying, and after any edit.

    /opt/zeeportal/venv/bin/python test_portal.py

It exercises auth, upload, access control, the WoL packet builder, PHI
scrubbing, knowledge loading, and the model-output parsers. It never touches
the real database or contacts the desktop.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="zeetest-")
os.environ.update({
    "ZEE_DATA_DIR": TMP,
    "ZEE_KNOWLEDGE_DIR": str(ROOT / "knowledge"),
    "ZEE_DESKTOP_IP": "192.0.2.10",          # TEST-NET-1, guaranteed unroutable
    "ZEE_DESKTOP_MAC": "00:00:5e:00:53:01",
    "ZEE_ROOT_PATH": "/casey",
    "ZEE_AUTO_WAKE": "0",
    "ZEE_AUTO_SLEEP": "0",
    "ZEE_OWNERS": "tester@example.com",
})

from fastapi.testclient import TestClient  # noqa: E402
from app import config, db, desktop, llm, worker  # noqa: E402
from app.main import app  # noqa: E402

PASSES, FAILS = [], []


def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name)
    mark = "\033[32mPASS\033[0m" if cond else "\033[31mFAIL\033[0m"
    print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


print("\n=== Wake-on-LAN packet ===")
pkt = desktop.build_magic_packet("00:00:5e:00:53:01")
check("magic packet is 102 bytes", len(pkt) == 102, f"got {len(pkt)}")
check("starts with 6x 0xFF", pkt[:6] == b"\xff" * 6)
check("MAC repeated 16 times", pkt[6:] == bytes.fromhex("AABBCCDDEEFF") * 16)
check("accepts dashed MAC", desktop.build_magic_packet("00-00-5e-00-53-03") == pkt)
check("accepts bare hex", desktop.build_magic_packet("aabbccddeeff") == pkt)
check("normalises MAC", desktop.normalize_mac("aabb.ccdd.eeff") == "00:00:5e:00:53:01")
try:
    desktop.build_magic_packet("nope")
    check("rejects bad MAC", False)
except ValueError:
    check("rejects bad MAC", True)

print("\n=== PHI scrubbing ===")
for raw, must_go in [
    ("Patient SSN 123-45-6789 came in", "123-45-6789"),
    ("MRN: 8837261 admitted", "8837261"),
    ("DOB 04/12/1988 noted", "04/12/1988"),
    ("medical record number 5512 on file", "5512"),
]:
    out, hits = worker.scrub_phi(raw)
    check(f"scrubs {must_go!r}", must_go not in out and bool(hits), out)
clean, hits = worker.scrub_phi("Trained 14 nurses; hemorrhage rate fell 30%")
check("leaves clean clinical text alone", "14 nurses" in clean and "30%" in clean and not hits)

print("\n=== Model output parsing ===")
check("strips <think> blocks",
      llm.strip_thinking("<think>hmm</think>Real answer").strip() == "Real answer")
check("handles unterminated <think>",
      "Real" in llm.strip_thinking("Real answer<think>dangling"))
check("parses fenced JSON array",
      llm.extract_json('Sure:\n```json\n["a","b"]\n```') == ["a", "b"])
check("parses bare JSON array", llm.extract_json('["x"]') == ["x"])
check("parses JSON object", llm.extract_json('{"q":["y"]}') == {"q": ["y"]})
check("returns None on garbage", llm.extract_json("no json at all") is None)

print("\n=== Knowledge base ===")
kb, ver = llm.load_knowledge()
check("knowledge files found", len(llm.knowledge_files()) >= 4,
      f"{[f.name for f in llm.knowledge_files()]}")
check("knowledge text loaded", len(kb) > 5000, f"{len(kb)} chars")
check("version is a stable hash", ver == llm.load_knowledge()[1] and ver != "empty")
for needle in ("Field Grade", "Bullets are not authorized", "[NEEDED:",
               "JSON array of strings"):
    check(f"knowledge contains {needle!r}", needle in kb)

print("\n=== System prompt assembly ===")
sysprompt, kbver = worker.build_system_prompt()
check("system prompt includes knowledge", len(sysprompt) > len(kb))
check("system prompt forbids invention", "Never invent a fact" in sysprompt)
check("system prompt forbids PHI", "protected health information" in sysprompt)
for mode in ("log", "award", "interview"):
    t = worker.TASK_PROMPTS[mode].format(date="27 Jul 2026", award_target="X")
    check(f"{mode!r} task prompt formats", len(t) > 100)

print("\n=== Database ===")
db.init_db()
# THE APP HAS NO LOGIN OF ITS OWN ANY MORE -- an account is made on first
# sight of a signed-in address (see db.user_for_email(), same pattern as
# Mom/app/core.py's user_for_email()), and "admin" is derived from
# config.OWNERS (ZEE_OWNERS / ADMIN_OWNERS), not a role typed into a form.
row = db.user_for_email("tester@example.com")
check("account made on first sight", row is not None)
check("in ZEE_OWNERS -> admin", row["role"] == "admin")
row2 = db.user_for_email("sister@example.com")
check("not in ZEE_OWNERS -> plain user", row2["role"] == "user")
check("username is the lowercased email", row2["username"] == "sister@example.com")
check("calling it again returns the same row, not a duplicate",
      db.user_for_email("TESTER@example.com")["username"] == row["username"])

jid = db.create_job("sister@example.com", "log", "memo.m4a", "/tmp/x.m4a", "audio", note="hi")
check("job created", jid > 0)
db.update_job(jid, status="done", draft="a draft", followups='["q1","q2"]')
j = db.get_job(jid)
check("job updated", j["status"] == "done" and j["draft"] == "a draft")
check("followups parse", db.jload(j["followups"], []) == ["q1", "q2"])
check("job listing scoped by user", len(db.list_jobs("sister@example.com")) == 1
      and len(db.list_jobs("nobody@example.com")) == 0)

db.update_job(jid, status="drafting")
check("stuck jobs requeue on restart", db.requeue_stuck_jobs() == 1
      and db.get_job(jid)["status"] == "queued")
db.update_job(jid, status="done")

print("\n=== HTTP surface ===")
# THE APP HAS NO LOGIN OF ITS OWN -- Caddy's forward_auth is what turns a
# real sign-in into this header (see main.py's current_user() docstring),
# so a test client sets it directly the same way Mom/tools/test_growth.py's
# TestClient does.
client = TestClient(app, base_url="https://testserver")

r = client.get("/", follow_redirects=False)
check("an unauthenticated request is refused, not served",
      r.status_code == 401, f"{r.status_code}")
check("healthz is public", client.get("/healthz").json() == {"ok": True})
check("anonymous API is refused",
      client.get("/api/status", follow_redirects=False).status_code == 401)

client.headers["X-Auth-Email"] = "tester@example.com"   # in ZEE_OWNERS -> admin

dash = client.get("/")
dash_flat = " ".join(dash.text.split())  # collapse HTML line wrapping
check("dashboard renders", dash.status_code == 200 and "Add something new" in dash.text)
check("template links carry the /casey prefix", 'action="/casey/upload"' in dash.text)
check("no bare-root links leaked", 'href="/"' not in dash.text and 'action="/upload"' not in dash.text)
check("dashboard lists award targets", "Field Grade Officer of the Quarter" in dash.text)
check("dashboard warns about PHI", "medical record numbers" in dash_flat)
check("dashboard warns about classification", "CUI" in dash_flat)

st = client.get("/api/status")
check("status API responds", st.status_code == 200 and "desktop" in st.json())
check("unreachable desktop reports not-ready", st.json()["desktop"]["ready"] is False)

r = client.post("/upload", data={"note": "", "mode": "log"}, follow_redirects=False)
check("empty upload rejected", r.status_code == 400)

r = client.post("/upload", data={"note": "Trained 14 nurses on QBL today.", "mode": "log"},
                follow_redirects=False)
check("typed note accepted", r.status_code == 303 and "/casey/job/" in r.headers["location"])
new_id = int(r.headers["location"].split("/")[-1])
check("job row created from note", db.get_job(new_id)["note"].startswith("Trained 14"))

r = client.post("/upload",
                files={"file": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")},
                data={"mode": "log"}, follow_redirects=False)
check("disallowed extension rejected", r.status_code == 400)

r = client.post("/upload",
                files={"file": ("memo.m4a", b"\x00" * 2048, "audio/mp4")},
                data={"mode": "award", "award_target": "Field Grade Officer of the Quarter"},
                follow_redirects=False)
check("audio upload accepted", r.status_code == 303)
audio_id = int(r.headers["location"].split("/")[-1])
saved = db.get_job(audio_id)
check("audio classified as audio", saved["kind"] == "audio")
check("upload written to disk", Path(saved["stored_path"]).exists())
check("stored filename is sanitised", ".." not in Path(saved["stored_path"]).name)

check("job page renders", client.get(f"/job/{audio_id}").status_code == 200)
check("job download works", client.get(f"/job/{new_id}/download").status_code == 200)
check("admin page renders for admin", "Knowledge base" in client.get("/admin").text)
check("nonexistent job is 404", client.get("/job/999999").status_code == 404)

# Access control: the sister must not see the admin's jobs.
client2 = TestClient(app, base_url="https://testserver")
client2.headers["X-Auth-Email"] = "sister@example.com"   # not in ZEE_OWNERS
check("non-admin blocked from /admin", client2.get("/admin").status_code == 403)
check("non-admin cannot read another user's job",
      client2.get(f"/job/{audio_id}").status_code == 404)
check("non-admin cannot download another user's job",
      client2.get(f"/job/{audio_id}/download").status_code == 404)
check("non-admin cannot wake the desktop",
      client2.post("/admin/wake", follow_redirects=False).status_code == 403)

r = client.post(f"/job/{new_id}/answer", data={"answers": "1. Fourteen. 2. Yes."},
                follow_redirects=False)
check("follow-up answers create a child job", r.status_code == 303)
child = db.get_job(int(r.headers["location"].split("/")[-1]))
check("child job links to parent", child["parent_id"] == new_id)
check("child job carries her answers", "Fourteen" in child["answers"])

print("\n=== Output writing ===")
db.update_job(audio_id, status="done", draft="### Test draft\nBody.",
              transcript="raw words", followups='["q?"]', kb_version="abc123")
worker.write_outputs(audio_id)
log = config.OUTPUT_DIR / "career-log.md"
check("career log written", log.exists() and "Test draft" in log.read_text())
per_job = list(config.OUTPUT_DIR.glob(f"*job{audio_id}*.md"))
check("per-job markdown written", len(per_job) == 1)
if per_job:
    txt = per_job[0].read_text()
    check("per-job file records provenance", "abc123" in txt and "q?" in txt)

print("\n" + "=" * 60)
print(f"  {len(PASSES)} passed, {len(FAILS)} failed")
if FAILS:
    print("\n  Failures:")
    for f in FAILS:
        print(f"    - {f}")
print("=" * 60 + "\n")
sys.exit(1 if FAILS else 0)
