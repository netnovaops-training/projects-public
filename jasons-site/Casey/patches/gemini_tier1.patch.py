#!/usr/bin/env python3
"""Fall back to the paid Gemini key when the free one runs dry. Run from Casey/.

Jason, 2026-09-07: "let's use tier 1 when free tier is out of credits."

WHAT WAS ACTUALLY WRONG, found while looking for something else. He has
three Gemini keys, and the one wired into both this portal and the recipe
app was `...wsfQ` -- FREE TIER. The Tier 1 key with billing attached
(`...nOiw`) was sitting unused. So "running out of credits" was not a
budget problem at all: everything was running on the free tier's hard rate
limit while the paid capacity went untouched.

THE ORDER, AND WHY THIS WAY ROUND. Free first, paid only when free is
exhausted. The reverse -- paid first -- would be simpler and would spend
money on every single request when a free quota was sitting there unused.
Free-first means the paid key is a spillover, which is what he asked for
and also what costs least.

ONLY ON A QUOTA ERROR, WHICH IS THE PART THAT MATTERS. It is tempting to
retry the paid key on any failure, and that would be wrong: a malformed
request, an oversized prompt or a safety refusal will fail identically on
both keys, so retrying would spend money to receive the same error twice.
Worse, it would do that on every request during an outage. So the fallback
is gated on the errors that actually mean "this key has no quota left" --
HTTP 429, and the 403s Google returns with RESOURCE_EXHAUSTED or a quota
message in them. Anything else drops straight to the house model, as before.

WHICH KEY ANSWERED IS RECORDED. `ask()` already returns the model name and
jobs store it, so the name now says which tier paid for the answer --
"gemini-2.5-flash (tier 1)". Without that, the first sign of the free key
being permanently exhausted would be a bill, not a log line.
"""
import io
import sys

P = "app/llm.py"
s = io.open(P, encoding="utf-8").read()
if "GEMINI_API_KEY_PAID" in s:
    sys.exit("already patched")

# --- 1. ask_gemini takes a key ---------------------------------------------
OLD = '''def ask_gemini(system: str, user: str, history=None,
               temperature: float = 0.4) -> str:'''
NEW = '''# Raised when a key has no quota left, and ONLY then -- see ask() for why
# that distinction is the whole point of this class existing.
class GeminiQuotaExhausted(RuntimeError):
    pass


def ask_gemini(system: str, user: str, history=None,
               temperature: float = 0.4, api_key: str = "") -> str:'''
assert OLD in s, "ask_gemini signature not found"
s = s.replace(OLD, NEW, 1)

OLD2 = '''    if not config.GEMINI_API_KEY:
        raise RuntimeError("no GEMINI_API_KEY set")'''
NEW2 = '''    # The caller passes the key so the same function serves both tiers.
    # Defaults to the free one, which is every existing call site.
    key = api_key or config.GEMINI_API_KEY
    if not key:
        raise RuntimeError("no GEMINI_API_KEY set")'''
assert OLD2 in s, "gemini key guard not found"
s = s.replace(OLD2, NEW2, 1)

OLD3 = '''    url = (f"{config.GEMINI_URL}/{config.GEMINI_MODEL}"
           f":generateContent?key={config.GEMINI_API_KEY}")
    r = httpx.post(url, json=body, timeout=config.ANTHROPIC_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")'''
NEW3 = '''    url = (f"{config.GEMINI_URL}/{config.GEMINI_MODEL}"
           f":generateContent?key={key}")
    r = httpx.post(url, json=body, timeout=config.ANTHROPIC_TIMEOUT)
    if r.status_code >= 400:
        # TELL "OUT OF QUOTA" APART FROM EVERYTHING ELSE. Only the former
        # is worth retrying on a paid key; a bad request or a safety
        # refusal fails the same way on both and retrying would spend
        # money to get the identical error twice.
        body_text = r.text[:300]
        out_of_quota = r.status_code == 429 or (
            r.status_code == 403
            and ("RESOURCE_EXHAUSTED" in r.text or "quota" in r.text.lower()))
        if out_of_quota:
            raise GeminiQuotaExhausted(f"Gemini {r.status_code}: {body_text}")
        raise RuntimeError(f"Gemini {r.status_code}: {body_text}")'''
assert OLD3 in s, "gemini request block not found"
s = s.replace(OLD3, NEW3, 1)

# --- 2. the chain tries free, then paid -------------------------------------
OLD4 = '''    if config.GEMINI_API_KEY:
        try:
            return (ask_gemini(system, user, history, temperature=temperature),
                    config.GEMINI_MODEL)
        except Exception as e:  # noqa: BLE001
            db.log_event("warn", "llm", f"Gemini failed, using the house model: {e}")'''
NEW4 = '''    if config.GEMINI_API_KEY:
        try:
            return (ask_gemini(system, user, history, temperature=temperature),
                    config.GEMINI_MODEL)
        except GeminiQuotaExhausted as e:
            # THE FREE KEY IS DRY -- the one failure worth paying to retry.
            # Jason, 2026-09-07: "let's use tier 1 when free tier is out of
            # credits." Free first so the paid key is spillover rather than
            # the default, which is both what he asked for and what costs
            # least. Any OTHER Gemini failure skips this and drops to the
            # house model, because it would fail identically on a paid key.
            if config.GEMINI_API_KEY_PAID:
                db.log_event("info", "llm",
                             f"free Gemini quota exhausted, using tier 1: {e}")
                try:
                    return (ask_gemini(system, user, history,
                                       temperature=temperature,
                                       api_key=config.GEMINI_API_KEY_PAID),
                            f"{config.GEMINI_MODEL} (tier 1)")
                except Exception as e2:  # noqa: BLE001
                    db.log_event("warn", "llm",
                                 f"tier 1 Gemini failed too, house model: {e2}")
            else:
                db.log_event("warn", "llm",
                             "free Gemini quota exhausted and no paid key set "
                             "(GEMINI_API_KEY_PAID) -- using the house model")
        except Exception as e:  # noqa: BLE001
            db.log_event("warn", "llm", f"Gemini failed, using the house model: {e}")'''
assert OLD4 in s, "gemini chain block not found"
s = s.replace(OLD4, NEW4, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("llm.py: free -> tier 1 Gemini failover")

# --- 3. config -------------------------------------------------------------
C = "app/config.py"
c = io.open(C, encoding="utf-8").read()
if "GEMINI_API_KEY_PAID" not in c:
    import re
    m = re.search(r"^GEMINI_API_KEY\s*=.*$", c, re.M)
    assert m, "GEMINI_API_KEY not found in config"
    add = (m.group(0) + "\n"
           "# The Tier 1 (billed) key, used ONLY when the free key above\n"
           "# reports its quota exhausted -- see ask() in llm.py. Left empty\n"
           "# the chain simply drops to the local model as it always did, so\n"
           "# not setting this costs nothing and turns nothing on by accident.\n"
           'GEMINI_API_KEY_PAID = os.getenv("GEMINI_API_KEY_PAID", "") or \\\n'
           '    os.getenv("ZEE_GEMINI_API_KEY_PAID", "")')
    c = c[:m.start()] + add + c[m.end():]
    io.open(C, "w", encoding="utf-8", newline="\n").write(c)
    print("config.py: GEMINI_API_KEY_PAID added")
else:
    print("config.py: already has GEMINI_API_KEY_PAID")
