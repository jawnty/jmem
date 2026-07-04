# Proactive jmem — v0 Spec (PRD)

Status: draft for review
Date: 2026-06-20
Owner: John
Scope: a single new capability on top of existing jmem. Dogfooded on John only.

## Problem

jmem today is reactive. It injects a relevant context packet before each agent
turn and it does this well. Two gaps remain, and they are the two things that
keep it feeling like a tool instead of a brain:

1. **It only acts when prompted.** It never tells you something you did not ask
   for, even when your own indexed sources or a watched stream contain an item
   that matches a goal you already hold. The judgment to say "you care about
   this, you should see it now" does not exist yet.
2. **You cannot prove it is helping.** You believe it works because you live
   with it, but there is no number. That is the same reason the whole memory
   category is mushy, and it is why you under-trust your own tool.

## v0 capability (exactly one thing)

A proactive intent-matching ping, delivered in-session, with outcome logging.

- You declare a small set of **standing intents** (durable goals or interests).
- jmem watches its already-indexed sources and a short list of streams for new
  items that match an intent.
- When it finds a match, it surfaces **one flagged proactive line at the top of
  your next agent turn**, reusing the `UserPromptSubmit` injection that already
  exists. No new channel. Not email. Not Telegram.
- Every ping is **logged with an outcome**: acted on, useful, or noise.

## Out of scope for v0

Distribution, cross-platform support, new delivery channels, the launchd
refactor, and any multi-user concern. This runs on your machine, for you, on the
plumbing you already have. Those are month-two problems and naming them here is
how we keep them out.

## The metric (this is the actual point)

**Headline: proactive precision.** Of the pings jmem sends you, what fraction did
you act on or mark useful, and how many were genuine **catches** (things you
would have missed without it).

Secondary, added later only once the headline works: a memory-lift number, such
as how often you still have to manually re-paste context the agent should have
had.

## Success criterion (2 weeks)

- A **weekly scorecard** exists and is generated from logged data, not memory.
- Across two weeks: at least a handful of real catches you would have missed,
  and a precision number you would consider worth leaving the feature on.
- A low precision number is also a success. v0 wins by producing the number
  either way. The failure mode is shipping a proactive feature you still cannot
  measure.

## Standing intents (draft — John edits)

Seeded from current life. Keep this to two or three, not ten.

1. Senior engineering-leadership roles at frontier AI labs and top startups
   (active while the job search is live; the canonical "OpenAI just posted a
   role" ping).
2. Competitive and funding moves in LLM memory / context / proactive-agent
   products (so you stop learning about your own market late).
3. People you owe a follow-up or a promised intro (commitments made in calls).

## Open questions for John

- What precision bar counts as "worth leaving it on"?
- Start with how many intents? Recommendation: two.
- Outcome marking: an inline command at ping time, or tagging during the weekly
  scorecard review?
