"""Getting what she already told ChatGPT into her own record.

Jason, 2026-09-06: "she's already set up some information on cha[t]-[G]PT
[- I'd] like to be able to import her session history of that specific log
And Port that session parse the data and then export into a spreadsheet or
document and then sync up changes from now and in the future."

THE ONE THING TO BE STRAIGHT ABOUT FIRST
There is no API that reads a person's ChatGPT conversations. The OpenAI
API and ChatGPT are different products: an API key gives access to models,
not to her chat history. Nothing can be wired up to "log in and pull her
sessions", and any design that assumes otherwise will not work.

What DOES exist is an export she runs herself:

    ChatGPT -> Settings -> Data controls -> Export data

which emails her a link to a zip. Inside is `conversations.json`: every
conversation, as a message tree. That file is the input here.

WHY A TREE AND NOT A LIST
Each conversation is a `mapping` of node id -> node, each with a parent.
Edited and regenerated messages create BRANCHES, so a naive walk over
mapping.values() returns every abandoned draft alongside the real thread,
in dictionary order rather than reading order -- which produces a
transcript that is both wrong and jumbled. `current_node` is the leaf of
the branch actually left on screen, so walking parents up from there and
reversing gives the conversation as she last saw it. That is the one she
means.

WHAT COMES BACK OUT
Two things, deliberately separate:
  - The transcript, filed as a recording, so it is searchable next to
    everything else she has said. Nothing is interpreted.
  - Optionally, drafted portfolio entries -- but only from what the
    transcript actually contains, and always as drafts for her to accept.
    A conversation is not a record of what happened; it is a record of
    what was discussed.
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path

from . import db, llm

MAX_BYTES = 200 * 1024 * 1024


def _load(raw: bytes) -> list:
    """conversations.json, from either the raw file or the whole export zip."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist()
                     if n.endswith("conversations.json")]
            if not names:
                raise ValueError(
                    "That zip has no conversations.json in it. It should be "
                    "the export ChatGPT emails you from Settings -> Data "
                    "controls -> Export data.")
            raw = z.read(names[0])
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"That is not readable JSON: {e}")
    if isinstance(data, dict):
        data = data.get("conversations") or [data]
    if not isinstance(data, list):
        raise ValueError("That file is not in the shape an export has.")
    return data


def _text_of(node: dict) -> tuple[str, str]:
    """(role, text) for one node, or ("", "") for one that carries none."""
    msg = (node or {}).get("message") or {}
    author = ((msg.get("author") or {}).get("role") or "").strip()
    content = msg.get("content") or {}
    ctype = content.get("content_type")
    parts = content.get("parts") or []
    if ctype not in (None, "text", "multimodal_text"):
        return "", ""
    out = []
    for p in parts:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict) and p.get("text"):
            out.append(str(p["text"]))
    text = "\n".join(t for t in out if t).strip()
    # Hidden system/tool scaffolding she never saw.
    if author in ("system", "tool") or not text:
        return "", ""
    if (msg.get("metadata") or {}).get("is_visually_hidden_from_conversation"):
        return "", ""
    return author, text


def _thread(conv: dict) -> list[dict]:
    """The branch actually left on screen. See this module's header."""
    mapping = conv.get("mapping") or {}
    node_id = conv.get("current_node")
    chain, seen = [], set()
    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = mapping[node_id]
        role, text = _text_of(node)
        if role:
            chain.append({"role": role, "text": text,
                          "ts": node.get("message", {}).get("create_time")})
        node_id = node.get("parent")
    chain.reverse()
    if chain:
        return chain
    # No current_node (older exports). Fall back to create_time order and
    # say so at the call site rather than pretending this is the same thing.
    rows = []
    for node in mapping.values():
        role, text = _text_of(node)
        if role:
            rows.append({"role": role, "text": text,
                         "ts": (node.get("message") or {}).get("create_time")})
    rows.sort(key=lambda r: r["ts"] or 0)
    return rows


