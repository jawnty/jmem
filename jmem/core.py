from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Iterable
import urllib.error
import urllib.parse
import urllib.request


HOME = Path.home()
PACKAGE_PARENT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PACKAGE_PARENT if (PACKAGE_PARENT / "bin").exists() else HOME / ".jmem"
ROOT = Path(os.environ.get("JMEM_HOME", DEFAULT_ROOT)).expanduser()
DB_PATH = ROOT / "index" / "jmem.sqlite"
LOG_PATH = ROOT / "logs" / "hooks.jsonl"
PROJECTS_ROOT = Path(os.environ.get("JMEM_PROJECTS_ROOT", HOME / "projects")).expanduser()

PROJECT_DOC_NAMES = {"AGENTS.md", "CLAUDE.md", "README.md", "PROGRESS.md", "HEARTBEAT.md"}
SKIP_DIRS = {
    ".git",
    ".next",
    ".nuxt",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "vendor",
}
STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "between",
    "could", "does", "doing", "from", "have", "here", "into", "just", "like",
    "need", "needs", "only", "please", "should", "that", "their", "there",
    "these", "thing", "this", "those", "what", "when", "where", "which",
    "while", "with", "would", "your",
}
TRIVIAL_PROMPTS = {
    "ok", "okay", "yes", "no", "thanks", "thank you", "cool", "great", "done",
    "go ahead", "continue",
}
INDEX_MAX_AGE_SECONDS = 60 * 60
GRANOLA_API_BASE = "https://public-api.granola.ai/v1"
GRANOLA_CACHE_DIR = ROOT / "memory" / "granola"
GRANOLA_STATE = Path(
    os.environ.get("JMEM_GRANOLA_STATE", HOME / ".claude/skills/granola-to-drive/state.json")
).expanduser()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY,
          source TEXT NOT NULL,
          path TEXT NOT NULL,
          title TEXT NOT NULL,
          mtime REAL NOT NULL,
          sha256 TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          content TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
        USING fts5(title, path, content, content='chunks', content_rowid='id');
        CREATE TABLE IF NOT EXISTS metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )


