# jmem Progress

## Status Summary

jmem completed a full improvement cycle (2026-08-08 → 2026-08-10): plan written
and adversarially reviewed, Phase 1 of `IMPROVEMENT-PLAN.md` implemented and
live, the memory store LLM-cleaned (67.5% was junk), the holdout replaced by
always-on precision/miss grading per John's decision, a read-only HTML brain
viewer shipped, and a weekly health-digest heartbeat installed and verified
end-to-end. The system is now in observation mode: let grading data accumulate
~2 weeks before tuning thresholds or funding Phase 2.

## What Was Done This Session

- **`IMPROVEMENT-PLAN.md`** (committed): written by a planning agent from
  verified live stats, critiqued by a separate adversarial agent (14 findings,
  incl. blocker: a naive `claude -p` judge would recurse through jmem's own
  hooks), revised to address all 14. One-pager pitch emailed to John.
- **Engine rebuild** (`jmem/core.py`, `jmem/config.py`, `jmem/judge.py`,
  `jmem/maintain.py`): read-only hooks (stale index → `reindex-requested`
  marker; Stop hooks never consolidate), `PRAGMA busy_timeout`, flock, 6s hook
  deadline, `JMEM_HOOKS_DISABLED=1` kill-switch honored first in both hook
  entrypoints; relevance gating (chunk_min_score=6.0 provisional, expanded
  trivial-prompt detection, adaptive weak-match budget); session-delta
  injection (full packet turn 1, only new items later, sidecar files in
  `logs/sessions/`); LLM judge consolidation via `claude -p` (settings
  override + kill-switch + ANTHROPIC_API_KEY stripped → bills Max
  subscription); verbatim candidate fallback deleted; template-marker
  backstop; B7 fixed (memory/canon no longer indexed as a source).
- **Store migration**: `jmem migrate-store --model sonnet` judged all 1,835
  soft items → 14 keep / 582 rewrite / 1,239 tombstone. Store now ~600 clean
  atomic facts, zero >400 chars. Pre-migration snapshot:
  `backups/daily/jmem-20260809.sqlite`. Judge receives item scope (dry-run
  caught misattribution of project facts to "jmem").
- **Ops**: `com.jmem.maintain` LaunchAgent (hourly :37) replaces
  `com.jmem.consolidate` + `com.jmem.granola-sync` (plists renamed
  `.superseded`). Maintain steps: granola sync, index, judge consolidation,
  effectiveness grading, candidate prune, hooks.jsonl rotation (totals folded
  into metadata), session-state cleanup, brain render, daily/weekly backups
  (`backups/`, keep 7 daily + 4 weekly; `jmem backup`/`restore`). Fixed
  python.org 3.14 SSL certs (Granola sync was failing verify); granola_sync
  no longer misreports failures.
- **Holdout built then disabled**: deterministic 1-in-4 by session_id hash was
  implemented, verified, then turned off per John ("memory rich always") via
  `config.toml` `[holdout] enabled = false`. Replaced by **precision/miss
  grading**: maintainer LLM-grades recent injections (relevant/partial/noise)
  and audits silent prompts for misses → `injection_grades` table; `jmem
  stats` shows precision + miss_rate. First reading: 75% precision on 12
  events (noise entries were synthetic test prompts — correct grades).
- **Brain viewer**: `jmem brain [--open]` (`jmem/brain.py`) generates
  `brain.html` — single-file, read-only, searchable, grouped by project,
  dark-mode aware; regenerated hourly by maintain. Delivered to John; he
  called it "pretty awesome."
- **Weekly digest heartbeat**: `HEARTBEAT.md` + `com.openclaw.hb-jmem-weekly`
  (Mondays 08:30 PT, runs with `JMEM_HOOKS_DISABLED=1`). Verified end-to-end:
  first digest ("healthy — 75% precision") delivered to Gmail via
  outbox → Clawdia Mailer.
- **Judge prompts hardened**: rejects general world knowledge — stores only
  facts specific to John, his projects, contacts, infrastructure, decisions.
  Random 18-item sample confirmed the store was already clean of world facts.
- **Tests**: 38 stdlib-unittest tests, `python3 -m unittest discover -s tests`
  (extraction, gating, holdout, judge parsing, grading, config, brain).
- **Docs**: README updated (maintain, judge, gating, backups); one-pager +
  improvement plan emailed to John (AgentMail).

## Active State

- **Observation mode**: hourly maintain grades effectiveness; Monday digest
  emails the verdict. Gating thresholds in `jmem/config.py` DEFAULTS are
  provisional — retune with 2 weeks of precision/miss data.
- **Disk**: brain = 104 KB text; DB 64 MB; total footprint ~240 MB (backups
  dominate; everything rotates/prunes).
- **Known gaps (deliberate)**: Codex writeback still broken (root cause
  documented in plan 1.1: rollout content nested under `payload`; Codex usage
  ~7 prompts/Aug — parked). No per-item delete/edit (Phase 2 memory browser;
  `brain.html` is read-only). Brain-vs-library dedup not done (a fact can
  exist in both CLAUDE.md and memory_items). No canon promotion, no entity
  tags, no supersede edges (all Phase 2).
- **Startup track (Carryover)**: untouched this cycle; 5 John-decision
  blockers + unsent Mom Test emails — see ARCHIVE.md. New pitch asset: the
  system now measures its own precision.

## What's Next

1. **Wait ~2 weeks** while grading data accumulates; read Monday digests
   (next: 2026-08-17). Then retune gating thresholds from real precision/miss
   data and decide Phase 2.
2. **Phase 2 priority order (revised)**: canon lifecycle + supersede/
   contradiction edges → minimal memory browser or `jmem forget <id>` (the
   missing user control) → entity tags IF miss audits show entity-shaped
   misses → Codex fix only if Codex usage returns → refactor/MCP/install.
3. **John decision pending**: is the Carryover validation season still alive?
   (Stripe link + outreach vs personal-tool-only.)

## Key Decisions Made

- **Minimal-slice execution**: prove value before funding dashboard/refactor.
- **Judge on Max subscription** (`claude -p`, API key stripped), all data
  including Granola approved to flow to it; `judge.exclude_granola` config
  flag exists as opt-out.
- **Holdout rejected as a method**: John's revealed preference (can't afford
  25% memory-less sessions) is itself the n=1 value signal; measurement must
  never withhold. Precision + miss rate are the operational "is it working"
  standard; counterfactual stays formally unknown and that's accepted.
- **Store only what's unique to John**: world knowledge lives in model
  weights; docs/meetings stay indexed-in-place as pointers (library), only
  distilled personal facts enter memory_items (brain).
- **No knowledge graph**: only two connection types are planned — entity tags
  and supersede edges — and only when miss data justifies them.
- **Tombstones, not deletes**; snapshot-first before any migration.
