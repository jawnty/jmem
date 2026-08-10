# jmem Improvement Plan

Status: proposed
Date: 2026-08-08
Scope: make jmem materially more effective for John's daily use across Claude Code
and Codex. Startup-validation (Carryover) work is out of scope, but items that
double as product-validation assets are flagged `[validation-asset]`.

Explicit scope decision: jmem stays **single-machine** (the Mac Mini) for this
entire plan. Multi-machine sync is out of scope; the `~/.jmem` state layout
(3.1) is kept self-contained and sync-friendly so that door stays open later.

All findings below were verified directly against the live install on
2026-08-08: `jmem/core.py` (1,917 lines), `logs/hooks.jsonl` (8,227 events since
2026-05-27), `index/jmem.sqlite` (951 files / 9,406 chunks; 1,828 memory_items),
and `memory/candidates/` (3,459 candidate files). Line numbers refer to
`/Users/john/projects/jmem/jmem/core.py` at commit `6a8ecf8`.

Effort scale: S = a focused session, M = a few sessions, L = a sustained track.
No calendar estimates, per working rules.

---

## 0. Verified Baseline (the evidence this plan is built on)

What is working:

- The loop runs and is reliable. 4,213 UserPromptSubmit events, 4,014 Stop
  events, injection on 98.4% of prompts, hooks wired in both
  `~/.claude/settings.json` and `~/.codex/hooks.json`. The plumbing has not
  broken in ~10 weeks of daily use.
- The pipeline shape (index -> retrieve -> inject -> capture -> consolidate) is
  right, and observability (`doctor`, `trace`, `context --explain`) exists.

What is broken or weak, with evidence:

| # | Finding | Evidence |
|---|---------|----------|
| B1 | Codex writeback is effectively dead — but Codex is the minority agent | Of 3,459 candidate files ever written, 3,454 came from `claude_stop_hook` and only **5** from `codex_stop_hook` — all 5 rejected, all containing raw JSON fragments of web-search tool output, not conversation text. Root cause diagnosed below (section 1.1). Context for prioritization: Codex is ~12% of usage and falling — 504/4,213 UserPromptSubmit and 438/4,014 Stop events (distinguishable today by session_id format: Codex uses UUIDv7 `019...`, Claude UUIDv4), with monthly Codex prompts 118 (May) -> 325 (Jun) -> 54 (Jul) -> 7 (Aug). An explicit `agent` field is still missing from logs and candidates. |
| B2 | Raw prompts and agent-session text stored verbatim as "memories" | 319 of 1,828 memory_items exceed 400 chars. Inspected samples include jtrade **LLM prompt-template instructions** stored as kind=preference ("ABSOLUTE RULE: every source reference you emit...") and portfolio-monitor **agent session summaries** stored as kind=decision. `classify_memory` (core.py:656) keyword-matches on words like "always"/"never"/"important", which prompt templates are full of. |
| B3 | Nothing is ever promoted to canon | All 1,828 memory_items are status=soft; **zero** rows have status=canon. `consolidate_candidate_file` (core.py:1493) hardcodes `status="soft"`, and manual `jmem candidates accept` has never completed successfully — doctor's `canon_files=1` is the generated `soft.md` view itself, not an accepted canon file. Worse, auto-consolidation moves any candidate with promoted lines into `accepted/` (2,315 files), a misleading 67% "accept" rate that implies human review happened when none ever did. The soft->canon lifecycle exists in schema only. |
| B4 | No relevance gating; packet always fires at the cap | Injection on 98.4% of prompts, avg packet 5,668 chars vs. 6,000 cap. The only gates are an 11-entry `TRIVIAL_PROMPTS` set (core.py:59) and score > 0 — but the recency bonus (core.py:958) gives every chunk touched in the last 90 days a positive score, and the cwd-LIKE query (core.py:907) always contributes rows. Effectively every prompt pays ~1.4k tokens of injected context whether or not it helps. |
| B5 | Granola dominates the index | granola_api: 304 files but 7,528 of 9,406 chunks (80%). Transcripts are cached up to 80k chars (core.py:351) and chunked at 2,200 chars (~36 chunks/note), so raw meeting transcript text outnumbers all project docs and agent memory 4:1 in the FTS candidate pool. |
| B6 | Confidence only goes up; junk self-reinforces | `upsert_memory_item` (core.py:718) does `min(0.95, max(old, new) + 0.03)` on every re-observation and bumps evidence_count. Because the same raw lines are re-extracted from overlapping transcripts session after session, junk items accumulate evidence_count ~5-6 and confidence 0.87-0.92 — indistinguishable from genuinely reinforced facts. There is no decay, no contradiction check, no supersede. 66 near-duplicate text groups (same 80-char prefix) exist. |
| B7 | Memory is double-injected via soft.md | `CANON_DIR` is indexed as source `jmem_memory` (core.py:184): the generated `soft.md` view is 88 chunks in the FTS index, so the same memory items can appear in a packet twice — once as `## Memory:` entries, once as `jmem_memory` source snippets. Measured scale: `soft.md` appears in `top_paths` in ~593 hook events (a floor — `top_paths` truncates to 5); the separate 2,821 figure is events with memory_items>0, where `log_hook` appends a literal `jmem_memory` tag (core.py:1712-1715), not soft.md chunk hits. (Verified: no runaway transcript echo loop — injected packets do not re-enter candidates — but the soft.md double-index is real.) |
| B8 | Retrieval work happens in the prompt hot path | `retrieve_with_trace` calls `ensure_index()` (core.py:878), which can run a full synchronous re-index (walks all of `~/projects`) when the index is >1h stale — inside the UserPromptSubmit hook, delaying the user's turn. `maybe_auto_consolidate()` similarly runs inside the Stop hook (core.py:1754). |
| B9 | Monolith, zero tests | All logic is one 1,917-line `core.py`. There is no `tests/` directory and no test at all. PROGRESS.md's own validation history is `py_compile` plus manual runs. |
| B10 | Install is repo-clone + symlinks | Live install is `~/.local/bin/jmem -> ~/projects/jmem/bin/jmem` plus three separate installer scripts. `pyproject.toml` (v0.4.0) exists but the packaged path is not the one in use; `UNKNOWN.egg-info/` clutter sits in the repo root. |
| B11 | Same packet re-injected every prompt of a session | There is no session-level dedup: a 40-turn session pays the ~1.4k-token packet up to 40 times, mostly identical content each turn. This per-session repetition, not the 98.4% injection rate alone, is the dominant token leak. |
| B12 | Codex injection delivery is asserted, never verified | `hook_main` prints Claude Code's `hookSpecificOutput` JSON envelope for Codex too (core.py:1768-1773). `injected_chars` in the log only proves jmem wrote stdout — not that Codex parses that envelope and delivers the context. No end-to-end confirmation of Codex-side injection exists. |
| B13 | No concurrency or locking story | Concurrent sessions (a daily reality) fire hooks simultaneously against one SQLite file. `connect()` (core.py:87) sets no `busy_timeout`; `ensure_index` and `maybe_auto_consolidate` blanket-except and can silently swallow "database is locked", meaning a lost re-index or consolidation run leaves no trace. A dashboard (2.2) would add yet another writer. |
| B14 | No backup, unmanaged growth | memory_items/evidence/events exist nowhere outside `index/jmem.sqlite` — once candidates are pruned, DB loss is total memory loss. Meanwhile nothing schedules `candidates prune` (`memory/candidates/` is 27MB / 3,459 files and growing) and `hooks.jsonl` is 5.7MB, append-only, and read whole-file on every `trace`/`doctor`. |