def conversations(raw: bytes) -> list[dict]:
    """Every conversation in the export, as a pickable list."""
    out = []
    for i, conv in enumerate(_load(raw)):
        if not isinstance(conv, dict):
            continue
        thread = _thread(conv)
        if not thread:
            continue
        words = sum(len(m["text"].split()) for m in thread)
        out.append({
            "index": i,
            "id": conv.get("conversation_id") or conv.get("id") or str(i),
            "title": (conv.get("title") or "(untitled)").strip()[:140],
            "created": conv.get("create_time"),
            "updated": conv.get("update_time"),
            "messages": len(thread),
            "words": words,
            "preview": thread[0]["text"][:180],
        })
    out.sort(key=lambda r: r["updated"] or r["created"] or 0, reverse=True)
    return out


def transcript(raw: bytes, conversation_id: str) -> dict:
    for conv in _load(raw):
        if not isinstance(conv, dict):
            continue
        cid = str(conv.get("conversation_id") or conv.get("id") or "")
        if cid != str(conversation_id):
            continue
        thread = _thread(conv)
        lines = []
        for m in thread:
            who = "Casey" if m["role"] == "user" else "ChatGPT"
            lines.append(f"**{who}:** {m['text']}")
        return {
            "id": cid,
            "title": (conv.get("title") or "(untitled)").strip(),
            "created": conv.get("create_time"),
            "messages": len(thread),
            "text": "\n\n".join(lines),
            "hers_only": "\n\n".join(m["text"] for m in thread
                                     if m["role"] == "user"),
        }
    raise KeyError(conversation_id)


def file_transcript(raw: bytes, conversation_id: str, username: str = "") -> dict:
    """Keep the conversation as a recording, alongside everything else."""
    t = transcript(raw, conversation_id)
    rec_id = db.rec_add(
        username or "casey", f"chatgpt-{t['id'][:12]}.md", "", len(t["text"]),
        source="chatgpt", title=f"ChatGPT: {t['title']}"[:120],
        transcript=t["text"], status="done")
    db.log_event("info", "chatgpt",
                 f"imported {t['messages']} messages from {t['title']!r}")
    return {"recording_id": rec_id, **t}


EXTRACT_SYSTEM = """You are reading a transcript of a conversation between a
nurse officer and an AI assistant, looking for things SHE DID that belong in her
career record.

WHAT COUNTS
Only accomplishments, projects, duties, credentials or results she describes
having done or being responsible for.

WHAT DOES NOT
- Anything the assistant suggested, drafted or speculated about. A conversation
  is a record of what was DISCUSSED, not of what happened.
- Plans and intentions. "I'm going to" is not an accomplishment.
- Anything you infer. If she did not say it, it is not there.

Never invent a number, a date, a unit or a scope. Where she gave no number,
leave the field empty — an empty field is a prompt for her to fill in; a made-up
one goes into a real package under her name.

Return JSON only:
{"entries": [{"title": "", "happened_on": "", "situation": "", "task": "",
              "action": "", "result": "", "evidence": "", "skills": "",
              "confidence": "high|medium|low",
              "quote": "the words she used, so she can check it"}]}
At most 6. Empty list if the conversation contains no accomplishments of hers.
"""


def extract_entries(text: str, system_prompt: str = "") -> list[dict]:
    """Draft portfolio entries from a transcript. Drafts, never saved facts."""
    if not text.strip():
        return []
    system = ((system_prompt + "\n\n" + EXTRACT_SYSTEM)
              if system_prompt else EXTRACT_SYSTEM)
    # Her own words only. The assistant's half is where invented detail
    # lives -- it will have drafted bullets, suggested numbers and offered
    # phrasings, and none of that is evidence of anything she did.
    try:
        answer, model = llm.ask(system, text[:60000], temperature=0.1)
        data = llm.extract_json(answer)
    except Exception as e:  # noqa: BLE001
        db.log_event("warn", "chatgpt", f"extraction failed: {e}")
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for e in (data.get("entries") or [])[:6]:
        if not isinstance(e, dict) or not str(e.get("title") or "").strip():
            continue
        out.append({k: str(e.get(k) or "").strip() for k in
                    ("title", "happened_on", "situation", "task", "action",
                     "result", "evidence", "skills", "confidence", "quote")}
                   | {"model": model})
    return out
