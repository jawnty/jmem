
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

---

# Archived: Startup-validation session (pre 2026-08-09)

# jmem Progress

## Status Summary

jmem pivoted from "personal dogfood tool" to "candidate startup," working name **Carryover**, positioned as a neutral, cross-domain context layer across Claude Code + Codex (+ email, calendar, Granola). A 4-agent competitive scan found the category crowded (Mem0, Pieces, GBrain, claude-mem, Letta, Zep, Supermemory) with weak individual-dev willingness-to-pay, so the project is gated on real validation, not more building. A landing/pre-order page is built and deployed to a throwaway preview URL for visual review only; it is NOT yet a live paying test.

## What Was Done This Session

- **Founder-season decision:** committed to a bounded validation season for jmem-as-startup. Objective locked: a company strangers pay for, AI-native (lab acquisition, if any, is a consequence, never the design goal — explicitly rejected "get noticed by labs" as the objective).
- **ICP defined:** the AI-native dev running Claude Code + Codex in parallel, using Wispr Flow, Granola, email — wants one neutral brain injecting cross-domain context into every new session.
- **Competitive research (4 parallel agents, 2026-06-21):** direct competitors, platform/incumbent moves, developer demand signals, adjacent categories. Verdict: crowded red ocean.
  - Mechanism (`UserPromptSubmit` hook + neutral + local SQLite) is commoditized: `rohitg00/agentmemory` (23.5K★), `claude-mem` (83K★ at the time, later cited as ~84K★), `MemPalace` (56K★), Mem0/OpenMemory ($24M raised), Cognee (€7.5M).
  - **Pieces for Developers** already occupies the full intersection (neutral + cross-domain incl. meetings/voice/calendar + local-first); gaps vs jmem are no email capture and pull- not push-based.
  - Individual-dev WTP tops out ~$10-20/mo; true multi-vendor power-user persona is a bleeding-edge niche.
  - Bright spot: platform-absorption threat is LOW — Anthropic/OpenAI structurally won't build cross-vendor memory (OpenAI's `disable_on_external_context` flag actively walls it off; Anthropic won't even sync Claude Code ↔ claude.ai).
- **Garry Tan's GBrain** (open-sourced by YC's president, ~24K★) confirmed the category thesis publicly but intensified competition — a free, blessed reference implementation pushes individual WTP toward zero.
- **YC talk applied** ("How to Get Your First 10 Customers," visiting partner Max): confirmed the plan — customers 1-3 from warm network only, no automation yet, public-pain prospecting (DM people already complaining in r/ClaudeAI etc.), outbound under 75 words, one clear CTA.
- **Reframed the "who pays" debate:** rejected widening the ICP ("wider net catches more payers" is backwards — wide pain is unpayable pain); rejected the team/enterprise pivot for now (John is not the ICP for a team product, no cheap way to reach one). Decision: stay solo-dev, validate before building more, keep Gmail/Calendar as added *sources* not an audience-widening move.
- **Validation plan locked:** Mom Test conversations (past-behavior questions, never "would you pay") with ~5 warm solo-dev contacts (Mukund + others) AND portfolio founders (screen for facts/workarounds, discount their compliments), in parallel with an async pre-order landing page. Decision rule: a **stranger's card**, not a warm friend's nod, is the gate.
- **3-agent research pass for the landing page (2026-06-26):** positioning/differentiation, competitor page + pricing teardown, high-converting landing page patterns.
  - Category clichés to avoid: "memory layer," "second brain," "never lose context," "stateful/self-improving."
  - Winning positioning: lead with vendor-neutral ("your context follows you across agents"), prove with cross-domain, reassure with own-your-brain/open-core.
  - Pricing: $20/mo is the invisible market rate (Mem0/Pieces/Letta/Supermemory all ~$19-20); differentiated move is **$9/mo locked-for-life, first 50 founding members** (nobody else offers a lifetime lock or flat pricing). Real low-end competitor is free local tools, not $19 SaaS.
  - Name "jmem" reads as me-too (worn "mem" morpheme); recommended alternative **Carryover** (also considered: Weft).
- **Landing page built:** `~/projects/jmem/landing/index.html` — single-file vanilla HTML/CSS, dark Warp/Resend-style aesthetic. Sections: hero, problem, how-it-works, an SVG architecture diagram, differentiation, founding pricing, FAQ, founder note, final CTA.
  - Iterated on the diagram 3x based on user feedback: v1 was flat equal-weight cards (rejected, "too simplistic"); v2 added real depth (hook lifecycle text, actual SQLite table names `memory_items`/`memory_evidence`/`memory_events`, a roadmap-tagged concurrent-session-conflict item) but user said "doesn't seem better"; asked a clarifying multi-select question and learned the issue was visual craft (looked like styled text boxes, not a real diagram) — rebuilt as an actual SVG: source nodes (repo, Gmail, calendar, Granola) converge on a glowing central "your brain" node, diverge to Claude Code/Codex agent nodes, with dashed feedback edges showing the Stop-hook write-back. User confirmed this version ("much better").
  - Voice rules enforced: no em dashes, no hype words, no "not X but Y," no category clichés.
  - Deployed to an **isolated Firebase preview site**: `firebase hosting:sites:create jmem-landing-preview --project jtuniverse`, config at `~/projects/jmem/landing/firebase.json` (site: `jmem-landing-preview`) + `~/projects/jmem/landing/.firebaserc` (default: `jtuniverse`). This is deliberately separate from `jawnty` and `jtuniverse` hosting targets — never touches the homepage or other demos.
  - Live preview URL: **https://jmem-landing-preview.web.app** (HTTP 200, verified).