---

## 1. Engine / Backend

### 1.1 Fix Codex writeback and verify Codex injection (P0-lite, effort S)

**What/why.** B1 + B12. Honest sizing first: Codex is ~12% of hook traffic and
collapsing (7 Codex prompts in August vs 3,700+ Claude ones), so this is not
"half the data missing" — it is a small, well-diagnosed fix that keeps the
cross-agent story true, plus an open question worth answering: whether jmem's
Codex-side experience being silently broken (no writeback, unverified
injection) contributed to Codex usage declining. It stays in Phase 1 because
the fix is S-effort with the root cause already in hand, but it ranks **below**
1.2 and 1.3, which affect ~100% of usage. Writeback diagnosis, confirmed
against a real rejected candidate
(`memory/candidates/rejected/20260722-194818-*.md`):

- Codex Stop events DO include a usable `transcript_path` pointing at the
  rollout file (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`). The hook and
  frontmatter plumbing work.
- `read_transcript_text` (core.py:1262) only understands the Claude Code
  transcript shape: top-level `text`/`content`/`message`/`prompt`/`response`
  keys, or `message.content`. Codex rollout lines are
  `{"timestamp": ..., "type": "response_item", "payload": {...}}` — all content
  is nested under `payload`, so JSON-clean lines yield nothing.
- The only lines that ever produced text were ones that failed `json.loads`
  (embedded newlines in tool output), which fall through to the raw-line branch
  (core.py:1274-1276) — hence the 5 garbage candidates made of mid-JSON
  fragments.

**Approach.**

1. Add a dedicated Codex rollout parser: detect the rollout schema (top-level
   `payload` key), then extract only conversational content — `payload` items of
   type `user_message` / `agent_message` / `message` with role user/assistant —
   and explicitly skip tool calls, tool outputs, web-search results, and
   reasoning items. Never fall back to appending unparsed raw lines; that branch
   is what produced the garbage.
2. Apply the same skip-tool-output discipline to the Claude parser: today it
   happily ingests tool-result content blocks, which is one of the two feeders
   of B2.
3. Log the raw event keys (`sorted(event.keys())`) into `hooks.jsonl` for Stop
   events so the next schema drift is diagnosable from the log instead of
   requiring archaeology. Also record an explicit `agent: codex|claude` field
   in both the log record and candidate frontmatter — the agent is currently
   only recoverable by inferring UUID version from session_id (Codex UUIDv7
   `019...` vs Claude UUIDv4), which is fragile and undocumented.
4. **Verify Codex-side injection end-to-end (B12), one-time:** run a live Codex
   session with a marker fact planted in the index, confirm the model actually
   sees it, and check the Codex hook docs for the expected output contract —
   `hook_main` currently emits the Claude-shaped `hookSpecificOutput` envelope
   for Codex (core.py:1768-1773), and nothing has ever confirmed Codex parses
   it. If Codex expects a different shape, 4,213 `injected_chars` log entries
   have been overcounting real deliveries. This check also becomes part of
   `jmem init`'s round-trip validation (3.2).
5. Regression-test with fixture rollout/transcript files for both agents
   (lands with the Phase 1 test scaffolding, see 1.9).

**Priority: P0-lite.** Small, fully diagnosed, and it closes B12's
false-telemetry risk; but sequenced after 1.2/1.3 within Phase 1 because those
affect every session, not 12% of them.

### 1.2 Fix extraction quality: stop memorizing raw prompts (P0, effort M)

**What/why.** B2 + B6. The injected packet's `## Memory:` section — the part
that is supposed to be jmem's distilled value — often contains 500-char prompt
echoes and agent chatter at confidence 0.92. This actively degrades sessions:
the agent reads a stale verbatim instruction from another project's LLM prompt
template labeled "preference, confidence 0.92".

The current extractor is two regex passes: `extract_candidate_lines`
(core.py:1302) keyword-greps transcript lines, with a fallback that stores the
first 480 chars of the whole text verbatim when nothing matches
(core.py:1316-1319); `classify_memory` (core.py:656) then keyword-assigns
kind+confidence. Keyword matching cannot distinguish "John prefers X" (durable
fact) from a prompt template that contains the word "never" (instruction text),
or from an in-flight status line ("we decided to ship this today" narrating one
task).

**Approach.**

1. **Delete the verbatim fallback.** If no candidate lines match, write no
   candidate. A missing memory is strictly better than a stored raw prompt.
2. **Make consolidation an LLM pass, not a regex pass — with mandatory
   isolation.** Per candidate file, the model receives the source excerpt and
   must emit zero or more **atomic facts**, each with: text (max ~200 chars,
   third-person, self-contained), kind, scope suggestion, confidence, and a
   `durable: yes/no` judgment. Explicit instructions: reject assistant
   narration, tool output, prompt templates, one-task-scoped statements, and
   questions. Regex classification stays only as the no-network fallback.
   Three hard constraints, in priority order:
   - **(a) Judge hook isolation.** A naive `claude -p` call inherits the global
     `~/.claude/settings.json` hooks — every consolidation run would fire
     jmem's own Stop hook, write a candidate containing the very memory text
     being judged, and feed it back into the next consolidation (self-ingestion
     loop), while UserPromptSubmit injects packets into the judge's own
     context. The judge MUST run hook-free: prefer a direct API call (no hook
     surface at all); if using the CLI, pass an explicit `--settings` override
     with hooks emptied AND set a `JMEM_HOOKS_DISABLED=1` env kill-switch that
     both hook entrypoints honor as their first check (belt and suspenders —
     the kill-switch also protects against future settings-merge surprises).
   - **(b) Never in the hook hot path.** Today consolidation already runs
     inside the Stop hook via `maybe_auto_consolidate` (core.py:1754, 1801)
     with only a 10-minute debounce; as originally sequenced, the LLM pass
     would have landed in that hot path. Hard dependency: 1.10 (all
     consolidation moves to the launchd maintainer) lands **before or with**
     this item, and the LLM pass only ever executes from the maintainer.
   - **(c) Explicit model/privacy decision.** An API-based judge means Granola
     meeting transcripts and Codex session content start flowing to Anthropic's
     API — content that today never leaves the machine. This is a deliberate
     John decision, not a default: choose between (i) Anthropic API accepted
     for this data, (ii) a local model for the judge (slower, weaker, private),
     or (iii) API judge but Granola-derived candidates opted out (regex path
     only). The plan does not presume; ~24 runs/day makes any option cheap.
3. **Atomic splitting.** One candidate line often bundles several facts; the
   LLM pass emits them separately so dedup and contradiction handling can work
   at fact granularity.
4. **Hard caps as backstop:** max item length 300 chars (down from 500 in
   `normalize_memory_text`, core.py:619); items containing markers of template
   text (ALL-CAPS rule headers, `{placeholders}`, "you MUST"-style
   second-person imperatives aimed at a model) are auto-skipped.
5. **One-time cleanup migration — snapshot first:** take a full backup
   (SQLite `.backup` of `jmem.sqlite` plus a candidates/canon tarball, per
   1.11) before touching anything, then run the new extractor's judgment over
   the existing 1,828 soft items; tombstone what fails (expect a large fraction
   of the 319 >400-char items to go). Keep tombstoned rows for audit rather
   than deleting (see 1.5). The migration must be re-runnable from the snapshot
   if its judgment proves too aggressive.

**Priority: P0.** Retrieval improvements are pointless while the store is
polluted; this is the quality bottleneck.

### 1.3 Relevance gating and token-budget control (P0, effort S-M)

**What/why.** B4. A packet that always fires at ~5.7KB is not "narrow
injection", it is a 1.4k-token tax on every prompt (~6M injected tokens over
4,213 prompts to date) and it trains John and the agent to skim past it. The
README's stated principle — broad index, narrow injection — is currently only
half true.

