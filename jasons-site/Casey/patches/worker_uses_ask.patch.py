#!/usr/bin/env python3
"""The drafting path never used Gemini. Run from Casey/.

Jason has said twice that he wants Gemini used -- "Answers come from Claude
or Gemini when a key is set", and "I do want to use Gemini". The chain in
llm.ask() implements exactly that: Claude, then Gemini, then the house
model, and since this morning a Tier 1 Gemini key when the free one runs
dry.

worker.py never called it. It called `llm.chat()`, which talks straight to
Ollama on the desktop and skips the chain entirely, then recorded
`model_used=config.OLLAMA_MODEL` unconditionally -- so the job record
agreed with itself and there was nothing to notice. Every accomplishment
draft this portal has ever produced came from the local 8B, including the
ones written while a working Gemini key sat in the environment.

This is the highest-value output in the whole application: the text that
goes into her official record. It was running on the weakest model
available, silently, because one call site reached past the router.

BOTH CALLS MOVE, not just the draft. The follow-up questions -- "what did
you leave out?" -- also went to the local model, and asking a small model
to return strict JSON is exactly where it is weakest; there is a
four-branch fallback parser below it that exists to cope with that.

THE MODEL RECORDED IS NOW THE ONE THAT ANSWERED. `ask()` returns the name,
so a draft written on Gemini says Gemini and one written on the local model
after a Gemini outage says that instead. The old code hardcoded the local
model's name whatever happened, which is how this stayed invisible.

The follow-up call deliberately keeps its own failure handling: if the
better model is down, questions are worth losing, a draft is not.
"""
import io
import sys

P = "app/worker.py"
s = io.open(P, encoding="utf-8").read()
if "llm.ask(" in s:
    sys.exit("already patched")

OLD = """    user_msg = f"{task}\\n\\n===== RAW INPUT =====\\n{combined}\\n===== END RAW INPUT =====\\n"
    draft = llm.chat(system, user_msg)"""
NEW = """    user_msg = f"{task}\\n\\n===== RAW INPUT =====\\n{combined}\\n===== END RAW INPUT =====\\n"
    # ask(), NOT chat(). chat() goes straight to Ollama and skips the whole
    # Claude -> Gemini -> house-model chain, which is why every draft this
    # portal ever produced came from the local 8B even with a working Gemini
    # key in the environment (found 2026-09-07). This is the text that ends
    # up in her official record; it should have the best model available.
    draft, draft_model = llm.ask(system, user_msg)"""
assert OLD in s, "draft call not found"
s = s.replace(OLD, NEW, 1)

OLD2 = """        raw = llm.chat(system, FOLLOWUP_PROMPT.format(draft=draft), temperature=0.6)"""
NEW2 = """        # The follow-ups move too. Asking a small local model for strict
        # JSON is exactly where it is weakest -- the four-branch fallback
        # parser below exists because of it.
        raw, _ = llm.ask(system, FOLLOWUP_PROMPT.format(draft=draft),
                         temperature=0.6)"""
assert OLD2 in s, "followup call not found"
s = s.replace(OLD2, NEW2, 1)

OLD3 = """                  model_used=config.OLLAMA_MODEL, kb_version=kb_version, error="")"""
NEW3 = """                  # The model that ACTUALLY answered. This used to record
                  # OLLAMA_MODEL whatever happened, so the record agreed
                  # with itself and there was nothing to notice.
                  model_used=draft_model, kb_version=kb_version, error="")"""
assert OLD3 in s, "model_used not found"
s = s.replace(OLD3, NEW3, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("worker.py: drafting now goes through the model chain")
