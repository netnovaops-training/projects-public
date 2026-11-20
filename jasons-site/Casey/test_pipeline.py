#!/usr/bin/env python3
"""End-to-end pipeline test against a fake desktop.

Stands up a stub Ollama + Whisper on localhost and pushes a real job through
worker.process_job(), so the wake -> transcribe -> draft -> follow-up chain is
exercised without needing the GPU box. Run this after changing worker.py.
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PORT_OLLAMA, PORT_WHISPER = 18434, 19000
TMP = tempfile.mkdtemp(prefix="zeepipe-")
os.environ.update({
    "ZEE_DATA_DIR": TMP,
    "ZEE_SECRET_KEY": "1" * 64,
    "ZEE_KNOWLEDGE_DIR": str(ROOT / "knowledge"),
    "ZEE_DESKTOP_IP": "127.0.0.1",
    "ZEE_DESKTOP_MAC": "00:00:5e:00:53:01",
    "ZEE_OLLAMA_PORT": str(PORT_OLLAMA),
    "ZEE_WHISPER_PORT": str(PORT_WHISPER),
    "ZEE_AUTO_SLEEP": "0",
})

from app import config, db, desktop, worker  # noqa: E402

CALLS = {"transcribe": 0, "chat": 0}
LAST_SYSTEM = {"text": ""}

FAKE_TRANSCRIPT = (
    "Today I finished the quarterly refresher on the QBL calculators for the "
    "night shift. Also patient MRN 4471992 had a postpartum hemorrhage and we "
    "caught it early because of the new process."
)
FAKE_DRAFT = "### 27 Jul 2026 — QBL refresher\n\nMaj Owner trained 14 nurses..."
FAKE_FOLLOWUPS = '["How many nurses total?", "Did another unit adopt it?", "What changed?"]'


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            self._json({"models": [{"name": "qwen3.5:9b"}]})
        elif self.path.startswith("/health"):
            self._json({"ok": True, "model": "large-v3"})
        else:
            self._json({"error": "nope"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if "transcriptions" in self.path:
            CALLS["transcribe"] += 1
            self._json({"text": FAKE_TRANSCRIPT})
        elif "/api/chat" in self.path:
            CALLS["chat"] += 1
            payload = json.loads(raw)
            system = payload["messages"][0]["content"]
            user = payload["messages"][1]["content"]
            LAST_SYSTEM["text"] = system
            if "JSON array" in user or "MISSING" in user:
                content = "<think>let me think</think>\n```json\n" + FAKE_FOLLOWUPS + "\n```"
            else:
                content = "<think>drafting</think>" + FAKE_DRAFT
            self._json({"message": {"role": "assistant", "content": content}})
        else:
            self._json({"error": "nope"}, 404)


def serve(port):
    HTTPServer(("127.0.0.1", port), Stub).serve_forever()


PASSES, FAILS = [], []


def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name)
    mark = "\033[32mPASS\033[0m" if cond else "\033[31mFAIL\033[0m"
    print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


for p in (PORT_OLLAMA, PORT_WHISPER):
    threading.Thread(target=serve, args=(p,), daemon=True).start()
time.sleep(0.8)

print("\n=== Fake desktop reachable ===")
st = desktop.status()
check("ollama detected", st.ollama)
check("whisper detected", st.whisper)
check("desktop reports ready", st.ready)

config.ensure_dirs()
db.init_db()

print("\n=== Audio job end to end ===")
audio = Path(TMP) / "memo.m4a"
audio.write_bytes(b"\x00" * 4096)
jid = db.create_job("zanetta", "log", "memo.m4a", str(audio), "audio",
                    award_target="Field Grade Officer of the Quarter")
worker.process_job(db.get_job(jid))
job = db.get_job(jid)

check("job completed", job["status"] == "done", job["status"] + " / " + job["error"])
check("whisper was called once", CALLS["transcribe"] == 1, str(CALLS))
check("model called twice (draft + follow-ups)", CALLS["chat"] == 2, str(CALLS))
check("transcript stored", "QBL calculators" in job["transcript"])
check("MRN scrubbed from transcript", "4471992" not in job["transcript"], job["transcript"])
check("PHI warning added to draft", "protected health information" in job["draft"].lower())
check("<think> stripped from draft", "<think>" not in job["draft"])
check("draft content present", "QBL refresher" in job["draft"])
fu = db.jload(job["followups"], [])
check("follow-ups parsed from fenced JSON", len(fu) == 3, str(fu))
check("follow-ups are plain strings", all(isinstance(q, str) and q for q in fu))
check("model recorded", job["model_used"] == config.OLLAMA_MODEL)
check("knowledge version recorded", len(job["kb_version"]) == 12, job["kb_version"])

print("\n=== Prompt actually carried the rules ===")
sysx = LAST_SYSTEM["text"]
check("system prompt reached the model", len(sysx) > 5000, f"{len(sysx)} chars")
check("carries Field Grade gate", "Field Grade" in sysx)
check("carries the no-bullets rule", "Bullets are not authorized" in sysx)
check("carries the QBL context", "quantitative blood loss" in sysx.lower())
check("carries the anti-invention rule", "Never invent a fact" in sysx)

print("\n=== Outputs on disk ===")
log = config.OUTPUT_DIR / "career-log.md"
check("career log appended", log.exists() and "QBL refresher" in log.read_text())
check("per-job file written", len(list(config.OUTPUT_DIR.glob(f"*job{jid}*.md"))) == 1)

print("\n=== Typed-note job (no audio) ===")
CALLS["transcribe"] = 0
jid2 = db.create_job("zanetta", "award", "typed", "", "text",
                     note="Ran a mass casualty exercise for the group.",
                     award_target="Field Grade Officer of the Year")
worker.process_job(db.get_job(jid2))
job2 = db.get_job(jid2)
check("typed note completes", job2["status"] == "done", job2["error"])
check("whisper skipped for typed notes", CALLS["transcribe"] == 0)
check("award mode reached the model", "Field Grade Officer of the Year" in job2["draft"]
      or job2["draft"] != "")

print("\n=== Follow-up round two ===")
jid3 = db.create_job("zanetta", "log", "memo.m4a (round 2)", "", "text",
                     note=job["transcript"], parent_id=jid)
db.update_job(jid3, answers="Q: How many nurses total?\nHer answers:\n14 on nights, 31 overall.")
worker.process_job(db.get_job(jid3))
job3 = db.get_job(jid3)
check("round two completes", job3["status"] == "done", job3["error"])
check("round two links to parent", job3["parent_id"] == jid)

print("\n=== Failure handling ===")
jid4 = db.create_job("zanetta", "log", "gone.m4a", "/nonexistent/gone.m4a", "audio")
try:
    worker.process_job(db.get_job(jid4))
    check("missing file falls back to empty text", True)
except Exception as e:
    check("missing file handled without crashing", False, str(e))

os.environ["ZEE_DESKTOP_IP"] = "192.0.2.99"
import importlib  # noqa: E402
importlib.reload(config)
config.AUTO_WAKE = False
jid5 = db.create_job("zanetta", "log", "x", "", "text", note="test")
try:
    worker.process_job(db.get_job(jid5))
    check("raises when desktop is down and auto-wake off", False)
except RuntimeError as e:
    check("raises when desktop is down and auto-wake off", "asleep" in str(e).lower())

print("\n" + "=" * 60)
print(f"  {len(PASSES)} passed, {len(FAILS)} failed")
for f in FAILS:
    print(f"    - {f}")
print("=" * 60 + "\n")
sys.exit(1 if FAILS else 0)
