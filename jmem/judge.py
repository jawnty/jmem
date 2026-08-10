"""LLM consolidation judge (IMPROVEMENT-PLAN 1.2).

Turns raw candidate text into atomic, durable memory facts using the Claude
CLI, and re-judges existing memory_items for the one-time store cleanup.

Isolation contract (plan 1.2a — do not weaken):
- MUST NOT run in the hook hot path. Callers are `jmem maintain` and the
  explicit `jmem consolidate` / `jmem migrate-store` CLI only.
- The subprocess runs with jmem's hooks disabled twice over: a --settings
  override that empties hooks, AND JMEM_HOOKS_DISABLED=1 which both hook
  entrypoints honor as their first check. Without this, every judge run
  would fire jmem's own Stop hook and feed the judged text back into the
  next consolidation (self-ingestion loop).
- ANTHROPIC_API_KEY is stripped from the environment so the call bills the
  Claude subscription, never pay-per-token API.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile


VALID_KINDS = {"preference", "decision", "project_fact", "correction", "todo", "general"}

# Text that looks like prompt-template / instruction material aimed at a
# model, not a durable fact about John or a project (plan 1.2.4 backstop).
TEMPLATE_MARKERS = re.compile(
    r"(\{[a-z_]+\}|\byou MUST\b|\bABSOLUTE RULE\b|\bDO NOT respond\b|"
    r"\bYour task\b|\bYou are an?\b|<[a-z-]+>|^#{1,3}\s)",
    re.IGNORECASE,
)

EXTRACT_INSTRUCTIONS = """\
You are a memory extraction judge for a personal coding-agent memory system.
You receive numbered blocks of raw session text (user prompts, assistant
replies, transcripts). Extract ONLY durable, atomic facts worth remembering
across future sessions.

A durable fact is third-person, self-contained, at most 200 characters, and
still true and useful weeks from now. Kinds: preference (how John likes
things done), decision (a choice that was made), project_fact (stable fact
about a project/system), correction (something previously believed that was
wrong), todo (an open commitment).

REJECT (emit nothing for): assistant narration ("I'll check...", "Let me..."),
tool output, prompt templates or instructions aimed at a model, one-task
status ("the tests pass now"), questions, greetings, anything you cannot
rewrite as a standalone third-person fact.

Output STRICT JSON only, no prose, no code fences: a JSON array where each
element is {"block": <int>, "text": "<fact>", "kind": "<kind>",
"confidence": <0.0-1.0>}. Emit [] if nothing qualifies.
"""

MIGRATE_INSTRUCTIONS = """\
You are auditing an existing memory store for a personal coding-agent memory
system. Each numbered item below was auto-extracted by a regex and may be
junk: raw user prompts stored verbatim, prompt-template instructions,
assistant narration, one-task status lines, or transcript fragments.

For each item, judge whether it is a durable, atomic fact worth injecting
into future coding sessions. Verdicts:
- "keep": already a clean durable fact (third-person, self-contained, <=300 chars).
- "rewrite": contains a real durable fact but needs rewriting; provide "text"
  (third-person, self-contained, <=200 chars) and "kind".
- "tombstone": not a durable fact (prompt echo, template, narration, stale
  one-task detail, fragment). When in doubt, tombstone.

Kinds: preference, decision, project_fact, correction, todo, general.

