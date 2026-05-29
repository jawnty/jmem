# Security

jmem is designed to keep source material local.

Do not commit:

- `index/`
- `logs/`
- `memory/granola/`
- `memory/candidates/`
- `memory/canon/`
- `.env`
- API keys, access tokens, generated meeting-note caches, or generated memory
  files

The repository `.gitignore` excludes those paths by default.

Granola notes and transcripts can contain sensitive personal, business, or client
information. They are cached locally only so prompt hooks can stay fast.

Memory candidates can contain private session details. They are review queues,
not public documentation.

Canon memory files are also private local state. They may contain durable user
preferences, project decisions, people notes, or operational details.

Before publishing a fork, run:

```bash
git status --short
git diff --cached --name-only
rg -n "API_KEY|TOKEN|SECRET|Bearer|sk-|ghp_|gho_|AIza|@|/Users/" .
```
