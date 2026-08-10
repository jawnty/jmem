# jmem Progress

## Status Summary

Phase 1 of IMPROVEMENT-PLAN.md is implemented, tested, and live (2026-08-09).
jmem's memory store was cleaned by an LLM migration (1,835 items judged: 14
kept, 582 rewritten into atomic facts, 1,239 tombstoned — 67.5% was junk),
hooks are now read-only and fast, injection is gated with session-delta
suppression, a deterministic 1-in-4 holdout is running, and a unified hourly
`jmem maintain` LaunchAgent owns all background mutation. The Codex writeback
fix (plan 1.1) and Phase 2 (dashboard, canon lifecycle, reference detection)
are NOT yet done.

## What Was Done This Session

- **Improvement plan:** `IMPROVEMENT-PLAN.md` written by a planning agent from
  verified live stats, adversarially reviewed (14 findings incl. one blocker:
  naive `claude -p` judge would recurse through jmem's own hooks), revised,
  committed. One-pager pitch emailed to John.
- **Scope decision (John):** execute the minimal slice — extraction cleanup,
  relevance gating, holdout — and let the holdout result decide whether the
  dashboard/refactor/Phase 3 get funded. LLM judge = Claude CLI on the Max
  subscription (ANTHROPIC_API_KEY stripped so no API billing), all data
  including Granola approved to flow to it. Holdout = 1 in 4 sessions.
  Commit as we go.
- **Engine (commit 735426f):** read-only hooks (stale index only touches a
  `reindex-requested` marker; Stop hooks no longer consolidate), busy_timeout
  + flock + 6s hook deadline, `JMEM_HOOKS_DISABLED` kill-switch, relevance
  gating (chunk_min_score, trivial-prompt expansion, adaptive weak-match
  budget), session-delta injection (full packet turn 1, only new items after),
  deterministic holdout, LLM judge consolidation (hook-isolated), verbatim
  candidate fallback deleted, template-marker backstop, instrumentation
  (injected item ids+scores, agent, gated reason, duration_ms; token
  accounting in `jmem stats`), B7 fix (memory/canon no longer indexed as a
  source), new commands: `maintain`, `backup`, `restore`, `migrate-store`,
  `config-init`; config in `config.toml` (tomllib, templated).
- **Tests (f631f6f):** 30 stdlib-unittest tests (extraction, gating, holdout,
  judge parsing, isolation, config) — `python3 -m unittest discover -s tests`.
- **Store migration:** `jmem migrate-store --model sonnet` over all 1,835 soft
  items (snapshot-first). Judge received each item's scope after a dry-run
  revealed misattribution of project facts to "jmem". Result: 596 clean soft
  items, zero >400 chars (was 319 raw-prompt echoes at conf 0.92).
- **Ops:** `com.jmem.maintain` LaunchAgent installed (hourly :37), old
  `com.jmem.consolidate` + `com.jmem.granola-sync` retired (plists renamed
  `.superseded`). Full maintain cycle verified live (57s). Fixed python.org
  3.14 SSL certs (ran Install Certificates.command) which had broken Granola
  sync; granola_sync status no longer misreports failures as "synced";
  tomllib import made defensive for pre-3.11 interpreters.
- **Backups:** `backups/daily/` (DB + canon, keep 7) and `backups/weekly/`
  (candidates tarball, keep 4), run by maintain. Pre-migration snapshot
  exists at `backups/daily/jmem-20260809.sqlite` (the un-migrated store).

## Verified Behavior (evidence, not narration)

- Hook turn 1: 5,461 chars injected, ids+scores logged, 23ms.
- Hook turn 2 same session: only new items injected (delta) — 2,321 chars.
- Holdout session: injected_chars=0, `gated=holdout`, logged.
- Trivial prompts ("ok", "do it", "/cmd"): gated, 0 chars.
- Stop hook: candidate written, no consolidation, ~0ms.
- Judge smoke test: prompt echoes → zero facts; real decision → clean fact.
- Post-migration packets visibly contain distilled facts (confirmed in live
  session ambient context).

## What's Next

1. **Holdout DISABLED (2026-08-09, John's call):** Claude Code carries real
   work; memory must be rich always. `config.toml` sets holdout.enabled=false.
   The primary effectiveness signal is now the maintainer's grading pass:
   every hour it LLM-grades recent injections (relevant/partial/noise) and
   audits silent prompts for misses; `jmem stats` shows precision and
   miss_rate (first reading: 75% precision on 12 events, 0 misses). Review
   precision/miss trends in ~2 weeks to decide on Phase 2 and tune the
   provisional gating thresholds.
2. **Codex writeback fix (plan 1.1)** — parked; root cause documented in the
   plan (rollout `payload` nesting). Codex usage is ~12% and falling.
3. **Threshold re-tune** — gating thresholds (chunk_min_score=6.0 etc.) are
   provisional per plan 1.3; re-tune once per-item hit rates exist (Phase 2).
4. Startup-validation track (Carryover landing page, Stripe link, Mom Test
   outreach) unchanged and still gated on John — see ARCHIVE.md.

## Key Decisions Made

- Minimal-slice execution: prove value via holdout before funding Phase 2/3.
- Judge on subscription (`claude -p`), never API-billed; all-data privacy
  posture with `judge.exclude_granola` config flag as the opt-out.
- Tombstones preserved (1,239 rows, status=tombstoned) for audit;
  re-runnable from the pre-migration snapshot if judgment proves aggressive.
