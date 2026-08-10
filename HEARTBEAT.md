# HEARTBEAT.md - jmem-weekly
# ⚠️ TO PAUSE: disable the launchd LaunchAgent (`launchctl bootout gui/$(id -u)/com.openclaw.hb-jmem-weekly`). launchd is the only gate - the schedule line below is documentation. DO NOT delete task instructions.

# schedule: Mondays 08:30 America/Los_Angeles (launchd + claude-heartbeat)
delivery: write email file to the central outbox `~/heartbeat-out/pending/` with `project: jmem-weekly` frontmatter - Clawdia Mailer (`com.clawdia.mailer`, 60s scan) delivers via AgentMail

**launchd owns scheduling.** Do NOT add an in-model self-gate. Do NOT invoke
`send_email.py` or AgentMail directly. Write a file, then stop.

This heartbeat is jmem's weekly health + effectiveness digest. jmem is the
local memory layer injecting context into John's Claude Code/Codex sessions.
The digest exists because jmem's failure modes are silent: if maintenance
breaks, injection quietly degrades and nobody notices. Keep the email short —
a paragraph of verdict, then numbers.

## Step 1: Stamp

Use Bash to write the current Pacific timestamp:
`TZ=America/Los_Angeles date +%Y-%m-%dT%H:%M:%S%z > /Users/john/projects/jmem/.last-heartbeat`

## Step 2: Collect health

Run these and capture output (all from `/Users/john/projects/jmem`):

1. `./bin/jmem stats` — note total prompts, injection %, tokens injected,
   **precision** and **miss_rate** lines, memory_items counts.
2. `./bin/jmem doctor` — note any `False` on hooks or LaunchAgents
   (`com.jmem.maintain` matters; `com.jmem.consolidate`/`granola-sync` are
   retired and SHOULD be absent).
3. `tail -5 logs/maintain.log` and `tail -5 logs/maintain.err.log` — the
   maintain summary line runs hourly; flag any `=error:` tokens or a newest
   entry older than ~3 hours.
4. `ls -t backups/daily/ | head -3` — newest DB snapshot should be from
   today or yesterday.
5. Last-7-days effectiveness detail from SQLite:
   `sqlite3 index/jmem.sqlite "SELECT kind, grade, COUNT(*) FROM injection_grades WHERE created_at >= datetime('now','-7 days') GROUP BY kind, grade;"`
   and the noisiest recent prompts:
   `sqlite3 index/jmem.sqlite "SELECT prompt_prefix FROM injection_grades WHERE grade='noise' AND created_at >= datetime('now','-7 days') LIMIT 5;"`

## Step 3: Judge the week

Write a one-paragraph verdict. Rules of thumb:

- **Healthy:** precision >= 75%, misses rare (miss_rate <= ~10%), maintain
  running hourly without errors, fresh backup. Say so in one sentence.
- **Degraded:** precision < 70% or rising noise → suggest threshold tuning
  or a look at the noisy prompts. Misses climbing → gating too aggressive.
- **Broken:** maintain stalled/erroring, doctor shows a hook or agent down,
  or backups stale > 2 days → lead the email with this and the exact
  command to investigate. Do NOT attempt repairs in this heartbeat run.

## Final Step: Queue the Email

```bash
OUTBOX=/Users/john/heartbeat-out/pending
SLUG="jmem-weekly-$(TZ=America/Los_Angeles date +%Y%m%d-%H%M%S)"
cat > "$OUTBOX/.tmp.$SLUG" << 'EMAILEOF'
---
project: jmem-weekly
to: john.thomas@gmail.com
subject: "jmem weekly: <verdict word> — <precision>% precision, <N> misses (<date>)"
html: false
---
<verdict paragraph>

Numbers this week:
- Injections graded: N (relevant X / partial Y / noise Z) -> precision P%
- Silent prompts audited: N (misses M) -> miss rate R%
- Injection rate: I% of prompts; ~T tokens injected total
- Memory store: S soft items (K new this week)
- Maintain: <hourly ok / errors>; newest backup <date>

<only if degraded/broken: one short action item with the exact command>
EMAILEOF
mv "$OUTBOX/.tmp.$SLUG" "$OUTBOX/$SLUG.md"
```

Fill in real values before writing; keep the body under ~25 lines. Then stop.