**Approach.**

1. **Session-level dedup / delta injection (the biggest single win, B11).**
   The largest leak is not the injection rate but per-session repetition: the
   same near-identical packet fires on every prompt of a session, so a 40-turn
   session pays ~1.4k tokens 40 times for content already in the agent's
   context. Mechanism: key on `session_id` (already in every event), persist
   the set of item/chunk ids injected this session (small sidecar table or
   per-session JSON), inject the full packet on turn 1, and on later turns
   inject only *new* items that were not previously sent — usually nothing.
   This alone should cut injected tokens by well over half at zero relevance
   cost, and is cheaper and safer than aggressive threshold tuning.
2. **Score threshold, not score > 0.** Calibrate a minimum absolute score for
   chunk matches (the recency bonus alone must not clear it). Emit nothing when
   nothing clears the bar. Working target: injection on roughly 40-70% of
   first-turn prompts, with the skipped ones observable in `jmem trace` as
   `gated`. **This target is explicitly provisional:** per-item hit-rate
   instrumentation (2.1.2) does not exist until Phase 2, so the Phase 1
   threshold is set by eyeballing `--explain` output on recent real prompts,
   then re-tuned against measured hit rates once Phase 2 lands.
3. **Adaptive budget.** Strong matches: fill up to the cap. Weak matches: emit
   only the top 1-2 items in a compact format. Never pad to the cap just
   because material exists.
