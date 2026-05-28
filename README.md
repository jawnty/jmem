# jmem

Local ambient memory for John's Codex and Claude Code workflows.

This v0 is deliberately small:

- Index local project docs, Codex memory, Claude Code memory, Clawmail notes, OpenClaw notes, any locally cached Granola notes, and the latest Granola API notes when `GRANOLA_API_KEY` is configured.
- Exclude Gmail and Google Drive.
- Inject a compact memory packet into Codex through a `UserPromptSubmit` hook.
- Keep retrieval deterministic and inspectable: SQLite FTS plus cwd/project boosts.

## Commands

```bash
/Users/john/projects/jmem/bin/jmem index
/Users/john/projects/jmem/bin/jmem stats
/Users/john/projects/jmem/bin/jmem search "morning brief heartbeat"
/Users/john/projects/jmem/bin/jmem context --cwd /Users/john/projects/heartbeats --prompt "why did morning brief fail?"
/Users/john/projects/jmem/bin/jmem granola-sync --index
```

## Codex Hook

Codex reads `/Users/john/.codex/hooks.json`. The v0 hook calls:

```bash
/Users/john/projects/jmem/bin/jmem-codex-hook user-prompt
```

The hook reads Codex's JSON event from stdin, runs `jmem context`, and returns
`additionalContext` for the current turn. Hook decisions are logged to
`/Users/john/projects/jmem/logs/hooks.jsonl`.

Codex may require reviewing/trusting the hook through `/hooks` after changes.

## Claude Code Hook

Claude Code reads `/Users/john/.claude/settings.json`. The v0 hook calls:

```bash
/Users/john/projects/jmem/bin/jmem-claude-hook user-prompt
```

Claude Code's `UserPromptSubmit` event injects stdout as context, so this hook
prints the raw `jmem context` packet instead of Codex's JSON wrapper. Claude Code
may require reviewing/trusting the hook through `/hooks` after changes.

## Source Policy

Broad index, narrow injection:

- It is fine to index every `README.md`, `PROGRESS.md`, `HEARTBEAT.md`, `AGENTS.md`, and `CLAUDE.md` under `/Users/john/projects`.
- It is not fine to inject all of that into every prompt.
- Context packets are capped and marked as memory hints, not truth. Volatile facts still need live verification.

Granola note ingestion is part of v0. `jmem granola-sync --index` reads
`GRANOLA_API_KEY` from the environment, `/Users/john/projects/.env`, or
`~/.config/granola/api-key`, fetches notes from the official Granola API, and
caches them under `memory/granola/` for fast local retrieval. The cache is
gitignored because meeting notes are sensitive. The local `granola.db` file
currently appears not to be a plain SQLite database, so v0 does not read it
directly.
