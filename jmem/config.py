"""jmem configuration.

Values live in <JMEM_HOME>/config.toml. Stdlib tomllib is read-only, so the
file is written from CONFIG_TEMPLATE (never serialized) and parsed on load.
Missing file or missing keys fall back to DEFAULTS.
"""
from __future__ import annotations

import os
from pathlib import Path
import tomllib


DEFAULTS: dict = {
    "retrieval": {
        # Provisional thresholds (IMPROVEMENT-PLAN 1.3): eyeballed against
        # --explain output on recent real prompts; re-tune once per-item
        # hit rates exist (Phase 2).
        "chunk_min_score": 6.0,
        "strong_chunk_score": 12.0,
        "max_chars": 6000,
        "weak_max_chars": 2500,
        "weak_max_items": 3,
        "weak_snippet_chars": 300,
        "min_prompt_tokens": 3,
    },
    "holdout": {
        # Deterministic A/B holdout: sessions where
        # sha256(session_id) % modulus == 0 get no injection (logged).
        "enabled": True,
        "modulus": 4,
    },
    "judge": {
        # LLM consolidation judge. Runs ONLY from `jmem maintain` /
        # explicit CLI, never in the hook hot path. The subprocess runs
        # with hooks disabled (settings override + JMEM_HOOKS_DISABLED=1)
        # and with ANTHROPIC_API_KEY stripped so it bills the Claude
        # subscription, not pay-per-token API.
        "enabled": True,
        "model": "haiku",
        "exclude_granola": False,
        "timeout_seconds": 240,
        "batch_size": 8,
    },
    "maintain": {
        "index_max_age_seconds": 3600,
        "candidate_prune_days": 30,
        "log_rotate_bytes": 5_000_000,
        "log_keep_files": 5,
        "session_state_max_age_days": 7,
        "backup_keep_daily": 7,
        "backup_keep_weekly": 4,
    },
}

CONFIG_TEMPLATE = """\
# jmem configuration. Values shown are the defaults; uncomment to override.
# This file is read with tomllib; jmem never rewrites it.

[retrieval]
# chunk_min_score = 6.0        # source chunks below this are gated (recency alone must not clear it)
# strong_chunk_score = 12.0    # below this, the packet shrinks to weak-match format
# max_chars = 6000             # packet cap on strong matches
# weak_max_chars = 2500        # packet cap on weak matches
# weak_max_items = 3
# weak_snippet_chars = 300
# min_prompt_tokens = 3        # prompts with fewer content tokens are gated

[holdout]
# enabled = true               # deterministic per-session A/B holdout
# modulus = 4                  # 1-in-N sessions get no injection

[judge]
# enabled = true               # LLM consolidation judge (claude -p, subscription-billed)
# model = "haiku"
# exclude_granola = false      # true = granola-derived content never reaches the LLM judge
# timeout_seconds = 240
# batch_size = 8

[maintain]
# index_max_age_seconds = 3600
# candidate_prune_days = 30
# log_rotate_bytes = 5000000
# log_keep_files = 5
# session_state_max_age_days = 7
# backup_keep_daily = 7
# backup_keep_weekly = 4
"""


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def config_path(root: Path) -> Path:
    return root / "config.toml"


def load_config(root: Path | None = None) -> dict:
    if root is None:
        from jmem.core import ROOT as core_root

        root = core_root
    path = config_path(root)
    if not path.exists():
        return dict(DEFAULTS)
    try:
        with path.open("rb") as fh:
            loaded = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return dict(DEFAULTS)
    return _merge(DEFAULTS, loaded)


def write_default_config(root: Path, force: bool = False) -> Path | None:
    path = config_path(root)
    if path.exists() and not force:
        return None
    path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return path


_cached: dict | None = None


def get_config() -> dict:
    global _cached
    if _cached is None or os.environ.get("JMEM_CONFIG_NO_CACHE"):
        _cached = load_config()
    return _cached
