# jmem

Local ambient memory for John's Codex and Claude Code workflows.

This v0 is deliberately small:

- Index local project docs, Codex memory, Claude Code memory, Clawmail notes, OpenClaw notes, and any locally cached Granola notes.
- Exclude Gmail and Google Drive.
- Inject a compact memory packet into Codex through a `UserPromptSubmit` hook.
- Keep retrieval deterministic and inspectable: SQLite FTS plus cwd/project boosts.

## Commands

```bash
/Users/john/projects/jmem/bin/jmem index
/Users/john/projects/jmem/bin/jmem stats
/Users/john/projects/jmem/bin/jmem search "morning brief heartbeat"
/Users/john/projects/jmem/bin/jmem context --cwd /Users/john/projects/heartbeats --prompt "why did morning brief fail?"
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

## Source Policy

Broad index, narrow injection:

- It is fine to index every `README.md`, `PROGRESS.md`, `HEARTBEAT.md`, `AGENTS.md`, and `CLAUDE.md` under `/Users/john/projects`.
- It is not fine to inject all of that into every prompt.
- Context packets are capped and marked as memory hints, not truth. Volatile facts still need live verification.