4. **Expand trivial-prompt handling** beyond the 11-entry literal set: short
   deictic prompts ("do it", "fix that", "yes please", slash-command
   invocations, pure pastes) carry no retrievable intent — gate on token count
   and structure, not exact string match.
5. **Tiered packet layout:** canon items first (once canon exists, 1.4), then
   high-scoring memory items, then source snippets. Within budget, prefer 5
   short atomic facts over 2 620-char snippets — snippet length (core.py:591,
   620 chars) should shrink for lower-ranked matches.
6. **Config, not constants:** `max_chars`, threshold, per-source caps in a
   `~/.jmem/config.toml` (also needed by 3.x install work). Note: stdlib
   `tomllib` is read-only — `jmem init` writes the file from a commented
   template string, never by serializing (3.2).

**Priority: P0.** Cheap, immediately felt, and it is the precondition for
measuring effectiveness honestly (a packet that always fires cannot show lift).

### 1.4 Canon promotion lifecycle that actually runs (P1, effort M)

**What/why.** B3. The soft/canon distinction is the product's trust model, and
it is dead weight today: nothing reaches canon, so retrieval treats a raw
prompt echo seen 6 times the same as a curated fact. Meanwhile the one review
UI that could promote things is a CLI (`candidates accept`) that John has used
once in 10 weeks — the review ergonomics failed, not John.

**Approach.**

1. **Auto-promotion rule:** a soft item becomes canon when it has been
   independently re-extracted in >= N distinct sessions (not merely N evidence
   rows — see the self-reinforcement caveat in B6; count distinct
   session_ids/days from `memory_evidence`) across >= 2 different days, passes
   the 1.2 quality judge, and has no open contradiction. Promotion is an event
   in `memory_events`, reversible via demote.
2. **Demotion/decay:** confidence decays for items not re-observed (e.g.
   half-life measured in weeks, faster for `todo`, slower for `preference`).
   Items decaying below the retrieval floor become dormant — excluded from
   packets, kept for explicit search. This finally uses `last_seen_at` for
   something.
3. **Contradiction handling:** at upsert, run new facts against same-scope
   same-kind items (FTS + entity overlap); on conflict, the newer correction
   supersedes: old item gets status=superseded with a `superseded_by` event,
   new item inherits the evidence trail. A `correction` kind item that matches
   an existing item's topic should always trigger this check — 366 corrections
   exist today and none has ever retired anything.
4. **Human-in-the-loop stays, but moves to the dashboard (2.2)** — one-click
   promote/demote/edit/tombstone where the items are visible, instead of a CLI
   over opaque numbered files.
5. **Fix the misleading `accepted/` semantics (B3):** auto-consolidation
   currently moves any candidate with promoted lines into `accepted/` — 2,315
   files that masquerade as human-reviewed when zero review has ever happened.
   Auto-processed candidates should move to `consolidated/`, reserving
   `accepted/`/`rejected/` for genuine human verdicts, so the review state of
   the store is legible.

**Priority: P1** (after 1.2, since promoting today's items would canonize
junk).

### 1.5 Tombstones and dedup (P1, effort S)

**What/why.** B6's 66 near-duplicate groups; ROADMAP's tombstone item; deleted
Granola notes currently live forever in `memory/granola/` because sync only
ever adds.

**Approach.** Add `tombstoned` handling end-to-end (status exists in docs but
nothing sets it): excluded from retrieval and views, kept for audit, and the
memory_hash of a tombstoned item blocks re-insertion of the same text (today a
deleted item would simply be re-learned next session). Near-dup merge: on
insert, check normalized-text similarity (token-set ratio is enough pre-
embeddings) against same-scope items and merge evidence instead of inserting.
For Granola: on sync, list current note ids and tombstone cached files whose
notes 404 or disappeared from state.

### 1.6 Scoping fixes (P2, effort S)

