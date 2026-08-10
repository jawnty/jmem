# Roadmap

## Done (v0 + Phase 1, 2026-08)

- Deterministic local indexing with SQLite FTS; ambient `UserPromptSubmit`
  hooks for Codex and Claude Code; Granola API caching.
- Read-only hooks: all mutation lives in the hourly `jmem maintain`
  LaunchAgent (index, granola, consolidation, pruning, log rotation,
  backups, brain render). busy_timeout + flock + hook deadline.
- LLM judge consolidation (hook-isolated `claude -p`): atomic third-person
  facts only; rejects narration, templates, one-task noise, and general
  world knowledge. Regex fallback with no verbatim path.
- One-time store migration: 1,835 items judged, 67.5% tombstoned.
- Relevance gating, session-delta injection, adaptive packet budget.
- Effectiveness instrumentation: injected item ids+scores, token accounting,
  hourly precision/miss grading (`injection_grades`), optional deterministic
  holdout (config).
- `jmem backup`/`restore` (daily/weekly rotation), `jmem brain` HTML viewer,
  `config.toml`, weekly health-digest heartbeat, 38-test unittest suite.

## Next (Phase 2 — gated on ~2 weeks of precision/miss data)

- Canon promotion lifecycle: auto-promote repeatedly-reinforced facts,
  confidence decay, supersede/contradiction edges.
- Minimal memory browser or `jmem forget <id>`: per-item edit/delete
  (today's brain viewer is read-only).
- Retune gating thresholds from measured hit rates.
- Entity tags (people/companies/projects) IF miss audits show entity-shaped
  misses.
- Brain-vs-library dedup: skip storing facts already recorded in indexed docs.
- Codex writeback fix (root cause in IMPROVEMENT-PLAN.md 1.1) if Codex usage
  returns.

## Later (Phase 3)

- Refactor core.py into modules with the full test suite.
- MCP tools for explicit lookup and writeback.
- Real installable (uv/pipx), one-command `jmem init`, upgrade path.
- Optional embeddings/hybrid retrieval, only if FTS misses are observed.
