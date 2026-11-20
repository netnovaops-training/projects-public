"""Talking to the GPU desktop: Wake-on-LAN, health checks, and remote hibernate."""
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, asdict
from typing import Optional

import httpx

from . import config, db

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-.]?){5}[0-9A-Fa-f]{2}$")


def normalize_mac(mac: str) -> str:
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(clean) != 12:
        raise ValueError(f"MAC address must be 12 hex digits, got {mac!r}")
    return ":".join(clean[i:i + 2] for i in range(0, 12, 2)).upper()


def build_magic_packet(mac: str) -> bytes:
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac!r}")
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def send_wol(mac: Optional[str] = None, broadcast: Optional[str] = None) -> bool:
    """Broadcast a magic packet on every configured port. Returns True if any send succeeded."""
    mac = mac or config.DESKTOP_MAC
    broadcast = broadcast or config.DESKTOP_BROADCAST
    if not mac:
        db.log_event("error", "wol", "No desktop MAC configured; cannot wake.")
        return False
    try:
        packet = build_magic_packet(mac)
    except ValueError as e:
        db.log_event("error", "wol", str(e))
        return False

    ok = False
    for target in {broadcast, "255.255.255.255"}:
        for port in config.WOL_PORTS:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.settimeout(3)
                s.sendto(packet, (target, port))
                s.close()
                ok = True
            except Exception as e:  # noqa: BLE001
                db.log_event("warn", "wol", f"send to {target}:{port} failed: {e}")

    # etherwake is a raw layer-2 sender; more reliable than UDP broadcast on some
    # switches. Best-effort only -- it needs root, which we may not have.
    if shutil.which("etherwake"):
        try:
            subprocess.run(["etherwake", normalize_mac(mac)], timeout=5,
                           capture_output=True, check=False)
        except Exception:
            pass

    if ok:
        db.log_event("info", "wol", f"Magic packet sent to {mac}")
    return ok


def _probe(url: str, timeout: float = 3.0) -> bool:
    try:
        r = httpx.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@dataclass
class DesktopStatus:
    reachable: bool = False
    ollama: bool = False
    whisper: bool = False
    ssh: bool = False

    @property
    def ready(self) -> bool:
        return self.ollama and self.whisper

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ready"] = self.ready
        return d


def status() -> DesktopStatus:
    ip = config.DESKTOP_IP
    if not ip:
        return DesktopStatus()
    st = DesktopStatus()
    st.ollama = _probe(config.ollama_url("/api/tags"))
    st.whisper = _probe(config.whisper_url("/health"))
    st.ssh = tcp_open(ip, 22, timeout=1.5)
    st.reachable = st.ollama or st.whisper or st.ssh or tcp_open(ip, 3389, 1.0)
    return st


def wake_and_wait(timeout: Optional[int] = None, on_progress=None) -> DesktopStatus:
    """Send WoL then poll until Ollama + Whisper answer, or timeout."""
    timeout = timeout or config.BOOT_WAIT_SECONDS
    st = status()
    if st.ready:
        return st

    send_wol()
    deadline = time.time() + timeout
    last_resend = time.time()
    while time.time() < deadline:
        st = status()
        if st.ready:
            db.log_event("info", "wol", "Desktop is up and services are answering.")
            return st
        if on_progress:
            remaining = int(deadline - time.time())
            on_progress(f"Waking desktop... services not up yet ({remaining}s left)")
        # Re-send every 30s in case the first packet was dropped.
        if time.time() - last_resend > 30:
            send_wol()
            last_resend = time.time()
        time.sleep(5)

    db.log_event("error", "wol",
                 f"Desktop did not become ready within {timeout}s "
                 f"(ollama={st.ollama} whisper={st.whisper} ssh={st.ssh})")
    return st


def hibernate() -> tuple[bool, str]:
    """Hibernate the desktop over SSH. Hibernate (S4) is chosen over sleep because
    Windows explicitly arms Wake-on-LAN for an explicit hibernate transition."""
    if not (config.DESKTOP_SSH_USER and config.DESKTOP_IP):
        return False, "SSH user or desktop IP not configured"
    cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=8", "-i", config.DESKTOP_SSH_KEY,
        f"{config.DESKTOP_SSH_USER}@{config.DESKTOP_IP}",
        "shutdown /h",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=25, text=True)
    except subprocess.TimeoutExpired:
        # The box often drops the connection mid-command as it powers down.
        db.log_event("info", "power", "Hibernate command timed out (usually means it worked).")
        return True, "Hibernate sent (connection dropped, which is normal)"
    except Exception as e:  # noqa: BLE001
        return False, f"SSH failed: {e}"

    if p.returncode == 0:
        db.log_event("info", "power", "Desktop hibernate requested.")
        return True, "Hibernate requested"
    msg = (p.stderr or p.stdout or "unknown error").strip()[:400]
    db.log_event("error", "power", f"Hibernate failed: {msg}")
    return False, msg