- Also wrote `~/projects/jmem/SPEC-proactive-v0.md` earlier in the season (a one-page PRD for a proactive-ping capability using the existing `UserPromptSubmit` hook) — superseded in priority by the startup-validation gate; not deleted, just not the current focus.
- Separately, wrote a full retro of the related **AI Radar** project at `~/projects/ai-radar/RETRO.md` (no prior retro existed) — its core finding (M3: AI Radar never connected launches to John's actual work) directly validated jmem's cross-domain differentiation angle.

## Active State

- **The preview page is NOT a real test.** All three CTA buttons point to a literal placeholder string `STRIPE_PAYMENT_LINK_HERE`. No card can be charged. This must not be reported as "validated" until a real Stripe Payment Link is wired in.
- **Blockers before this becomes a real pre-order test (all need John):**
  1. Final name (Carryover vs jmem vs other) — page currently branded "Carryover."
  2. A real **Stripe Payment Link** for $9/mo (optionally capped at 50 redemptions) — paste the URL, replace 3 occurrences of `STRIPE_PAYMENT_LINK_HERE` in `landing/index.html`.
  3. Deploy target for the REAL public version — current `jmem-landing-preview.web.app` is a throwaway visual-test site; confirm whether to keep this URL or use a different one for the real launch. **Never deploy to `jawnty` or the main `jtuniverse` site** — those are the protected homepage/demo targets.
  4. Open-source yes/no — decides whether a GitHub "view source" link gets added (research flagged this as a strong trust signal for this audience).
  5. Founder note in the page has a placeholder: `— John, founder. [your real name, photo, and GitHub go here]` — needs John's real identity info.
- **Outreach not yet sent:** the Mom Test emails to Mukund + 4-5 other solo-dev contacts, and the portfolio-founder screen emails, were drafted in concept (short, <75 words, one CTA, per the YC talk) but not yet finalized/sent as of this session.
- **jmem core (the actual tool)** is unchanged this session — still the v0.3 line described in `ARCHIVE.md`'s archived session, live daily-driver on John's Mac Mini via `~/.local/bin/jmem`.
- Git: `landing/`, `PROGRESS.md`, and `SPEC-proactive-v0.md` are untracked in `~/projects/jmem` (not yet committed).

## What's Next

1. **Resolve the 5 blockers above** (name, Stripe link, deploy target, open-source call, founder identity) — all are John decisions, not build work.
2. Once resolved: swap `STRIPE_PAYMENT_LINK_HERE` → real link, redeploy, and treat the first real card entered by a stranger as the actual signal.
3. Send the Mom Test outreach (warm solo-devs + portfolio founders) in parallel with the page going live — per the YC talk, warm conversations first to sharpen language, then push the page to strangers (Reddit r/ClaudeAI, r/ChatGPTCoding, Show HN, Twitter/X riding the GBrain conversation).
4. **Decision rule, unchanged throughout the season: a stranger's card is the gate.** Warm friends saying "sounds cool" does not count. If neither the Mom Test conversations nor the pre-order page produce real payment intent, jmem stays a personal tool (still valuable — daily driver + portfolio piece) and the founder season pivots to a different wedge, not a wider ICP.
5. Keep Google Global Fleet (L9) and Patreon (Head of Engineering) pursuits running passively in parallel per the season's original boundary — do not let this validation work expand into full-time building before the gate is passed.

## Key Decisions Made

- **Company, not personal tool, not "get noticed by labs."** Explicitly resolved a multi-turn ambiguity: the goal is strangers paying for an AI-native product; lab attention is a possible consequence, never the design input.
- **Stay solo-dev ICP for now, do not widen to teams/enterprise or to "anyone with Gmail."** Widening trades acute-but-small pain for vague-but-large disinterest; John is not the ICP for a team product and has no cheap GTM motion for one yet.
- **Validation before more building, always.** Repeated pattern this season: research/interviews/pre-order before code. The competitive scan, the YC talk, and the landing-page pivot were all treated as gates, not just inputs.
- **Card beats compliment.** Friends and portfolio founders will flatter; only unprompted past-behavior facts (existing workarounds, money already spent) or an actual stranger's payment count as signal.
- **Cheap-to-run (Gemma/open model) is a margin and privacy story, not a reason to price low.** Target price anchors at the top of the validated range ($20/mo standard, $9/mo founding), not at $5.
- **Diagrams must show real mechanism, not styled paragraphs.** After 3 iterations, the working principle: use the product's actual internals (real hook names, real table names) as the content, but express it as an actual visual diagram (nodes, hierarchy, a focal point) rather than equal-weight text boxes — content depth and visual craft are separate problems and both must be solved.
