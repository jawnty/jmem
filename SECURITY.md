# Security

jmem is designed to keep source material local.

Do not commit:

- `index/`
- `logs/`
- `memory/granola/`
- `.env`
- API keys, access tokens, or generated meeting-note caches

The repository `.gitignore` excludes those paths by default.

Granola notes and transcripts can contain sensitive personal, business, or client
information. They are cached locally only so prompt hooks can stay fast.

Before publishing a fork, run:

```bash
git status --short
git diff --cached --name-only
rg -n "API_KEY|TOKEN|SECRET|Bearer|sk-|ghp_|gho_|AIza|@|/Users/" .
```

