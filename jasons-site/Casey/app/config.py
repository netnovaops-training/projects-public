"""Configuration, loaded from environment (populated by systemd EnvironmentFile)."""
import os
from pathlib import Path


def _b(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# --- Paths -------------------------------------------------------------------
BASE_DIR = Path(os.getenv("ZEE_BASE_DIR", "/opt/zeeportal"))
DATA_DIR = Path(os.getenv("ZEE_DATA_DIR", "/var/lib/zeeportal"))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
DB_PATH = DATA_DIR / "zeeportal.db"
KNOWLEDGE_DIR = Path(os.getenv("ZEE_KNOWLEDGE_DIR", str(BASE_DIR / "knowledge")))

# --- Web ---------------------------------------------------------------------
SITE_NAME = os.getenv("ZEE_SITE_NAME", "Career Portal")
PUBLIC_HOST = os.getenv("ZEE_PUBLIC_HOST", "example.org")
ROOT_PATH = os.getenv("ZEE_ROOT_PATH", "/casey")   # served under a sub-path by Caddy
BIND_HOST = os.getenv("ZEE_BIND_HOST", "127.0.0.1")
BIND_PORT = _i("ZEE_BIND_PORT", 8000)
MAX_UPLOAD_MB = _i("ZEE_MAX_UPLOAD_MB", 512)

ALLOWED_EXT = {
    # audio
    ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".flac", ".mp4", ".webm", ".amr",
    # documents (for context / knowledge)
    ".pdf", ".docx", ".txt", ".md", ".rtf",
    # email, added 2026-09-07. Jason: "I want to be able to read emails and
    # docx docs files". Years of the work he wants shown -- award
    # nominations, a note from a commander, the paper trail behind an extra
    # duty -- exists only as mail. .eml costs a stdlib parser; .msg is
    # Outlook's compound-binary format and degrades to a clear message if
    # its reader is not installed.
    ".eml", ".msg",
    # photographs, added 2026-09-07. Jason: "she has many other awards, just
    # no way to scan them." The phone is the only capture device she has, so
    # a format the portal refuses is a part of her record that never exists.
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff",
}
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".flac", ".mp4", ".webm", ".amr"}

# --- Who runs this account as an admin ----------------------------------------
# Same ADMIN_OWNERS fallback shape as Mom/Kitchen (see Mom/app/core.py's own
# OWNERS comment) -- one answer to "who is an admin" rather than one per app.
OWNERS = {
    e.strip().lower()
    for e in os.getenv("ZEE_OWNERS", os.getenv("ADMIN_OWNERS",
                       "person4@example.com,person1@example.com")).split(",")
    if e.strip()
}

# --- Desktop (the GPU box) ---------------------------------------------------
DESKTOP_IP = os.getenv("ZEE_DESKTOP_IP", "")
DESKTOP_MAC = os.getenv("ZEE_DESKTOP_MAC", "")
DESKTOP_BROADCAST = os.getenv("ZEE_DESKTOP_BROADCAST", "255.255.255.255")
DESKTOP_SSH_USER = os.getenv("ZEE_DESKTOP_SSH_USER", "")
DESKTOP_SSH_KEY = os.getenv("ZEE_DESKTOP_SSH_KEY", "/var/lib/zeeportal/.ssh/id_ed25519")
WOL_PORTS = [int(p) for p in os.getenv("ZEE_WOL_PORTS", "7,9").split(",") if p.strip()]

OLLAMA_PORT = _i("ZEE_OLLAMA_PORT", 11434)
# THE SPEECH SERVICE IS ITS OWN CONTAINER. This used to default to the
# Ollama host, where nothing has ever listened on 9000 -- transcription
# could not have worked. It is a separate service on its own port.
WHISPER_HOST = os.getenv("ZEE_WHISPER_HOST", "stt")
WHISPER_PORT = _i("ZEE_WHISPER_PORT", 8092)
OLLAMA_MODEL = os.getenv("ZEE_OLLAMA_MODEL", "gemma4:12b-it-qat")
OLLAMA_NUM_CTX = _i("ZEE_OLLAMA_NUM_CTX", 32768)
# Qwen3.5 / Gemma 4 are reasoning models with thinking on by default. For
# structured drafting it burns tokens and latency for no gain.
OLLAMA_THINK = _b("ZEE_OLLAMA_THINK", "0")
OLLAMA_TIMEOUT = _i("ZEE_OLLAMA_TIMEOUT", 900)
WHISPER_TIMEOUT = _i("ZEE_WHISPER_TIMEOUT", 1800)

# --- Power management --------------------------------------------------------
AUTO_WAKE = _b("ZEE_AUTO_WAKE", "1")
AUTO_SLEEP = _b("ZEE_AUTO_SLEEP", "1")
IDLE_SLEEP_MINUTES = _i("ZEE_IDLE_SLEEP_MINUTES", 20)
BOOT_WAIT_SECONDS = _i("ZEE_BOOT_WAIT_SECONDS", 300)

# --- Who answers -------------------------------------------------------------
#  Jason is paying for an Anthropic key for THIS project specifically
#  (2026-09-03). Claude answers whenever the key is present; the house
#  model answers when it is not, so a lapsed bill or a rotated key
#  degrades the page rather than breaking it. Nothing here reaches
#  ChatGPT: a consumer subscription carries no API access, so the export
#  is the bridge -- she takes the document to ChatGPT herself.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ZEE_ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_URL = os.getenv("ZEE_ANTHROPIC_URL", "https://api.anthropic.com/v1/messages")
ANTHROPIC_MAX_TOKENS = _i("ZEE_ANTHROPIC_MAX_TOKENS", 1800)
ANTHROPIC_TIMEOUT = _i("ZEE_ANTHROPIC_TIMEOUT", 180)