**What/why.** `scope_for_cwd` (core.py:627) maps anything outside
`~/projects` to `global` (77 items polluting every project's packet) and
`memory_hash` (core.py:622) includes scope+kind, so the same fact learned in
two projects or reclassified duplicates silently. Top-3-path-segment
`project_terms` also mean `~/projects/jawnty-me/career/jobsearch` scopes to
`jawnty-me` — reasonable, but sub-project scoping (e.g. `jawnty-me/career`)
would help the 600-item jawnty-me scope.

**Approach.** Introduce `home:<dir>` scopes for non-project cwds instead of
global (global becomes an explicitly assigned scope, mostly by the 1.2 LLM
pass); hash on normalized text only, letting kind/scope be mutable metadata;
allow two-level project scopes with retrieval falling back up the hierarchy.

### 1.7 MCP server: explicit lookup and writeback (P1, effort M) [validation-asset]

**What/why.** Ambient injection is push-only and capped; the agent cannot ask
jmem a follow-up ("what did we decide about X in the last portfolio-monitor
session?") nor deliberately save a fact mid-session. Both agents speak MCP, and
this is on the ROADMAP already. Explicit `jmem_remember` also produces the
highest-quality memories possible (agent-curated at the moment of decision) —
exactly the training data the 1.4 promotion rule wants.

**Approach.** A small stdio MCP server (`jmem mcp`) exposing:
`jmem_search(query, scope?, kinds?)`, `jmem_context(prompt)` (same packet
builder, on demand), `jmem_remember(text, kind, scope)` (writes a
pre-classified high-trust candidate), `jmem_forget(id|text)` (tombstone), and
`jmem_explain(query)`. Register in both Claude Code (`.mcp.json`/settings) and
Codex (`config.toml`) via `jmem init` (3.2). No new dependencies are strictly
required (MCP stdio JSON-RPC is implementable in stdlib, matching jmem's
zero-dep stance), but using the official `mcp` package as an optional extra is
acceptable.

### 1.8 Optional embeddings / hybrid retrieval (P3, effort M-L)

**What/why.** ROADMAP correctly gates this on observed FTS misses — and today
there is no miss measurement, so the gate can never open. FTS with OR-of-terms
(core.py:582) has known failure modes (synonyms, paraphrase, "what did Bob say
about pricing" vs transcript wording), but the honest position is: instrument
first (2.1 logs zero-match and low-score prompts), then decide.

**Approach when the data says go:** local embedding model via `sqlite-vec` +
a small ONNX/gguf embedder, embedding memory_items and chunk summaries (not 7.5k
raw transcript chunks); hybrid rank via reciprocal-rank-fusion of FTS and
vector lists. Keep it an optional extra (`pip install jmem[vec]`) to preserve
the no-deps core.

### 1.9 Refactor core.py + test suite (P1, effort M)

**What/why.** B9. Every fix above lands in one 1,917-line file with no tests;
the Codex bug survived ~10 weeks precisely because nothing exercised the
transcript parser against real fixtures. This is now the riskiest file John
owns that has zero coverage.

**Approach.** Split by seam, mechanically (no behavior change in the same
commit as moves): `db.py` (connection/schema/migrations), `indexer.py` (walk +
chunk + upsert), `granola.py`, `retrieval.py` (tokens/scoring/packet),
`extraction.py` (transcript parsers + candidate lines + classify),
`consolidate.py`, `hooks.py` (both agents' entrypoints), `cli.py`. Add pytest
with: fixture transcripts (Claude + Codex rollout, including the
embedded-newline case), extraction golden tests, retrieval scoring tests
against a small seeded DB, and a hook end-to-end test piping event JSON on
stdin. Add schema versioning in `metadata` with tiny forward migrations —
required anyway before 1.4/1.5 alter semantics.

**Split across phases to honor test-first:** the *minimal* pytest scaffolding —
`tests/` with fixture transcripts (Claude + Codex rollout, including the
embedded-newline case) and golden tests for extraction and gating — lands in
**Phase 1, before or with 1.1/1.2/1.3**, since those are the riskiest behavior
changes and shipping them into an untested monolith would contradict this
plan's own working rules. The full module split and broader coverage remain
Phase 2.

### 1.10 Get hook latency out of the hot path (P1, effort S)

**What/why.** B8. A synchronous full re-index inside UserPromptSubmit is the
kind of thing that makes John type ahead of a stalled prompt once an hour;
`maybe_auto_consolidate` inside Stop can also stall session close.

**Approach.** Hooks never index or consolidate. `ensure_index` in the hook
path becomes: use the index as-is; if stale, touch a `reindex-requested` marker
and continue. A lightweight launchd interval job (the existing hourly
consolidator, renamed `jmem maintain`) becomes the single home for all
background mutation: index refresh, granola sync, consolidation (including the
1.2 LLM pass — hard dependency, see 1.2b), decay and tombstone sweeps, plus
the housekeeping nothing schedules today (B14): `candidates prune` (27MB /
3,459 files and growing), `hooks.jsonl` rotation (5.7MB append-only, currently
read whole-file by `trace`/`doctor`), and the 1.11 backup. Also cap hook
wall-time with an internal deadline (return empty packet rather than block).
Log hook duration per event in `hooks.jsonl` (currently unmeasured) so
regressions show in the dashboard.

**Concurrency and locking (B13).** Concurrent sessions firing hooks against
one SQLite file is the daily norm, and today's code has no story for it:
`connect()` sets no `busy_timeout`, and the blanket `except` blocks in
`ensure_index`/`maybe_auto_consolidate` can silently swallow "database is
locked" — a lost write with no trace. Required alongside the hot-path work:

- **Single-writer discipline:** hooks become read-only against the DB (they
  only append to `hooks.jsonl` and write candidate files — both already
  per-file atomic); all DB mutation flows through the launchd maintainer, and
  dashboard mutations (2.2) go through one serialized path (the maintainer's
  code, invoked in-process behind a lock), not a fourth ad-hoc writer.
- `PRAGMA busy_timeout` (a few seconds) in `connect()` so residual contention
  waits instead of erroring.
- A `flock`-guarded lockfile around re-index/consolidate so overlapping
  maintainer runs (or a manual `jmem index` racing the maintainer) serialize.
- Locked/failed operations get logged, never silently dropped.

### 1.11 Backup and restore of the brain (P1, effort S)

**What/why.** B14. `index/jmem.sqlite` is the only copy of
memory_items/evidence/events in existence — the source chunks are rebuildable
from files, but the extracted memory is not, especially once candidate files
get pruned. A corrupted DB (see B13's locking gaps) or a bad migration is
total memory loss. The plan's own 1.2 cleanup migration is a destructive bulk
operation and must not run without this.

**Approach.** `jmem backup`: SQLite online `.backup` of `jmem.sqlite` plus a
tarball of `memory/candidates/` and `memory/canon/`, written to
`~/.jmem/backups/` with simple rotation (keep last N daily + M weekly). Run
automatically by the maintainer (1.10); `jmem restore <snapshot>` for the
inverse. Any schema migration (1.9/3.3) and the 1.2 cleanup snapshot first as
a non-optional precondition.

---

## 2. Observability: Measurement, Dashboard, CLI

### 2.1 Effectiveness measurement (P0 for instrumentation, effort M) [validation-asset]

**What/why.** SPEC-proactive-v0.md already names the core problem: "You cannot
prove it is helping." Nothing today records whether an injected packet was
used. This is also the startup's category-wide weakness — a working lift metric
is both a personal decision tool and the strongest possible landing-page claim.

**Approach — instrument first, judge later:**

1. **Log injected item identity, not just counts:** per UserPromptSubmit,
   record the memory_item ids and chunk ids injected plus their scores
   (extend the `hooks.jsonl` record; today only `top_paths`/`top_sources`).
2. **Reference detection (cheap, automatic — with a contamination guard):**
   at Stop time, the (now LLM-assisted, 1.2) consolidation pass additionally
   answers: did the assistant's output reference any injected item? Critical
   design constraint: the Stop-time transcript *contains the injected packet
   itself* (it arrived as user-turn context), so naive token-overlap matching
   over the whole transcript would false-positive on nearly every injection.
   Matching MUST score **assistant-role message content only**, which requires
   the role-aware transcript parsing built in 1.1 — reference detection
   therefore depends on that parser work, for both agents' formats. Store
   per-item `hit` / `miss` events. This yields per-item, per-source, and
   per-project hit rates over time — e.g. "granola_api snippets got referenced
   in 2% of injections; project_doc in 31%" — the data needed to tune source
   weights (1.3/4.1) and to open the embeddings gate (1.8). Caveat to keep
   honest in the dashboard: "referenced" is a proxy, not proof of help — an
   agent can echo an injected fact uselessly, or benefit silently. Hit rate
   ranks sources and items; only the holdout (item 5) measures lift.
3. **Token cost accounting:** injected_chars is already logged; add a running
   tokens-injected estimate and cost per model to stats/dashboard, so "6M
   tokens injected, X% referenced" is a single visible number.
4. **Miss capture:** log prompts where retrieval found nothing or was gated,
   plus explicit user signals (an MCP `jmem_remember` call right after a gated
   prompt is a retrieval miss worth flagging).
5. **Deterministic A/B holdout (Phase 2, not optional):** skip injection for
   sessions where `hash(session_id) % n == 0` (~20 lines), log the assignment,
   and compare holdout vs injected sessions on whatever outcome proxies exist
   (re-paste frequency, explicit `jmem_remember` calls after gated prompts,
   session length on comparable tasks). This is the only *causal* measure of
   lift in the plan — everything else is correlational — which is why it is
   promoted to a scheduled Phase 2 item rather than a someday flag.

### 2.2 Local web dashboard (P1, effort M-L) [validation-asset]

**What/why.** The CLI observability is good for John-as-developer and bad for
John-as-user: candidate review died as a CLI workflow (B3), and there is no way
to see the system's behavior over time. A local dashboard is also the demo
surface a stranger would evaluate.

**Approach.** `jmem dashboard` serving on localhost — stdlib `http.server` +
vanilla HTML/JS per the golden-stack rule (no framework; it reads
`jmem.sqlite` and `hooks.jsonl` directly, so no new storage). Views, in
priority order:

1. **Injection feed:** live tail of hook events — prompt prefix, gated or
   injected, packet size, items with scores, per-item hit/miss once 2.1 lands.
   Click an event to see the full packet and the `--explain` breakdown.
2. **Memory browser + review queue:** memory_items filterable by
   scope/kind/status/confidence, sorted by evidence or staleness, with
   one-click promote-to-canon / tombstone / edit-text / change-scope (writes
   `memory_events`). This replaces the CLI candidate-review loop as the human
   trust boundary and is the delivery vehicle for the 1.2 cleanup migration
   (bulk-select and tombstone).
3. **Stats:** per-project and per-source injection counts, hit rates, token
   cost, index composition (the granola-dominance chart), candidate flow
   (written/consolidated/rejected per day), Codex-vs-Claude split (needs the
   agent field from 1.1).
4. **Doctor panel:** the `jmem doctor` checks rendered green/red with fix
   hints.

Security: bind to `127.0.0.1` only, and protect every mutating endpoint with a
per-launch random token checked as a header (plus same-origin checks). Without
this, any webpage John visits could blind-POST to localhost and rewrite the
memory that gets injected into every future agent session — a drive-by
memory-poisoning vector. Dashboard writes go through the single serialized
mutation path from 1.10, not their own DB connection.

### 2.3 CLI ergonomics (P2, effort S)

- `jmem memory list|show|edit|tombstone|promote` — first-class item-level
  commands (today items are only reachable via SQL or the generated soft.md).
- `jmem stats --json`, `doctor --json` for scripting/heartbeats.
- `jmem trace --watch` (follow mode) and `--session <id>` filtering.
- `jmem why <prompt>` as a friendlier alias for `context --explain`.
- Fix `cmd_candidates_list` O(n^2) `paths.index(path)` (core.py:1618) and the
  glob-everything-every-call candidate listing — with 3,459 files these
  commands already drag.

---

## 3. Installation and Distribution

### 3.1 Real installable: uv/pipx, tagged releases (P1, effort S) [validation-asset]

**What/why.** B10. `pyproject.toml` already defines entry points; the gap is
that the blessed path is still clone + symlinks + three bespoke installer
scripts, and version 0.4.0 has no tag. Zero runtime deps makes jmem an ideal
pipx/uv citizen.

**Approach.** Publish to PyPI (or keep GitHub-only: `uv tool install
git+https://github.com/jawnty/jmem`); tag releases; delete `setup.py` (
pyproject is sufficient) and the `UNKNOWN.egg-info`/`jmem.egg-info` clutter;
CI on GitHub Actions running the 1.9 test suite on macOS + Linux. Installed
mode already routes state to `~/.jmem` (core.py:23) — make that the documented
default and repo-mode the dev exception. Keeping all state self-contained
under `~/.jmem` also honors the stated single-machine v0 scope while leaving
the door open: a future multi-machine story becomes "sync one directory", not
a redesign. Homebrew tap is optional later polish
(S, P3); pipx/uv covers the actual audience.

### 3.2 One-command `jmem init` (P1, effort M) [validation-asset]

**What/why.** Today wiring requires knowing about three scripts and two hook
files. A stranger — or John on a new machine — should get to a working loop in
one command. This is also where the current installers' gaps get fixed: they
merge JSON but the launchd installers and hook installers know nothing about
each other, and nothing verifies end-to-end.

**Approach.** `jmem init` does, idempotently and with a printed plan first:
detect Claude Code (`~/.claude/settings.json`) and Codex (`~/.codex/`), wire
UserPromptSubmit + Stop hooks (absorbing `scripts/install-hooks`); detect
Granola key via the existing chain and offer sync; install background
maintenance (launchd on macOS — absorbing both launchd scripts into one
`com.jmem.maintain` agent per 1.10; cron/systemd-user on Linux); create
`~/.jmem/config.toml` with commented defaults (written from a commented
template string — stdlib `tomllib` reads TOML but has no writer, so the config
is templated, never serialized); run initial index; finish by running
`jmem doctor` and an end-to-end round-trip. That round-trip must validate the
**agent-side contract**, not just jmem's stdout (B12): piping a fake event
through the hook entrypoints only proves jmem emitted something — the check
should also confirm the output shape each agent actually consumes (and, where
feasible, plant a marker fact and verify it surfaces in a real minimal agent
turn, as in 1.1.4). Add `jmem uninstall` doing the exact inverse — trust
requires a clean exit path.

### 3.3 Health checks and upgrade path (P2, effort S)

- `jmem doctor --fix` for the mechanical findings (missing hook entry, unloaded
  LaunchAgent, stale index, missing dirs).
- Version stamping in the DB (`metadata.schema_version`) + auto-migration on
  first run of a new version (from 1.9), with a 1.11 backup snapshot taken
  automatically before any migration runs; `jmem doctor` warns when hook files
  point at a path that no longer matches the installed package (the exact
  failure mode a pipx upgrade of today's symlink install would cause).
- Cross-platform notes: core (index/retrieve/hooks/consolidate) is
  pure-stdlib and portable now; the macOS-only pieces are launchd and the
  Granola local-cache fallback. Keep the scheduler behind a small interface so
  Linux gets cron/systemd-user units; document Windows as unsupported.

---

## 4. Other Material Findings

### 4.1 Granola chunk dominance and transcript policy (P1, effort S-M)

B5. 80% of the FTS candidate pool is meeting-transcript text, which is verbose,
speaker-fragmented, and mostly noise per token; it crowds the packet (2,417
granola injections) while claude_memory/project_doc content — which the hit-rate
data will likely show is far denser — competes at equal weight.

Approach: index transcripts and summaries as separate sources
(`granola_summary` vs `granola_transcript`); retrieval weights summary chunks
up and transcript chunks down, with a per-packet cap (max 1-2 granola snippets)
until hit rates justify more; keep full transcripts searchable via explicit
`jmem search`/MCP but out of ambient packets by default. Also delete or fix the
dead `iter_granola_api_notes` path (core.py:257 — unused by indexing, which
reads the file cache) and decide whether `granola_local` cache-v6 indexing
(core.py:192) should remain — it double-covers the same meetings with worse
text.

### 4.2 Privacy scopes and injection hygiene (P2, effort S-M)

- Candidate files and memory_items store raw transcript excerpts which can
  contain secrets that appeared in session output; injected packets then
  re-surface them in future sessions (and would surface into *any* project's
  session — meeting notes about person X can be injected while working in a
  public repo). Add: a redaction pass over candidate text (reuse the
  preflight-style secret patterns), per-source privacy levels in config
  (e.g. granola=private -> never injected into cwds outside `~/projects`, or
  an allowlist), and a `jmem doctor` check that scans memory_items for
  secret-shaped strings.
- Persisted prompt-injection surface: text captured from tool output (web
  content) currently flows transcript -> candidate -> memory -> future packet.
  1.1/1.2's tool-output rejection closes most of it; keep "never store text
  originating from tool results" as an explicit extractor invariant, not an
  accident.

### 4.3 Entity views (P3, effort M)

ROADMAP item; becomes cheap after 1.2's LLM pass, which can tag facts with
entities (person/company/project) at extraction time. An `entities` table plus
dashboard view ("everything known about Mukund") and MCP lookup. Do not build
before extraction quality lands — entities over junk facts is negative value.

### 4.4 Proactive v0 tie-in (P3, effort M)

SPEC-proactive-v0.md is a good spec deliberately superseded by the validation
gate. Note only: its prerequisites are exactly this plan's P0/P1 items — the
outcome-logging it needs is 2.1's plumbing, and its ping channel is 1.3's
packet header. Revisit after Phase 2; do not schedule it before the metric
exists.

---

## 5. Phased Sequencing

### Phase 1 — Stop the bleeding, start the measurement (all S/M, all P0)

1. **1.9 minimal test scaffolding first** — `tests/` with fixture transcripts
   (both agents) and golden tests for extraction and gating, so every following
   Phase 1 change lands test-first instead of into an untested monolith. (Full
   refactor stays Phase 2.)
2. **1.10 hot-path removal + concurrency basics** — hooks stop indexing and
   consolidating; the launchd maintainer becomes the single mutation home;
   busy_timeout + flock + logged failures. Sequenced early because 1.2's LLM
   pass is only safe once consolidation lives in the maintainer (hard
   dependency 1.2b), and because single-writer discipline should predate any
   new writers.
3. **1.2 Extraction overhaul + snapshot + one-time store cleanup** — the store
   is the product; nothing else matters while it holds prompt echoes at 0.92.
   Includes the judge hook-isolation kill-switch (1.2a), the privacy decision
   (1.2c), and a 1.11-style backup before the migration.
4. **1.3 Relevance gating + session-delta injection + budget control** —
   delta injection is the largest token win; the gating threshold ships as
   provisional pending Phase 2 hit rates.
5. **2.1 instrumentation (items 1+3: injected-id logging, token accounting)**
   — cheap, and every later decision (source weights, embeddings gate, canon
   thresholds) depends on this data existing early.
6. **1.1 Codex writeback fix + one-time Codex injection verification** —
   S-effort, root cause in hand; ranked after the all-sessions items because
   Codex is ~12% of usage and falling, but it closes B12's false-telemetry
   risk and keeps the cross-agent claim honest.
7. **B7 fix** (stop indexing `memory/canon/` as a source; memory reaches
   packets only via memory_items) — small structural distortion removed before
   tuning begins.

Rationale: Phase 1 makes the existing loop correct and measurable without
adding any new surface, in dependency order: tests before behavior changes,
maintainer before the LLM pass, cleanup before tuning. The cleanup migration
gives an immediately visible quality jump in every session.

### Phase 2 — Trust model and visibility (mostly M, P1)

1. **1.9 full refactor** (start here; Phase 1's fixes and scaffolding define
   the seams and their tests move with them).
2. **1.4 canon lifecycle** (auto-promotion, decay, contradiction/supersede,
   `consolidated/` vs `accepted/` semantics) + **1.5 tombstones/dedup** — now
   safe because the store is clean and evidence counting is honest.
3. **2.1 reference detection** (assistant-role-only hit/miss per item,
   per-source hit rates) riding the LLM consolidation pass, plus the
   **deterministic holdout (2.1.5)** — the only causal lift measure.
4. **1.11 `jmem backup`/`restore`** wired into the maintainer, before the
   Phase 2 schema changes land.
5. **2.2 dashboard** (injection feed, memory browser/review queue, stats;
   localhost-only + token-guarded mutations) — the human trust boundary moves
   here from the dead CLI review flow.
6. **1.7 MCP server** — pull-based lookup + high-trust explicit writeback.
7. **4.1 Granola rebalance** — tuned using Phase 1/2 hit-rate data rather than
   guesswork.
8. **1.3 threshold re-tune** against measured hit rates (closing the
   provisional-threshold loop opened in Phase 1).

Rationale: Phase 2 turns jmem from "pipeline that runs" into "memory John can
audit and trust", and produces the effectiveness numbers. The dashboard comes
after the data model settles so it renders real statuses (canon, superseded,
hit rates), not today's monoculture of soft items.

### Phase 3 — Distribution and depth (P1-P3)

1. **3.1 packaging + CI**, **3.2 `jmem init`/`uninstall`**, **3.3 doctor
   --fix + migrations** — the install story, sequenced after the refactor so
   what gets packaged is the tested, modular version. [validation-asset: this
   trio is the difference between "John's rig" and "a stranger can try it",
   and is required before any Carryover pre-order converts into an install.]
2. **2.3 CLI ergonomics**, **4.2 privacy scopes/redaction**.
3. **Gated by measured data:** **1.8 embeddings/hybrid** (opens only if 2.1
   shows meaningful FTS-miss rates), **4.3 entity views**, **4.4 proactive
   v0**, Homebrew tap, sub-project scoping (1.6 full form).

Rationale: distribution work is worthless if it ships today's extraction bugs,
and the expensive depth features (embeddings, entities, proactive) each have an
explicit evidence gate from Phase 1/2 instrumentation instead of being built on
faith — matching how this project has been run so far: validate, then build.

---

## Appendix: Reproduction Queries

```bash
# Injection rate / packet sizes
python3 -c "import json;rs=[json.loads(l) for l in open('logs/hooks.jsonl')];u=[r for r in rs if r['event']=='UserPromptSubmit'];i=[r for r in u if r['injected_chars']>0];print(len(u),len(i),sum(r['injected_chars'] for r in i)/len(i))"

# Codex vs Claude agent split from the log (session_id UUID version: Codex=v7 "019...", Claude=v4)
python3 -c "import json,collections;rs=[json.loads(l) for l in open('logs/hooks.jsonl')];print(collections.Counter((r['event'],'codex' if str(r.get('session_id','')).startswith('019') else 'claude') for r in rs))"
# -> UPS: claude 3709 / codex 504; Stop: claude 3577 / codex 438

# Codex vs Claude candidate split (candidates carry the source in frontmatter)
grep -rl "source: codex_stop_hook" memory/candidates/ | wc -l   # 5
grep -rl "source: claude_stop_hook" memory/candidates/ | wc -l  # 3454

# All-soft store, long raw items
sqlite3 index/jmem.sqlite "SELECT status,COUNT(*) FROM memory_items GROUP BY status;"
sqlite3 index/jmem.sqlite "SELECT COUNT(*) FROM memory_items WHERE LENGTH(text)>400;"  # 319

# Granola dominance / soft.md double-index
sqlite3 index/jmem.sqlite "SELECT source,COUNT(DISTINCT path),COUNT(*) FROM chunks GROUP BY source;"
```