Output STRICT JSON only, no prose, no code fences: a JSON array where each
element is {"id": <int>, "verdict": "keep"|"rewrite"|"tombstone",
"text": "<only for rewrite>", "kind": "<only for rewrite>",
"confidence": <0.0-1.0, only for keep/rewrite>}.
Every input id must appear exactly once.
"""


def judge_available(config: dict) -> bool:
    if os.environ.get("JMEM_DISABLE_JUDGE"):
        return False
    if not config.get("judge", {}).get("enabled", True):
        return False
    return shutil.which("claude") is not None


def _isolated_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env["JMEM_HOOKS_DISABLED"] = "1"
    return env


def _settings_override_path() -> str:
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="jmem-judge-", delete=False
    )
    json.dump({"hooks": {}, "disableAllHooks": True}, fh)
    fh.close()
    return fh.name


def _parse_json_array(raw: str) -> list[dict]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            return []
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]


def run_judge(prompt: str, config: dict) -> list[dict] | None:
    """Run one judge call. Returns parsed items, or None on any failure so
    callers can fall back to the regex path."""
    model = str(config.get("judge", {}).get("model", "haiku"))
    timeout = int(config.get("judge", {}).get("timeout_seconds", 240))
    settings_path = _settings_override_path()
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model, "--settings", settings_path],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_isolated_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        try:
            os.unlink(settings_path)
        except OSError:
            pass
    if result.returncode != 0:
        return None
    parsed = _parse_json_array(result.stdout)
    return parsed if parsed is not None else None


def looks_like_template(text: str) -> bool:
    return bool(TEMPLATE_MARKERS.search(text))


def clean_fact(item: dict, max_chars: int = 300) -> dict | None:
    """Validate one judge-emitted fact; None if it fails the backstop caps."""
    text = str(item.get("text") or "").strip()
    kind = str(item.get("kind") or "general").strip()
    try:
        confidence = float(item.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    if not text or len(text) > max_chars:
        return None
    if looks_like_template(text):
        return None
    if kind not in VALID_KINDS:
        kind = "general"
    confidence = max(0.0, min(confidence, 0.95))
    return {"text": text, "kind": kind, "confidence": confidence}


def extract_facts_from_blocks(blocks: list[str], config: dict) -> list[list[dict]] | None:
    """Judge a batch of candidate text blocks. Returns one fact-list per
    block (aligned by index), or None if the judge failed entirely."""
    if not blocks:
        return []
    numbered = "\n\n".join(
        f"--- BLOCK {i} ---\n{block[:2000]}" for i, block in enumerate(blocks)
    )
    items = run_judge(f"{EXTRACT_INSTRUCTIONS}\n{numbered}", config)
    if items is None:
        return None
    out: list[list[dict]] = [[] for _ in blocks]
    for item in items:
        try:
            block_idx = int(item.get("block", -1))
        except (TypeError, ValueError):
            continue
        if not 0 <= block_idx < len(blocks):
            continue
        fact = clean_fact(item)
        if fact:
            out[block_idx].append(fact)
    return out


def judge_existing_items(items: list[dict], config: dict) -> dict[int, dict] | None:
    """Re-judge existing memory_items rows ({id, text, kind}). Returns
    verdicts keyed by item id, or None if the judge failed."""
    if not items:
        return {}
    numbered = "\n".join(
        f"[{item['id']}] (kind={item['kind']}) {item['text'][:600]}" for item in items
    )
    parsed = run_judge(f"{MIGRATE_INSTRUCTIONS}\n{numbered}", config)
    if parsed is None:
        return None
    known_ids = {int(item["id"]) for item in items}
    verdicts: dict[int, dict] = {}
    for entry in parsed:
        try:
            item_id = int(entry.get("id", -1))
        except (TypeError, ValueError):
            continue
        if item_id not in known_ids:
            continue
        verdict = str(entry.get("verdict") or "").strip().lower()
        if verdict not in {"keep", "rewrite", "tombstone"}:
            continue
        if verdict == "rewrite":
            fact = clean_fact(entry, max_chars=200)
            if not fact:
                verdict = "tombstone"
                verdicts[item_id] = {"verdict": verdict}
                continue
            verdicts[item_id] = {"verdict": verdict, **fact}
        elif verdict == "keep":
            try:
                confidence = float(entry.get("confidence", 0.8))
            except (TypeError, ValueError):
                confidence = 0.8
            verdicts[item_id] = {
                "verdict": verdict,
                "confidence": max(0.0, min(confidence, 0.95)),
            }
        else:
            verdicts[item_id] = {"verdict": verdict}
    return verdicts
