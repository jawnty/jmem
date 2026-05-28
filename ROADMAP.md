# Roadmap

## v0

- Deterministic local indexing with SQLite FTS.
- Ambient `UserPromptSubmit` hooks for Codex and Claude Code.
- Local source discovery for project docs and common agent memory folders.
- Granola API caching for meeting notes.
- Source snippets injected with file paths and source labels.

## Next

- Add an extracted-memory layer:
  - `memory/candidates/`
  - `memory/canon/`
  - `memory/people/`
  - `memory/projects/`
- Add post-session writeback using `Stop` hooks.
- Add source-level privacy scopes and retrieval budgets.
- Add tombstones for deleted/404 Granola notes.
- Add optional embeddings after FTS misses are observed.
- Add MCP tools for explicit lookup and writeback.

