# Roadmap

## v0

- Deterministic local indexing with SQLite FTS.
- Ambient `UserPromptSubmit` hooks for Codex and Claude Code.
- Local source discovery for project docs and common agent memory folders.
- Granola API caching for meeting notes.
- Source snippets injected with file paths and source labels.
- Health and retrieval observability with `jmem doctor`, `jmem trace`, and
  `jmem context --explain`.
- Reviewable writeback candidates from `Stop` hooks and `jmem candidates add`.
- Candidate review commands:
  - `jmem candidates show`
  - `jmem candidates accept`
  - `jmem candidates reject`
  - `jmem candidates prune`

## Next

- Improve the curated extracted-memory layer:
  - `memory/people/`
  - `memory/projects/`
  - candidate-to-bucket suggestions
- Add source-level privacy scopes and retrieval budgets.
- Add tombstones for deleted/404 Granola notes.
- Add optional embeddings after FTS misses are observed.
- Add MCP tools for explicit lookup and writeback.