# --- Gemini, the cheap middle ------------------------------------------------
#  Added 2026-09-04. She had been running entirely on the local model --
#  no Anthropic key was ever set -- which costs nothing and is weaker
#  than her packages deserve. Gemini's lite tier is the cheap option that
#  already has a working key on this machine, and it measured better than
#  the dearer Gemini tier on structured extraction elsewhere in the stack.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# The Tier 1 (billed) key, used ONLY when the free key above
# reports its quota exhausted -- see ask() in llm.py. Left empty
# the chain simply drops to the local model as it always did, so
# not setting this costs nothing and turns nothing on by accident.
GEMINI_API_KEY_PAID = os.getenv("GEMINI_API_KEY_PAID", "") or \
    os.getenv("ZEE_GEMINI_API_KEY_PAID", "")
GEMINI_MODEL = os.getenv("ZEE_GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_URL = os.getenv(
    "ZEE_GEMINI_URL",
    "https://generativelanguage.googleapis.com/v1beta/models")


def provider() -> str:
    """Who answers, best available first.

    Claude if a key is set -- it is the strongest at the format
    discipline her 1206 bullets and citations need. Gemini's lite tier
    next, which is cheap and already keyed here. The local model last,
    which is free and always there, so the page never goes dead because
    a bill lapsed."""
    if ANTHROPIC_API_KEY:
        return "claude"
    if GEMINI_API_KEY:
        return "gemini"
    return "ollama"


# --- The voice back ----------------------------------------------------------
#  The house already turns her speech into text. This turns the answer
#  back into speech so the loop is quick enough to think out loud in.
VOICE_URL = os.getenv("ZEE_VOICE_URL", "http://voice:8091/v1/audio/speech")
VOICE_NAME = os.getenv("ZEE_VOICE_NAME", "Jason")
VOICE_TIMEOUT = _i("ZEE_VOICE_TIMEOUT", 180)
SPEAK_ANSWERS = _b("ZEE_SPEAK_ANSWERS", "1")

# --- The running document ----------------------------------------------------
#  Files always work and need no credentials. The live Google sync turns
#  on only when a service account is supplied, and the same button then
#  writes to the Doc and the Sheet instead of handing back a download.
GOOGLE_SA_JSON = os.getenv("ZEE_GOOGLE_SA_JSON", "").strip()
GOOGLE_DOC_ID = os.getenv("ZEE_GOOGLE_DOC_ID", "").strip()
GOOGLE_SHEET_ID = os.getenv("ZEE_GOOGLE_SHEET_ID", "").strip()

# --- The ChatGPT action API --------------------------------------------------
#
#  The bearer token a ChatGPT custom GPT presents. EMPTY MEANS CLOSED, not
#  open: actions.py refuses every call when this is unset, because a
#  half-configured door is worse than a shut one -- it looks shut.
ACTION_TOKEN = os.getenv("ZEE_ACTION_TOKEN", "").strip()
# The public base a custom GPT calls, used to write the OpenAPI servers
# block. Must be the outside-world URL, not the container one.
PUBLIC_URL = os.getenv("ZEE_PUBLIC_URL", "").strip().rstrip("/")

# --- The background pass -----------------------------------------------------
#
#  Where to tell her something new is waiting. Empty = the portal's own
#  badge only, which is the honest default: a notification channel that
#  is half-configured is worse than none, because it looks like it works.
#
#  In practice this points at the Telegram bridge, which already knows
#  how to reach her phone (see telegram/bot.py's career mode). Anything
#  that accepts a JSON POST works.
NOTIFY_URL = os.getenv("ZEE_NOTIFY_URL", "").strip()

# --- Misc --------------------------------------------------------------------
TIMEZONE = os.getenv("ZEE_TIMEZONE", "America/New_York")


def ollama_url(path: str = "") -> str:
    return f"http://{DESKTOP_IP}:{OLLAMA_PORT}{path}"


def whisper_url(path: str = "") -> str:
    return f"http://{WHISPER_HOST}:{WHISPER_PORT}{path}"


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)

# --- what a photograph is allowed to tell us --------------------------------
#
# THE SAME CODE MAKES THE OPPOSITE DECISION FOR THE TWO PEOPLE USING IT.
#
# Casey photographs certificates she was awarded years earlier, so the capture
# date is when she found the frame, not when she earned the medal. A
# confident wrong date in a career record is worse than no date, so her
# instance leaves this OFF and takes dates from the citation text.
#
# Jason photographs the thing itself -- the office on the first day, the
# badge, the machine he built. There the capture date is the most reliable
# fact in the file, written by a camera at the moment rather than by a
# person remembering afterwards. His instance sets EXIF_DATES=1.
EXIF_DATES = os.getenv("EXIF_DATES", "").strip().lower() in ("1", "true", "yes")

# GPS SEPARATELY, AND OFF BY DEFAULT EVEN WHEN DATES ARE ON. A photo from a
# first day at work carries the employer's coordinates to six decimal
# places. It is his own page and his own data, so it can be captured -- but
# a page that quietly prints workplace and home coordinates is one nobody
# thinks about until the day it gets shared.
EXIF_GPS = os.getenv("EXIF_GPS", "").strip().lower() in ("1", "true", "yes")