def iter_project_docs() -> Iterable[tuple[str, Path]]:
    for dirpath, dirnames, filenames in os.walk(PROJECTS_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if filename in PROJECT_DOC_NAMES:
                yield ("project_doc", Path(dirpath) / filename)


def iter_memory_files() -> Iterable[tuple[str, Path]]:
    fixed = [
        ("codex_memory", HOME / ".codex/memories/memory_summary.md"),
        ("codex_memory", HOME / ".codex/memories/MEMORY.md"),
        ("clawmail_memory", HOME / ".clawmail/memory/curated.md"),
    ]
    for source, path in fixed:
        if path.exists():
            yield source, path

    claude_projects = HOME / ".claude/projects"
    if claude_projects.exists():
        for memory_dir in sorted(claude_projects.glob("*/memory")):
            if memory_dir.is_dir():
                for path in sorted(memory_dir.rglob("*.md")):
                    yield "claude_memory", path

    for pattern, source in [
        (HOME / ".codex/automations", "codex_automation_memory"),
        (HOME / ".clawmail/memory/notes", "clawmail_note"),
        (HOME / ".openclaw/memory/notes", "openclaw_note"),
    ]:
        if not pattern.exists():
            continue
        for path in sorted(pattern.rglob("*.md")):
            yield source, path


def iter_granola_local_cache() -> Iterable[tuple[str, str, str]]:
    cache_path = HOME / "Library/Application Support/Granola/cache-v6.json"
    if not cache_path.exists():
        return
    try:
        data = json.loads(cache_path.read_text(errors="ignore"))
    except Exception:
        return
    state = data.get("cache", {}).get("state", {})
    documents = state.get("documents") or state.get("documentLists") or {}
    if isinstance(documents, dict):
        for doc_id, doc in documents.items():
            if not isinstance(doc, dict):
                continue
            title = str(doc.get("title") or doc.get("name") or doc_id)
            bits = []
            for key in ("title", "summary", "notes", "transcript", "text"):
                value = doc.get(key)
                if isinstance(value, str) and value.strip():
                    bits.append(value.strip())
            if bits:
                yield ("granola_local", f"granola:{doc_id}", title + "\n\n" + "\n\n".join(bits))


def granola_api_token() -> str | None:
    for key in ("GRANOLA_API_KEY", "GRANOLA_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value.strip()
    env_file = PROJECTS_ROOT / ".env"
    try:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "GRANOLA_API_KEY":
                    return value.strip().strip('"').strip("'")
    except Exception:
        pass
    for path in [
        HOME / ".config/granola/api-key",
        HOME / ".config/granola/token",
    ]:
        try:
            if path.exists():
                value = path.read_text().strip()
                if value:
                    return value
        except Exception:
            continue
    return None


def granola_get_json(path: str, token: str, params: dict[str, str] | None = None) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"{GRANOLA_API_BASE}{path}{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def iter_granola_api_notes(limit: int = 30) -> Iterable[tuple[str, str, str]]:
    token = granola_api_token()
    if not token:
        return
    try:
        listed = granola_get_json("/notes", token, {"page_size": str(min(limit, 30))})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return
    for note in listed.get("notes", [])[:limit]:
        note_id = note.get("id")
        if not note_id:
            continue
        try:
            detail = granola_get_json(f"/notes/{note_id}", token, {"include": "transcript"})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        title = detail.get("title") or note.get("title") or note_id
        bits = [
            f"# {title}",
            f"id: {note_id}",
            f"web_url: {detail.get('web_url', '')}",
            f"created_at: {detail.get('created_at', '')}",
            f"updated_at: {detail.get('updated_at', '')}",
        ]
        calendar = detail.get("calendar_event") or {}
        if calendar:
            bits.append(f"calendar_event: {calendar.get('event_title', '')}")
        attendees = detail.get("attendees") or []
        if attendees:
            bits.append(
                "attendees: "
                + ", ".join(
                    str(a.get("email") or a.get("name") or "")
                    for a in attendees
                    if isinstance(a, dict)
                )
            )
        for key in ("summary_markdown", "summary_text"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                bits.append(value.strip())
                break
        transcript = detail.get("transcript")
        if isinstance(transcript, list):
            transcript_text = "\n".join(
                str(item.get("text", "")).strip()
                for item in transcript
                if isinstance(item, dict) and item.get("text")
            )
            if transcript_text:
                bits.append("## Transcript\n" + transcript_text[:40_000])
        yield ("granola_api", f"granola-api:{note_id}", "\n\n".join(bits))


def render_granola_note(note_id: str, detail: dict, fallback_title: str = "") -> str:
    title = detail.get("title") or fallback_title or note_id
    bits = [
        f"# {title}",
        "",
        f"Granola ID: {note_id}",
        f"Source: Granola API",
        f"Created: {detail.get('created_at', '')}",
        f"Updated: {detail.get('updated_at', '')}",
    ]
    if detail.get("web_url"):
        bits.append(f"URL: {detail.get('web_url')}")
    calendar = detail.get("calendar_event") or {}
    if calendar:
        bits.append(f"Calendar event: {calendar.get('event_title', '')}")
    attendees = detail.get("attendees") or []
    if attendees:
        rendered = []
        for attendee in attendees:
            if isinstance(attendee, dict):
                rendered.append(str(attendee.get("name") or attendee.get("email") or "").strip())
        if rendered:
            bits.append("Attendees: " + ", ".join(x for x in rendered if x))
    for key in ("summary_markdown", "summary_text"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            bits.extend(["", "## Summary", "", value.strip()])
            break
    transcript = detail.get("transcript")
    if isinstance(transcript, list):
        lines = []
        for item in transcript:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            speaker = str(item.get("speaker") or item.get("speaker_name") or "").strip()
            lines.append(f"{speaker}: {text}" if speaker else text)
        if lines:
            bits.extend(["", "## Transcript", "", "\n".join(lines)[:80_000]])
    return "\n".join(bits).strip() + "\n"


def granola_state_note_ids() -> dict[str, str]:
    try:
        state = json.loads(GRANOLA_STATE.read_text())
    except Exception:
        return {}
    notes = state.get("notes", {})
    if not isinstance(notes, dict):
        return {}
    out: dict[str, str] = {}
    for note_id, meta in notes.items():
        if not isinstance(note_id, str):
            continue
        title = ""
        if isinstance(meta, dict):
            title = str(meta.get("title") or "")
        out[note_id] = title
    return out


def iter_granola_cache_files() -> Iterable[tuple[str, Path]]:
    if not GRANOLA_CACHE_DIR.exists():
        return
    for path in sorted(GRANOLA_CACHE_DIR.glob("*.md")):
        yield "granola_api", path


def sync_granola_notes(args: argparse.Namespace) -> int:
    token = granola_api_token()
    if not token:
        print(
            "GRANOLA_API_KEY not found in environment, "
            f"{PROJECTS_ROOT}/.env, or ~/.config/granola/api-key",
            file=sys.stderr,
        )
        return 2
    note_ids = granola_state_note_ids()
    if args.recent:
        try:
            listed = granola_get_json("/notes", token, {"page_size": str(min(args.recent, 30))})
            for note in listed.get("notes", [])[:args.recent]:
                if note.get("id"):
                    note_ids.setdefault(note["id"], note.get("title") or "")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Granola recent-note listing failed: {exc}", file=sys.stderr)
            return 1
    if args.limit:
        note_ids = dict(list(note_ids.items())[:args.limit])
    GRANOLA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fetched = 0
    skipped = 0
    failed = 0
    for idx, (note_id, title) in enumerate(note_ids.items(), start=1):
        path = GRANOLA_CACHE_DIR / f"{note_id}.md"
        if path.exists() and not args.force:
            skipped += 1
            continue
        try:
            detail = granola_get_json(f"/notes/{note_id}", token, {"include": "transcript"})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            failed += 1
            if args.verbose:
                print(f"failed {note_id}: {exc}", file=sys.stderr)
            continue
        tmp = path.with_suffix(".tmp")
        tmp.write_text(render_granola_note(note_id, detail, title), encoding="utf-8")
        tmp.replace(path)
        fetched += 1
        if args.verbose and fetched % 10 == 0:
            print(f"fetched {fetched} / {len(note_ids)}")
        time.sleep(args.sleep)
    print(f"granola_sync fetched={fetched} skipped={skipped} failed={failed} cache={GRANOLA_CACHE_DIR}")
    if args.index:
        return index_sources(None)
    return 0


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > 2_000_000:
            return None
        return path.read_text(errors="ignore")
    except Exception:
        return None


def title_for(path: Path, text: str) -> str:
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:180] or path.name
    return path.name


def chunk_text(text: str, max_chars: int = 2200) -> list[str]:
    parts = re.split(r"\n(?=#{1,4}\s)|\n{2,}", text)
    chunks: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(current) + len(part) + 2 <= max_chars:
            current = f"{current}\n\n{part}".strip()
        else:
            if current:
                chunks.append(current)
            if len(part) <= max_chars:
                current = part
            else:
                for i in range(0, len(part), max_chars):
                    chunks.append(part[i:i + max_chars])
                current = ""
    if current:
        chunks.append(current)
    return chunks


def upsert_document(conn: sqlite3.Connection, source: str, path: str, title: str, text: str, mtime: float) -> int:
    sha = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    existing = conn.execute(
        "SELECT sha256 FROM chunks WHERE path = ? LIMIT 1",
        (path,),
    ).fetchone()
    if existing and existing["sha256"] == sha:
        return 0
    conn.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE path = ?)", (path,))
    conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
    count = 0
    for idx, chunk in enumerate(chunk_text(text)):
        cur = conn.execute(
            """
            INSERT INTO chunks(source, path, title, mtime, sha256, chunk_index, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source, path, title, mtime, sha, idx, chunk),
        )
        rowid = cur.lastrowid
        conn.execute(
            "INSERT INTO chunks_fts(rowid, title, path, content) VALUES (?, ?, ?, ?)",
            (rowid, title, path, chunk),
        )
        count += 1
    return count


def index_sources(_: argparse.Namespace | None = None) -> int:
    conn = connect()
    init_db(conn)
    seen_paths: set[str] = set()
    changed = 0
    files = 0

    all_files = list(iter_project_docs()) + list(iter_memory_files()) + list(iter_granola_cache_files())
    for source, path in all_files:
        text = read_text(path)
        if not text:
            continue
        files += 1
        seen_paths.add(str(path))
        changed += upsert_document(conn, source, str(path), title_for(path, text), text, path.stat().st_mtime)

    for source, path, text in iter_granola_local_cache():
        files += 1
        seen_paths.add(path)
        changed += upsert_document(conn, source, path, path, text, time.time())

    if seen_paths:
        placeholders = ",".join("?" for _ in seen_paths)
        stale = conn.execute(f"SELECT DISTINCT path FROM chunks WHERE path NOT IN ({placeholders})", tuple(seen_paths)).fetchall()
        for row in stale:
            conn.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE path = ?)", (row["path"],))
            conn.execute("DELETE FROM chunks WHERE path = ?", (row["path"],))

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES ('last_indexed_at', ?)",
        (now,),
    )
    conn.commit()
    print(f"indexed files={files} changed_chunks={changed} db={DB_PATH}")
    return 0


def ensure_index() -> None:
    if not DB_PATH.exists():
        index_sources(None)
        return
    try:
        conn = connect()
        init_db(conn)
        row = conn.execute("SELECT value FROM metadata WHERE key = 'last_indexed_at'").fetchone()
        if not row:
            index_sources(None)
            return
        last = dt.datetime.fromisoformat(row["value"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.timezone.utc)
        age = (dt.datetime.now(dt.timezone.utc) - last).total_seconds()
        if age > INDEX_MAX_AGE_SECONDS:
            index_sources(None)
    except Exception:
        return


def tokens(text: str) -> list[str]:
    found = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.@/-]{2,}", text.lower())
    cleaned = []
    for token in found:
        token = token.strip("._-/")
        if token and token not in STOPWORDS and len(token) >= 3:
            cleaned.append(token)
    return list(dict.fromkeys(cleaned))


def project_terms(cwd: str) -> list[str]:
    try:
        rel = Path(cwd).resolve().relative_to(PROJECTS_ROOT)
    except Exception:
        return []
    parts = [p for p in rel.parts[:3] if p and not p.startswith(".")]
    terms: list[str] = []
    for part in parts:
        terms.append(part.lower())
        terms.extend(t for t in re.split(r"[-_]", part.lower()) if len(t) >= 3)
    return list(dict.fromkeys(terms))


def fts_query(query_terms: list[str]) -> str:
    safe = []
    for term in query_terms[:18]:
        term = re.sub(r"[^A-Za-z0-9_./@-]", "", term)
        if term:
            safe.append(f'"{term}"')
    return " OR ".join(safe)


def snippet(content: str, query_terms: list[str], max_chars: int = 620) -> str:
    lower = content.lower()
    starts = [lower.find(term.lower()) for term in query_terms if lower.find(term.lower()) >= 0]
    start = max(min(starts) - 160, 0) if starts else 0
    out = re.sub(r"\s+", " ", content[start:start + max_chars]).strip()
    if start:
        out = "..." + out
    if start + max_chars < len(content):
        out += "..."
    return out


def retrieve(cwd: str, prompt: str, limit: int = 8) -> list[sqlite3.Row]:
    ensure_index()
    conn = connect()
    init_db(conn)
    q_terms = tokens(prompt)
    p_terms = project_terms(cwd)
    terms = list(dict.fromkeys(q_terms + p_terms))
    if not terms:
        return []

    rows: list[sqlite3.Row] = []
    query = fts_query(terms)
    if query:
        try:
            rows.extend(
                conn.execute(
                    """
                    SELECT c.*, bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.rowid
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT 40
                    """,
                    (query,),
                ).fetchall()
            )
        except sqlite3.OperationalError:
            pass

    cwd_path = str(Path(cwd).resolve())
    if cwd_path.startswith(str(PROJECTS_ROOT)):
        rows.extend(
            conn.execute(
                """
                SELECT *, -10.0 AS rank
                FROM chunks
                WHERE path LIKE ?
                ORDER BY mtime DESC
                LIMIT 10
                """,
                (cwd_path.rstrip("/") + "/%",),
            ).fetchall()
        )

    scored: list[tuple[float, sqlite3.Row]] = []
    seen: set[int] = set()
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        haystack = f"{row['title']} {row['path']} {row['content']}".lower()
        score = 0.0
        for term in q_terms:
            if term in haystack:
                score += 2.0
        for term in p_terms:
            if term in haystack:
                score += 4.0
        if str(row["path"]).startswith(cwd_path.rstrip("/") + "/"):
            score += 8.0
        age_days = max((time.time() - float(row["mtime"])) / 86400, 0)
        score += max(0, 3.0 - min(age_days / 30.0, 3.0))
        scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    unique: list[sqlite3.Row] = []
    seen_paths: set[str] = set()
    for score, row in scored:
        if score <= 0:
            continue
        if row["path"] in seen_paths:
            continue
        seen_paths.add(row["path"])
        unique.append(row)
        if len(unique) >= limit:
            break
    return unique


def build_context(cwd: str, prompt: str, max_chars: int = 6000) -> str:
    if prompt.strip().lower() in TRIVIAL_PROMPTS:
        return ""
    rows = retrieve(cwd, prompt)
    if not rows:
        return ""

    terms = list(dict.fromkeys(tokens(prompt) + project_terms(cwd)))
    lines = [
        "# jmem Ambient Context",
        "",
        "Use this as local memory hints, not guaranteed truth. Verify live repo/service state for volatile facts.",
        "",
    ]
    used = 0
    for row in rows:
        item = (
            f"## {row['title']}\n"
            f"- source: {row['source']}\n"
            f"- path: {row['path']}\n"
            f"- snippet: {snippet(row['content'], terms)}\n"
        )
        if used + len(item) > max_chars:
            break
        lines.append(item)
        used += len(item)
    return "\n".join(lines).strip()


def cmd_context(args: argparse.Namespace) -> int:
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read()
    context = build_context(args.cwd, prompt or "", args.max_chars)
    if context:
        print(context)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    rows = retrieve(args.cwd, args.query, args.limit)
    terms = list(dict.fromkeys(tokens(args.query) + project_terms(args.cwd)))
    for row in rows:
        print(f"{row['source']} | {row['path']} | {row['title']}")
        print(snippet(row["content"], terms, 360))
        print()
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    ensure_index()
    conn = connect()
    init_db(conn)
    row = conn.execute(
        "SELECT COUNT(DISTINCT path) files, COUNT(*) chunks FROM chunks"
    ).fetchone()
    sources = conn.execute(
        "SELECT source, COUNT(DISTINCT path) files, COUNT(*) chunks FROM chunks GROUP BY source ORDER BY source"
    ).fetchall()
    last = conn.execute("SELECT value FROM metadata WHERE key = 'last_indexed_at'").fetchone()
    print(f"db={DB_PATH}")
    print(f"last_indexed_at={last['value'] if last else 'unknown'}")
    print(f"files={row['files']} chunks={row['chunks']}")
    for source_row in sources:
        print(f"{source_row['source']}: files={source_row['files']} chunks={source_row['chunks']}")
    return 0


def log_hook(event: dict, injected: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": event.get("hook_event_name"),
        "session_id": event.get("session_id"),
        "turn_id": event.get("turn_id"),
        "cwd": event.get("cwd"),
        "prompt_prefix": (event.get("prompt") or "")[:160],
        "injected_chars": len(injected),
    }
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def hook_main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}

    if mode != "user-prompt" and event.get("hook_event_name") != "UserPromptSubmit":
        return 0

    prompt = event.get("prompt") or ""
    cwd = event.get("cwd") or os.getcwd()
    context = build_context(cwd, prompt)
    log_hook(event, context)
    if not context:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }))
    return 0


def codex_hook_entry() -> int:
    return hook_main(["user-prompt"])


def claude_hook_main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}

    hook_event = event.get("hook_event_name") or event.get("hookEventName")
    if mode != "user-prompt" and hook_event != "UserPromptSubmit":
        return 0

    prompt = (
        event.get("prompt")
        or event.get("user_prompt")
        or event.get("userPrompt")
        or event.get("message")
        or ""
    )
    cwd = event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    context = build_context(cwd, prompt)
    event.setdefault("hook_event_name", hook_event or "UserPromptSubmit")
    event.setdefault("prompt", prompt)
    event.setdefault("cwd", cwd)
    log_hook(event, context)
    if context:
        print(context)
    return 0


def claude_hook_entry() -> int:
    return claude_hook_main(["user-prompt"])


def main() -> int:
    parser = argparse.ArgumentParser(prog="jmem")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="Index configured local sources")
    p_index.set_defaults(func=index_sources)

    p_stats = sub.add_parser("stats", help="Show index stats")
    p_stats.set_defaults(func=cmd_stats)

    p_search = sub.add_parser("search", help="Search memory")
    p_search.add_argument("query")
    p_search.add_argument("--cwd", default=os.getcwd())
    p_search.add_argument("--limit", type=int, default=8)
    p_search.set_defaults(func=cmd_search)

    p_context = sub.add_parser("context", help="Build Codex context packet")
    p_context.add_argument("--cwd", default=os.getcwd())
    p_context.add_argument("--prompt", default="")
    p_context.add_argument("--max-chars", type=int, default=6000)
    p_context.set_defaults(func=cmd_context)

    p_granola = sub.add_parser("granola-sync", help="Fetch Granola notes into the local jmem cache")
    p_granola.add_argument("--limit", type=int, default=0, help="Limit note fetch count for testing")
    p_granola.add_argument("--recent", type=int, default=30, help="Also include this many recent notes from /notes")
    p_granola.add_argument("--sleep", type=float, default=0.22, help="Delay between API note fetches")
    p_granola.add_argument("--force", action="store_true", help="Refetch notes already cached")
    p_granola.add_argument("--index", action="store_true", help="Run jmem index after sync")
    p_granola.add_argument("--verbose", action="store_true")
    p_granola.set_defaults(func=sync_granola_notes)

    args = parser.parse_args()
    return args.func(args)
