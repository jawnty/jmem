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
