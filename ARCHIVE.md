
---

## Session: 2026-05-28 — v0 public release + observability/candidates

# jmem Progress

## Status Summary

jmem is now a public local-first ambient memory project at `https://github.com/jawnty/jmem`. The v0.3 line has a working broad-index/narrow-injection loop for Codex and Claude Code, plus observability, reviewable writeback candidates, and explicit candidate accept/reject/prune commands.

The local Mac Mini install is active: `jmem` resolves from `~/.local/bin/jmem`, which symlinks to `/Users/john/projects/jmem/bin/jmem`, so repo edits immediately affect the command-line tool and hooks.

## What Was Done This Session

- Published the project publicly as `jawnty/jmem`.
- Added and pushed release docs:
  - `/Users/john/projects/jmem/README.md`
  - `/Users/john/projects/jmem/ROADMAP.md`
  - `/Users/john/projects/jmem/SECURITY.md`
  - `/Users/john/projects/jmem/LICENSE`
- Added package metadata and console entry points:
  - `/Users/john/projects/jmem/pyproject.toml`
  - `/Users/john/projects/jmem/setup.py`
  - `jmem`, `jmem-codex-hook`, `jmem-claude-hook`
- Added README architecture diagram and refined it after screenshot review:
  - removed cramped Mermaid edge labels
  - moved refresh behavior into a text legend
  - changed the jmem core node to a light, high-contrast style for GitHub dark mode
- Built observability commands in `/Users/john/projects/jmem/jmem/core.py`:
  - `jmem doctor`
  - `jmem trace`
  - `jmem context --explain`
- Built reviewable writeback candidates:
  - `jmem candidates add`
  - `jmem candidates list`
  - `jmem candidates show`
  - `jmem candidates accept`
  - `jmem candidates reject`
  - `jmem candidates prune`
  - Codex `Stop` hook support
  - Claude Code `Stop` hook support
  - candidate files under `memory/candidates/`
  - accepted canon files under `memory/canon/`
- Updated `/Users/john/projects/jmem/scripts/install-hooks` to install both `UserPromptSubmit` and `Stop` hooks for Codex and Claude Code.
- Installed live hooks with:
  - `/Users/john/projects/jmem/scripts/install-hooks --all`
- Installed main-path command shims:
  - `~/.local/bin/jmem -> /Users/john/projects/jmem/bin/jmem`
  - `~/.local/bin/jmem-codex-hook -> /Users/john/projects/jmem/bin/jmem-codex-hook`
  - `~/.local/bin/jmem-claude-hook -> /Users/john/projects/jmem/bin/jmem-claude-hook`
- Validated package install in `.venv-test`; latest package version is `jmem-0.3.0`.
- Validated commands and hooks:
  - `python3 -m py_compile ...`
  - `jmem doctor`
  - `jmem trace --limit 2`
  - `jmem context --explain`
  - temp `JMEM_HOME` candidate write
  - temp Codex Stop hook write
  - temp Claude Stop hook write
  - temp transcript-path extraction
  - temp hook installer output
  - temp candidate accept/reject/prune workflow
- Committed and pushed:
  - `b9a6fb2 Prepare jmem v0 for public release`
  - `7df23da Add architecture diagram to README`
  - `a6dd539 Improve README diagram legibility`
  - `ae47f88 Add jmem observability and candidate writeback`
- Tagged initial public release:
  - `v0`

## Active State

- Current branch: `main`.
- Current remote: `origin -> https://github.com/jawnty/jmem.git`.
- Latest pushed commit before candidate-review work: `ae47f88 Add jmem observability and candidate writeback`.
- Generated/private paths are intentionally gitignored:
  - `index/`
  - `logs/`
  - `memory/granola/`
  - `memory/candidates/`
  - `memory/canon/`
  - `.venv/`
  - `.venv-test/`
  - `*.egg-info/`
- `jmem doctor` currently reports:
  - Codex `UserPromptSubmit` hook installed: true
  - Codex `Stop` hook installed: true
  - Claude `UserPromptSubmit` hook installed: true
  - Claude `Stop` hook installed: true
  - Granola token configured: true
  - Granola LaunchAgent file present and loaded: true
  - index exists at `/Users/john/projects/jmem/index/jmem.sqlite`
- Current indexed source counts after the last `jmem index`:
  - files: 744
  - chunks: 7764
  - `granola_api`: 253 files
  - `project_doc`: 273 files
  - `claude_memory`: 109 files
- Candidate writeback remains intentionally conservative:
  - candidates are review queues, not canonical memory
  - promotion requires explicit `jmem candidates accept`
  - generated candidate files are private and ignored by git
  - generated canon files are private and ignored by git

## What's Next

1. Dogfood the new observability loop for a few real Codex and Claude Code sessions:
   - `jmem doctor`
   - `jmem trace --limit 10`
   - `jmem context --cwd "$PWD" --prompt "..." --explain`
2. Review actual Stop-hook candidate quality after a few sessions:
   - `jmem candidates list`
   - inspect files under `/Users/john/projects/jmem/memory/candidates/`
3. Improve candidate quality and promotion ergonomics:
   - better extraction from real Stop-hook payloads
   - candidate-to-bucket suggestions
   - line editing before accept
4. Expand curated memory only after candidate clutter proves the need:
   - `memory/people/`
   - `memory/projects/`
5. Consider tagging a `v0.3.0` release after a little live dogfooding.

## Key Decisions Made

- Use `~/.local/bin` symlinks instead of a global copied install. This keeps command-line usage simple while ensuring the live CLI follows the repo implementation.
- Keep `UserPromptSubmit` retrieval and `Stop` writeback separate:
  - prompt hooks inject narrow context
  - Stop hooks write reviewable candidates
- Do not auto-promote candidates into canonical memory. Human review remains the trust boundary; `accept` is explicit.
- Put polling mode in README prose instead of Mermaid edge labels. GitHub Mermaid edge labels collided with nodes in screenshots and looked unprofessional.
- Keep Mermaid for now because GitHub renders it natively and agents can edit it easily. Revisit D2 or Excalidraw-generated SVG only if the README diagram becomes important product packaging.
- Keep Granola as a first-class source. Meeting notes are core to the value of jmem, not an optional integration.
