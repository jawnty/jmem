from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
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
CANDIDATES_DIR = ROOT / "memory" / "candidates"
CANON_DIR = ROOT / "memory" / "canon"
PROJECTS_ROOT = Path(os.environ.get("JMEM_PROJECTS_ROOT", HOME / "projects")).expanduser()

PROJECT_DOC_NAMES = {
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "PROGRESS.md",
    "HEARTBEAT.md",
    "USER.md",
    "MEMORY.md",
}
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
PROFILE_TERMS = {
    "background", "profile", "john", "career", "experience", "style", "preferences",
    "cares", "goals", "vp", "google", "uber", "youtube", "cisco",
}
INDEX_MAX_AGE_SECONDS = 60 * 60
GRANOLA_API_BASE = "https://public-api.granola.ai/v1"
GRANOLA_CACHE_DIR = ROOT / "memory" / "granola"
GRANOLA_STATE = Path(
    os.environ.get("JMEM_GRANOLA_STATE", HOME / ".claude/skills/granola-to-drive/state.json")
).expanduser()


@dataclass
class RetrievalTrace:
    cwd: str
    prompt: str
    query_terms: list[str]
    project_terms: list[str]
    fts_query: str
    candidates_seen: int
    matches: list[tuple[float, sqlite3.Row]]
    memory_matches: list[tuple[float, sqlite3.Row]] = field(default_factory=list)


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
        CREATE TABLE IF NOT EXISTS memory_items (
          id INTEGER PRIMARY KEY,
          text TEXT NOT NULL,
          kind TEXT NOT NULL,
          scope TEXT NOT NULL,
          status TEXT NOT NULL,
          confidence REAL NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          evidence_count INTEGER NOT NULL,
          source_hash TEXT NOT NULL UNIQUE,
          updated_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
        USING fts5(text, kind, scope, content='memory_items', content_rowid='id');
        CREATE TABLE IF NOT EXISTS memory_evidence (
          id INTEGER PRIMARY KEY,
          memory_id INTEGER NOT NULL,
          source_type TEXT NOT NULL,
          source_path TEXT NOT NULL,
          source_excerpt TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(memory_id) REFERENCES memory_items(id)
        );
        CREATE TABLE IF NOT EXISTS memory_events (
          id INTEGER PRIMARY KEY,
          memory_id INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          note TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(memory_id) REFERENCES memory_items(id)
        );
        CREATE INDEX IF NOT EXISTS idx_memory_items_scope_status
          ON memory_items(scope, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_memory_items_kind
          ON memory_items(kind);
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
        (CANON_DIR, "jmem_memory"),
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


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def get_metadata(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)", (key, value))


def normalize_memory_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" -\t")
    text = re.sub(r"^\[[ xX]\]\s*", "", text)
    return text[:500]


def memory_hash(kind: str, scope: str, text: str) -> str:
    normalized = normalize_memory_text(text).lower()
    return hashlib.sha256(f"{kind}\n{scope}\n{normalized}".encode("utf-8")).hexdigest()


def scope_for_cwd(cwd: str) -> str:
    try:
        rel = Path(cwd).expanduser().resolve().relative_to(PROJECTS_ROOT)
    except Exception:
        return "global"
    if not rel.parts:
        return "global"
    return f"project:{rel.parts[0]}"


def parse_candidate_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(errors="ignore")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    out: dict[str, str] = {}
    for raw in match.group(1).splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def classify_memory(text: str) -> tuple[str, float]:
    line = normalize_memory_text(text)
    lower = line.lower()
    if not line or line.endswith("?"):
        return "skip", 0.0
    if lower.startswith("#") or lower.startswith("##"):
        return "skip", 0.0
    if re.match(r"^(what|why|how|when|where|can i|could i|should i|do i)\b", lower):
        return "skip", 0.0
    if re.match(r"^(i('|’)m|i am|let me|first, let me|you('|’)re right|this is important)\b", lower):
        return "skip", 0.0
    if re.search(r"\b(let me (check|see|inspect|investigate|fix)|i('|’)ll|i will)\b", lower):
        return "skip", 0.0
    if re.search(r"\b(correction|actually|instead of|not .* but|wrong|mistake)\b", lower):
        return "correction", 0.86
    if re.search(r"\b(preference|prefers|i prefer|john prefers|always|never|do not|don't|doesn't want|wants)\b", lower):
        return "preference", 0.86
    if re.search(r"\b(decision|decided|we chose|we are going to|go ahead|approved|ship|commit and push)\b", lower):
        return "decision", 0.82
    if re.search(r"\b(critical|important|must|non-negotiable|source of truth|first-class)\b", lower):
        return "project_fact", 0.80
    if re.search(r"\b(jmem|codex|claude code|granola|hook|userpromptsubmit|sqlite|launchagent|mcp)\b", lower):
        return "project_fact", 0.74
    if re.search(r"\b(todo|next|follow[- ]?up|should|need to|needs to)\b", lower):
        return "todo", 0.64
    return "general", 0.50


def active_candidate_paths(limit: int = 0) -> list[Path]:
    paths: list[Path] = []
    for path in candidate_paths(include_reviewed=False):
        meta = parse_candidate_frontmatter(path)
        if meta.get("status", "candidate") != "candidate":
            continue
        paths.append(path)
        if limit and len(paths) >= limit:
            break
    return paths


def upsert_memory_item(
    conn: sqlite3.Connection,
    *,
    text: str,
    kind: str,
    scope: str,
    status: str,
    confidence: float,
    source_type: str,
    source_path: str,
) -> tuple[str, int | None]:
    normalized = normalize_memory_text(text)
    if not normalized:
        return "skipped", None
    now = now_utc()
    source_hash = memory_hash(kind, scope, normalized)
    existing = conn.execute(
        "SELECT * FROM memory_items WHERE source_hash = ?",
        (source_hash,),
    ).fetchone()
    if existing:
        memory_id = int(existing["id"])
        new_confidence = min(0.95, max(float(existing["confidence"]), confidence) + 0.03)
        conn.execute(
            """
            UPDATE memory_items
            SET confidence = ?,
                last_seen_at = ?,
                evidence_count = evidence_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (new_confidence, now, now, memory_id),
        )
        conn.execute(
            "DELETE FROM memory_items_fts WHERE rowid = ?",
            (memory_id,),
        )
        conn.execute(
            "INSERT INTO memory_items_fts(rowid, text, kind, scope) VALUES (?, ?, ?, ?)",
            (memory_id, normalized, kind, scope),
        )
        event_type = "reinforced"
        result = "updated"
    else:
        cur = conn.execute(
            """
            INSERT INTO memory_items(
              text, kind, scope, status, confidence, first_seen_at, last_seen_at,
              evidence_count, source_hash, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (normalized, kind, scope, status, confidence, now, now, source_hash, now),
        )
        memory_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO memory_items_fts(rowid, text, kind, scope) VALUES (?, ?, ?, ?)",
            (memory_id, normalized, kind, scope),
        )
        event_type = "created"
        result = "inserted"
    conn.execute(
        """
        INSERT INTO memory_evidence(memory_id, source_type, source_path, source_excerpt, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (memory_id, source_type, source_path, normalized[:900], now),
    )
    conn.execute(
        "INSERT INTO memory_events(memory_id, event_type, note, created_at) VALUES (?, ?, ?, ?)",
        (memory_id, event_type, f"{source_type}:{source_path}", now),
    )
    return result, memory_id


def render_soft_memory_view(conn: sqlite3.Connection) -> Path:
    CANON_DIR.mkdir(parents=True, exist_ok=True)
    path = CANON_DIR / "soft.md"
    rows = conn.execute(
        """
        SELECT kind, scope, text, status, confidence, evidence_count, updated_at
        FROM memory_items
        WHERE status IN ('soft', 'canon')
        ORDER BY scope, kind, confidence DESC, updated_at DESC
        LIMIT 500
        """
    ).fetchall()
    lines = [
        "# Soft Memory",
        "",
        "Generated from SQLite memory_items. Do not edit by hand.",
        "",
    ]
    current = ""
    for row in rows:
        heading = f"{row['scope']} / {row['kind']}"
        if heading != current:
            if current:
                lines.append("")
            lines.extend([f"## {heading}", ""])
            current = heading
        lines.append(
            f"- {row['text']} "
            f"(status={row['status']}, confidence={float(row['confidence']):.2f}, evidence={row['evidence_count']})"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def retrieve_memory_items(cwd: str, prompt: str, limit: int = 4) -> list[tuple[float, sqlite3.Row]]:
    conn = connect()
    init_db(conn)
    q_terms = tokens(prompt)
    p_scope = scope_for_cwd(cwd)
    terms = list(dict.fromkeys(q_terms + project_terms(cwd)))
    if not terms:
        return []
    rows: list[sqlite3.Row] = []
    query = fts_query(terms)
    if query:
        try:
            rows.extend(
                conn.execute(
                    """
                    SELECT m.*, bm25(memory_items_fts) AS rank
                    FROM memory_items_fts
                    JOIN memory_items m ON m.id = memory_items_fts.rowid
                    WHERE memory_items_fts MATCH ?
                      AND m.status IN ('soft', 'canon')
                      AND m.confidence >= 0.70
                    ORDER BY rank
                    LIMIT 40
                    """,
                    (query,),
                ).fetchall()
            )
        except sqlite3.OperationalError:
            pass
    rows.extend(
        conn.execute(
            """
            SELECT *, -10.0 AS rank
            FROM memory_items
            WHERE status IN ('soft', 'canon')
              AND confidence >= 0.78
              AND scope IN (?, 'global')
            ORDER BY updated_at DESC
            LIMIT 15
            """,
            (p_scope,),
        ).fetchall()
    )
    scored: list[tuple[float, sqlite3.Row]] = []
    seen: set[int] = set()
    for row in rows:
        row_id = int(row["id"])
        if row_id in seen:
            continue
        seen.add(row_id)
        haystack = f"{row['text']} {row['kind']} {row['scope']}".lower()
        scope = str(row["scope"])
        scope_terms = [t for t in re.split(r"[:/_-]", scope.lower()) if t]
        if scope not in {p_scope, "global"} and not any(term in q_terms for term in scope_terms):
            continue
        score = float(row["confidence"]) * 5.0 + min(int(row["evidence_count"]), 6) * 0.35
        if row["scope"] == p_scope:
            score += 4.0
        elif row["scope"] == "global":
            score += 1.0
        for term in q_terms:
            if term in haystack:
                score += 2.2
        for term in project_terms(cwd):
            if term in haystack:
                score += 1.4
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:limit]


def retrieve_with_trace(cwd: str, prompt: str, limit: int = 8) -> RetrievalTrace:
    ensure_index()
    conn = connect()
    init_db(conn)
    q_terms = tokens(prompt)
    p_terms = project_terms(cwd)
    terms = list(dict.fromkeys(q_terms + p_terms))
    if not terms:
        return RetrievalTrace(cwd, prompt, q_terms, p_terms, "", 0, [])

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

    if PROFILE_TERMS.intersection(q_terms):
        rows.extend(
            conn.execute(
                """
                SELECT *, -9.0 AS rank
                FROM chunks
                WHERE path IN (?, ?)
                ORDER BY chunk_index
                LIMIT 8
                """,
                (str(PROJECTS_ROOT / "USER.md"), str(PROJECTS_ROOT / "MEMORY.md")),
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
        if PROFILE_TERMS.intersection(q_terms):
            filename = Path(str(row["path"])).name
            if filename == "USER.md":
                score += 14.0
            elif filename == "MEMORY.md":
                score += 5.0
        age_days = max((time.time() - float(row["mtime"])) / 86400, 0)
        score += max(0, 3.0 - min(age_days / 30.0, 3.0))
        scored.append((score, row))

    candidates_seen = len(scored)
    scored.sort(key=lambda item: item[0], reverse=True)
    unique: list[tuple[float, sqlite3.Row]] = []
    seen_paths: set[str] = set()
    for score, row in scored:
        if score <= 0:
            continue
        if row["path"] in seen_paths:
            continue
        seen_paths.add(row["path"])
        unique.append((score, row))
        if len(unique) >= limit:
            break
    memory_matches = retrieve_memory_items(cwd, prompt, limit=4)
    return RetrievalTrace(cwd, prompt, q_terms, p_terms, query, candidates_seen, unique, memory_matches)


def retrieve(cwd: str, prompt: str, limit: int = 8) -> list[sqlite3.Row]:
    return [row for _, row in retrieve_with_trace(cwd, prompt, limit).matches]


def build_context(cwd: str, prompt: str, max_chars: int = 6000) -> str:
    if prompt.strip().lower() in TRIVIAL_PROMPTS:
        return ""
    trace = retrieve_with_trace(cwd, prompt)
    if not trace.matches and not trace.memory_matches:
        return ""

    terms = list(dict.fromkeys(trace.query_terms + trace.project_terms))
    lines = [
        "# jmem Ambient Context",
        "",
        "Use this as local memory hints, not guaranteed truth. Verify live repo/service state for volatile facts.",
        "",
    ]
    used = 0
    for _, row in trace.memory_matches:
        item = (
            f"## Memory: {row['kind']} ({row['scope']})\n"
            f"- source: jmem_memory\n"
            f"- status: {row['status']}\n"
            f"- confidence: {float(row['confidence']):.2f}\n"
            f"- evidence_count: {row['evidence_count']}\n"
            f"- memory: {row['text']}\n"
        )
        if used + len(item) > max_chars:
            break
        lines.append(item)
        used += len(item)
    for _, row in trace.matches:
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


def explain_context(cwd: str, prompt: str, max_chars: int = 6000) -> str:
    trace = retrieve_with_trace(cwd, prompt)
    rows = [row for _, row in trace.matches]
    memory_rows = [row for _, row in trace.memory_matches]
    context = build_context(cwd, prompt, max_chars)
    terms = list(dict.fromkeys(trace.query_terms + trace.project_terms))
    lines = [
        "# jmem Retrieval Explain",
        "",
        f"cwd: {cwd}",
        f"query_terms: {', '.join(trace.query_terms) or '(none)'}",
        f"project_terms: {', '.join(trace.project_terms) or '(none)'}",
        f"fts_query: {trace.fts_query or '(none)'}",
        f"candidates_seen: {trace.candidates_seen}",
        f"memory_selected: {len(memory_rows)}",
        f"selected: {len(rows)}",
        "",
    ]
    for idx, (score, row) in enumerate(trace.memory_matches, start=1):
        lines.extend([
            f"## Memory {idx}. {row['kind']} ({row['scope']})",
            f"- score: {score:.2f}",
            f"- status: {row['status']}",
            f"- confidence: {float(row['confidence']):.2f}",
            f"- evidence_count: {row['evidence_count']}",
            f"- text: {row['text']}",
            "",
        ])
    for idx, (score, row) in enumerate(trace.matches, start=1):
        lines.extend([
            f"## {idx}. {row['title']}",
            f"- score: {score:.2f}",
            f"- source: {row['source']}",
            f"- path: {row['path']}",
            f"- chunk_index: {row['chunk_index']}",
            f"- snippet: {snippet(row['content'], terms)}",
            "",
        ])
    if context:
        lines.extend(["# Context Packet", "", context])
    return "\n".join(lines).strip()


def cmd_context(args: argparse.Namespace) -> int:
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read()
    if args.explain:
        context = explain_context(args.cwd, prompt or "", args.max_chars)
    else:
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
    memory_rows = conn.execute(
        "SELECT status, kind, COUNT(*) count FROM memory_items GROUP BY status, kind ORDER BY status, kind"
    ).fetchall()
    last = conn.execute("SELECT value FROM metadata WHERE key = 'last_indexed_at'").fetchone()
    consolidated = conn.execute("SELECT value FROM metadata WHERE key = 'last_consolidated_at'").fetchone()
    print(f"db={DB_PATH}")
    print(f"last_indexed_at={last['value'] if last else 'unknown'}")
    print(f"last_consolidated_at={consolidated['value'] if consolidated else 'unknown'}")
    print(f"files={row['files']} chunks={row['chunks']}")
    for source_row in sources:
        print(f"{source_row['source']}: files={source_row['files']} chunks={source_row['chunks']}")
    if memory_rows:
        print("memory_items=" + ", ".join(
            f"{r['status']}/{r['kind']}:{r['count']}" for r in memory_rows
        ))
    return 0


def read_hook_logs(limit: int = 20) -> list[dict]:
    if not LOG_PATH.exists():
        return []
    records: list[dict] = []
    try:
        lines = LOG_PATH.read_text(errors="ignore").splitlines()
    except Exception:
        return []
    for line in lines[-max(limit * 3, limit):]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records[-limit:]


def hook_command(path: Path, mode: str) -> str:
    return f"{path} {mode}"


def config_has_command(path: Path, command: str) -> bool:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return False
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return False
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in entry.get("hooks", []):
                if isinstance(hook, dict) and hook.get("command") == command:
                    return True
    return False


def launchagent_loaded(label: str) -> bool:
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def cmd_doctor(_: argparse.Namespace) -> int:
    conn = connect()
    init_db(conn)
    last = conn.execute("SELECT value FROM metadata WHERE key = 'last_indexed_at'").fetchone()
    counts = conn.execute(
        "SELECT COUNT(DISTINCT path) files, COUNT(*) chunks FROM chunks"
    ).fetchone()
    memory_counts = conn.execute(
        "SELECT status, kind, COUNT(*) count FROM memory_items GROUP BY status, kind ORDER BY status, kind"
    ).fetchall()
    last_consolidated = conn.execute("SELECT value FROM metadata WHERE key = 'last_consolidated_at'").fetchone()
    source_rows = conn.execute(
        "SELECT source, COUNT(DISTINCT path) files FROM chunks GROUP BY source ORDER BY source"
    ).fetchall()
    codex_hook = hook_command(ROOT / "bin/jmem-codex-hook", "user-prompt")
    codex_stop = hook_command(ROOT / "bin/jmem-codex-hook", "stop")
    claude_hook = hook_command(ROOT / "bin/jmem-claude-hook", "user-prompt")
    claude_stop = hook_command(ROOT / "bin/jmem-claude-hook", "stop")
    logs = read_hook_logs(10)
    injected = [r for r in logs if int(r.get("injected_chars") or 0) > 0]
    candidates = candidate_paths()
    canon_files = sorted(CANON_DIR.glob("*.md")) if CANON_DIR.exists() else []

    print("jmem doctor")
    print(f"root={ROOT}")
    print(f"db={DB_PATH} exists={DB_PATH.exists()}")
    print(f"last_indexed_at={last['value'] if last else 'unknown'}")
    print(f"last_consolidated_at={last_consolidated['value'] if last_consolidated else 'unknown'}")
    print(f"files={counts['files']} chunks={counts['chunks']}")
    print("sources=" + ", ".join(f"{r['source']}:{r['files']}" for r in source_rows))
    print(
        "memory_items="
        + (
            ", ".join(f"{r['status']}/{r['kind']}:{r['count']}" for r in memory_counts)
            if memory_counts else "none"
        )
    )
    print(f"codex_user_prompt_hook={config_has_command(HOME / '.codex/hooks.json', codex_hook)}")
    print(f"codex_stop_hook={config_has_command(HOME / '.codex/hooks.json', codex_stop)}")
    print(f"claude_user_prompt_hook={config_has_command(HOME / '.claude/settings.json', claude_hook)}")
    print(f"claude_stop_hook={config_has_command(HOME / '.claude/settings.json', claude_stop)}")
    print(f"granola_token_configured={granola_api_token() is not None}")
    print(f"granola_cache_files={len(list(GRANOLA_CACHE_DIR.glob('*.md'))) if GRANOLA_CACHE_DIR.exists() else 0}")
    print(f"granola_launchagent_file={(HOME / 'Library/LaunchAgents/com.jmem.granola-sync.plist').exists()}")
    print(f"granola_launchagent_loaded={launchagent_loaded('com.jmem.granola-sync')}")
    print(f"consolidate_launchagent_file={(HOME / 'Library/LaunchAgents/com.jmem.consolidate.plist').exists()}")
    print(f"consolidate_launchagent_loaded={launchagent_loaded('com.jmem.consolidate')}")
    print(f"hook_log={LOG_PATH} exists={LOG_PATH.exists()}")
    print(f"recent_hook_events={len(logs)} recent_injections={len(injected)}")
    print(f"candidate_files={len(candidates)}")
    print(f"canon_files={len(canon_files)}")
    if logs:
        print("recent_hooks:")
        for record in logs[-5:]:
            print(
                "- "
                f"ts={record.get('ts')} "
                f"event={record.get('event')} "
                f"cwd={record.get('cwd')} "
                f"injected_chars={record.get('injected_chars')} "
                f"sources={','.join(record.get('top_sources') or [])}"
            )
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    records = read_hook_logs(args.limit)
    if args.json:
        print(json.dumps(records, indent=2))
        return 0
    for record in records:
        print(f"{record.get('ts')} | {record.get('event')} | injected={record.get('injected_chars')}")
        print(f"cwd: {record.get('cwd')}")
        print(f"prompt: {record.get('prompt_prefix')}")
        sources = record.get("top_sources") or []
        paths = record.get("top_paths") or []
        print(f"sources: {', '.join(sources) or '(none)'}")
        for path in paths[: args.paths]:
            print(f"- {path}")
        if record.get("candidate_path"):
            print(f"candidate: {record.get('candidate_path')}")
        print()
    return 0


def slugify(text: str, fallback: str = "session") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:60].strip("-") or fallback)


def read_transcript_text(path: str, max_chars: int = 40_000) -> str:
    if not path:
        return ""
    transcript = Path(path).expanduser()
    if not transcript.exists() or transcript.stat().st_size > 20_000_000:
        return ""
    chunks: list[str] = []
    try:
        for line in transcript.read_text(errors="ignore").splitlines()[-800:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                if line.strip():
                    chunks.append(line.strip())
                continue
            text = ""
            if isinstance(item, dict):
                for key in ("text", "content", "message", "prompt", "response"):
                    value = item.get(key)
                    if isinstance(value, str):
                        text = value
                        break
                if not text and isinstance(item.get("message"), dict):
                    value = item["message"].get("content")
                    if isinstance(value, str):
                        text = value
                    elif isinstance(value, list):
                        text = " ".join(
                            part.get("text", "")
                            for part in value
                            if isinstance(part, dict) and isinstance(part.get("text"), str)
                        )
            if text.strip():
                chunks.append(text.strip())
    except Exception:
        return ""
    joined = "\n".join(chunks)
    return joined[-max_chars:]


def extract_candidate_lines(text: str, limit: int = 12) -> list[str]:
    candidates: list[str] = []
    patterns = re.compile(
        r"\b(remember|preference|prefers|decision|decided|next|follow[- ]?up|todo|should|always|never|important|critical)\b",
        re.IGNORECASE,
    )
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" -\t")
        if len(line) < 12 or len(line) > 520:
            continue
        if patterns.search(line):
            candidates.append(line)
        if len(candidates) >= limit:
            break
    if not candidates:
        compact = re.sub(r"\s+", " ", text).strip()
        if compact:
            candidates.append(compact[:480])
    return list(dict.fromkeys(candidates))[:limit]


def write_candidate(
    text: str,
    cwd: str,
    source: str = "manual",
    session_id: str = "",
    transcript_path: str = "",
) -> Path | None:
    lines = extract_candidate_lines(text)
    if not lines:
        return None
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now().astimezone()
    slug_source = session_id or Path(cwd).name or source
    path = CANDIDATES_DIR / f"{now.strftime('%Y%m%d-%H%M%S')}-{slugify(slug_source)}.md"
    body = [
        "---",
        "status: candidate",
        f"created_at: {now.isoformat(timespec='seconds')}",
        f"source: {source}",
        f"cwd: {cwd}",
        f"session_id: {session_id}",
        f"transcript_path: {transcript_path}",
        "---",
        "",
        "# Memory Candidate",
        "",
        "Audit trail for automatic consolidation. Manual review is optional.",
        "",
        "## Candidate memories",
        "",
    ]
    body.extend(f"- [ ] {line}" for line in lines)
    body.extend([
        "",
        "## Source excerpt",
        "",
        "```text",
        text.strip()[:4000],
        "```",
        "",
    ])
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(body), encoding="utf-8")
    tmp.replace(path)
    return path


def candidate_paths(include_reviewed: bool = False) -> list[Path]:
    if not CANDIDATES_DIR.exists():
        return []
    paths = sorted(CANDIDATES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if include_reviewed:
        for child in ("accepted", "rejected"):
            folder = CANDIDATES_DIR / child
            if folder.exists():
                paths.extend(sorted(folder.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True))
    return paths


def resolve_candidate(identifier: str = "") -> Path | None:
    paths = candidate_paths(include_reviewed=False)
    if not paths:
        return None
    if not identifier:
        return paths[0]
    possible = Path(identifier).expanduser()
    if possible.exists():
        return possible
    if identifier.isdigit():
        index = int(identifier) - 1
        if 0 <= index < len(paths):
            return paths[index]
    for path in paths:
        if path.stem == identifier or path.name == identifier or path.stem.startswith(identifier):
            return path
    return None


def candidate_memory_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(errors="ignore")
    except Exception:
        return []
    lines: list[str] = []
    in_section = False
    for raw in text.splitlines():
        if raw.strip() == "## Candidate memories":
            in_section = True
            continue
        if in_section and raw.startswith("## "):
            break
        if not in_section:
            continue
        match = re.match(r"^-\s+\[[ xX]\]\s+(.+)$", raw.strip())
        if match:
            lines.append(match.group(1).strip())
    return lines


def update_candidate_status(path: Path, status: str, extra: list[str] | None = None) -> None:
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        text = path.read_text(errors="ignore")
    except Exception:
        text = ""
    text = re.sub(r"^status:\s+.*$", f"status: {status}", text, count=1, flags=re.MULTILINE)
    if extra is None:
        extra = []
    note = ["", f"## Review", "", f"- status: {status}", f"- reviewed_at: {now}"]
    note.extend(extra)
    path.write_text(text.rstrip() + "\n" + "\n".join(note) + "\n", encoding="utf-8")


def move_candidate(path: Path, folder_name: str) -> Path:
    target_dir = CANDIDATES_DIR / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    if target.exists():
        target = target_dir / f"{path.stem}-{int(time.time())}{path.suffix}"
    path.replace(target)
    return target


def append_canon(bucket: str, lines: list[str], source_path: Path) -> Path:
    safe_bucket = slugify(bucket, "general")
    CANON_DIR.mkdir(parents=True, exist_ok=True)
    path = CANON_DIR / f"{safe_bucket}.md"
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    existing = path.read_text(errors="ignore") if path.exists() else ""
    body: list[str] = []
    if not existing.strip():
        title = safe_bucket.replace("-", " ").title()
        body.extend([f"# {title}", ""])
    body.extend([
        f"## Accepted {now}",
        "",
        f"source_candidate: {source_path}",
        "",
    ])
    body.extend(f"- {line}" for line in lines)
    body.append("")
    with path.open("a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write("\n".join(body))
    return path


def consolidate_candidate_file(
    conn: sqlite3.Connection,
    path: Path,
    min_confidence: float,
    dry_run: bool,
) -> dict[str, int]:
    meta = parse_candidate_frontmatter(path)
    scope = scope_for_cwd(meta.get("cwd") or "")
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    for line in candidate_memory_lines(path):
        kind, confidence = classify_memory(line)
        if kind == "skip" or confidence < min_confidence:
            counts["skipped"] += 1
            continue
        if dry_run:
            counts["inserted"] += 1
            continue
        result, _ = upsert_memory_item(
            conn,
            text=line,
            kind=kind,
            scope=scope,
            status="soft",
            confidence=confidence,
            source_type=meta.get("source") or "candidate",
            source_path=str(path),
        )
        counts[result] = counts.get(result, 0) + 1
    return counts


def consolidate_candidates(args: argparse.Namespace) -> int:
    conn = connect()
    init_db(conn)
    limit = max(int(getattr(args, "limit", 50) or 0), 0)
    dry_run = bool(getattr(args, "dry_run", False))
    quiet = bool(getattr(args, "quiet", False))
    min_confidence = float(getattr(args, "min_confidence", 0.78))
    paths = active_candidate_paths(limit=limit)
    totals = {
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "accepted_candidates": 0,
        "rejected_candidates": 0,
    }
    for path in paths:
        counts = consolidate_candidate_file(conn, path, min_confidence, dry_run)
        promoted = counts.get("inserted", 0) + counts.get("updated", 0)
        totals["processed"] += 1
        totals["inserted"] += counts.get("inserted", 0)
        totals["updated"] += counts.get("updated", 0)
        totals["skipped"] += counts.get("skipped", 0)
        if not quiet:
            print(
                f"{path.name}: inserted={counts.get('inserted', 0)} "
                f"updated={counts.get('updated', 0)} skipped={counts.get('skipped', 0)}"
            )
        if dry_run:
            continue
        if promoted:
            update_candidate_status(path, "accepted", [f"- consolidated_lines: {promoted}"])
            move_candidate(path, "accepted")
            totals["accepted_candidates"] += 1
        else:
            update_candidate_status(path, "rejected", [f"- reason: no high-confidence memory lines"])
            move_candidate(path, "rejected")
            totals["rejected_candidates"] += 1
    soft_path = ""
    if not dry_run:
        soft_path = str(render_soft_memory_view(conn))
        set_metadata(conn, "last_consolidated_at", now_utc())
        conn.commit()
        if bool(getattr(args, "index", False)):
            index_sources(None)
    if not quiet:
        print(
            "consolidated "
            + " ".join(f"{key}={value}" for key, value in totals.items())
            + (f" soft_view={soft_path}" if soft_path else "")
            + (" dry_run=true" if dry_run else "")
        )
    return 0


def maybe_auto_consolidate(limit: int = 25, debounce_seconds: int = 600) -> None:
    if os.environ.get("JMEM_DISABLE_AUTO_CONSOLIDATE"):
        return
    try:
        conn = connect()
        init_db(conn)
        last = get_metadata(conn, "last_consolidated_at")
        if last:
            last_dt = dt.datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=dt.timezone.utc)
            age = (dt.datetime.now(dt.timezone.utc) - last_dt).total_seconds()
            if age < debounce_seconds:
                return
        args = argparse.Namespace(
            limit=limit,
            dry_run=False,
            quiet=True,
            min_confidence=0.78,
            index=False,
        )
        consolidate_candidates(args)
    except Exception:
        return


def candidate_text_from_event(event: dict) -> tuple[str, str]:
    transcript_path = str(event.get("transcript_path") or event.get("transcriptPath") or "")
    pieces = []
    for key in ("summary", "prompt", "user_prompt", "message", "response"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value.strip())
    transcript_text = read_transcript_text(transcript_path)
    if transcript_text:
        pieces.append(transcript_text)
    return "\n\n".join(pieces), transcript_path


def cmd_candidates_add(args: argparse.Namespace) -> int:
    text = args.text
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read()
    path = write_candidate(
        text or "",
        args.cwd,
        source=args.source,
        session_id=args.session_id,
        transcript_path=args.transcript_path,
    )
    if not path:
        print("no candidate written")
        return 1
    print(path)
    return 0


def cmd_candidates_list(args: argparse.Namespace) -> int:
    paths = candidate_paths(include_reviewed=args.all)
    for path in paths[: args.limit]:
        rel = path.relative_to(CANDIDATES_DIR) if path.is_relative_to(CANDIDATES_DIR) else path
        print(f"{paths.index(path) + 1}. {path.stem} | {rel}")
    return 0


def cmd_candidates_show(args: argparse.Namespace) -> int:
    path = resolve_candidate(args.identifier)
    if not path:
        print("candidate not found", file=sys.stderr)
        return 1
    print(path)
    print()
    print(path.read_text(errors="ignore").rstrip())
    return 0


def cmd_candidates_accept(args: argparse.Namespace) -> int:
    path = resolve_candidate(args.identifier)
    if not path:
        print("candidate not found", file=sys.stderr)
        return 1
    lines = candidate_memory_lines(path)
    if args.line:
        selected: list[str] = []
        for idx in args.line:
            if idx < 1 or idx > len(lines):
                print(f"line index out of range: {idx}", file=sys.stderr)
                return 1
            selected.append(lines[idx - 1])
        lines = selected
    if not lines:
        print("candidate has no memory lines", file=sys.stderr)
        return 1
    moved = move_candidate(path, "accepted")
    canon_path = append_canon(args.bucket, lines, moved)
    conn = connect()
    init_db(conn)
    scope = scope_for_cwd(parse_candidate_frontmatter(moved).get("cwd") or "")
    for line in lines:
        kind, confidence = classify_memory(line)
        if kind == "skip":
            kind, confidence = "general", 0.90
        upsert_memory_item(
            conn,
            text=line,
            kind=kind,
            scope=scope,
            status="canon",
            confidence=max(confidence, 0.90),
            source_type="manual_accept",
            source_path=str(moved),
        )
    render_soft_memory_view(conn)
    set_metadata(conn, "last_consolidated_at", now_utc())
    conn.commit()
    update_candidate_status(moved, "accepted", [f"- canon_path: {canon_path}", f"- accepted_lines: {len(lines)}"])
    print(f"accepted={moved}")
    print(f"canon={canon_path}")
    return 0


def cmd_candidates_reject(args: argparse.Namespace) -> int:
    path = resolve_candidate(args.identifier)
    if not path:
        print("candidate not found", file=sys.stderr)
        return 1
    extra = [f"- reason: {args.reason}"] if args.reason else []
    update_candidate_status(path, "rejected", extra)
    moved = move_candidate(path, "rejected")
    print(f"rejected={moved}")
    return 0


def cmd_candidates_prune(args: argparse.Namespace) -> int:
    cutoff = time.time() - (args.days * 86400)
    pruned = 0
    for path in candidate_paths(include_reviewed=False):
        if path.stat().st_mtime >= cutoff:
            continue
        if args.dry_run:
            print(path)
            continue
        update_candidate_status(path, "pruned", [f"- reason: older than {args.days} days"])
        moved = move_candidate(path, "rejected")
        print(f"pruned={moved}")
        pruned += 1
    if not args.dry_run:
        print(f"pruned_count={pruned}")
    return 0


def log_hook(event: dict, injected: str, trace: RetrievalTrace | None = None, candidate_path: str = "") -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    top_rows = [row for _, row in trace.matches] if trace else []
    memory_rows = [row for _, row in trace.memory_matches] if trace else []
    top_sources = list(dict.fromkeys(
        [str(row["source"]) for row in top_rows]
        + (["jmem_memory"] if memory_rows else [])
    ))
    top_paths = [str(row["path"]) for row in top_rows[:5]]
    record = {
        "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": event.get("hook_event_name"),
        "session_id": event.get("session_id"),
        "turn_id": event.get("turn_id"),
        "cwd": event.get("cwd"),
        "prompt_prefix": (event.get("prompt") or "")[:160],
        "injected_chars": len(injected),
        "top_sources": top_sources,
        "top_paths": top_paths,
        "memory_items": len(memory_rows),
        "granola_used": any(source == "granola_api" for source in top_sources),
        "candidate_path": candidate_path,
    }
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def hook_main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}

    if mode == "stop" or event.get("hook_event_name") == "Stop":
        event.setdefault("hook_event_name", "Stop")
        event.setdefault("cwd", event.get("cwd") or os.getcwd())
        text, transcript_path = candidate_text_from_event(event)
        candidate = write_candidate(
            text,
            event.get("cwd") or os.getcwd(),
            source="codex_stop_hook",
            session_id=str(event.get("session_id") or ""),
            transcript_path=transcript_path,
        )
        if candidate:
            maybe_auto_consolidate()
        log_hook(event, "", None, str(candidate) if candidate else "")
        return 0

    if mode != "user-prompt" and event.get("hook_event_name") != "UserPromptSubmit":
        return 0

    prompt = event.get("prompt") or ""
    cwd = event.get("cwd") or os.getcwd()
    trace = retrieve_with_trace(cwd, prompt) if prompt.strip().lower() not in TRIVIAL_PROMPTS else None
    context = build_context(cwd, prompt)
    log_hook(event, context, trace)
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
    if mode == "stop" or hook_event == "Stop":
        event.setdefault("hook_event_name", "Stop")
        event.setdefault("cwd", event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        text, transcript_path = candidate_text_from_event(event)
        candidate = write_candidate(
            text,
            event.get("cwd") or os.getcwd(),
            source="claude_stop_hook",
            session_id=str(event.get("session_id") or ""),
            transcript_path=transcript_path,
        )
        if candidate:
            maybe_auto_consolidate()
        log_hook(event, "", None, str(candidate) if candidate else "")
        return 0

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
    trace = retrieve_with_trace(cwd, prompt) if prompt.strip().lower() not in TRIVIAL_PROMPTS else None
    context = build_context(cwd, prompt)
    event.setdefault("hook_event_name", hook_event or "UserPromptSubmit")
    event.setdefault("prompt", prompt)
    event.setdefault("cwd", cwd)
    log_hook(event, context, trace)
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
    p_context.add_argument("--explain", action="store_true", help="Show retrieval terms, selected matches, and context")
    p_context.set_defaults(func=cmd_context)

    p_consolidate = sub.add_parser("consolidate", help="Promote high-confidence candidates into SQLite memory")
    p_consolidate.add_argument("--limit", type=int, default=50, help="Maximum active candidates to process")
    p_consolidate.add_argument("--min-confidence", type=float, default=0.78)
    p_consolidate.add_argument("--dry-run", action="store_true")
    p_consolidate.add_argument("--quiet", action="store_true")
    p_consolidate.add_argument("--index", action="store_true", help="Re-index source files after writing the Markdown view")
    p_consolidate.set_defaults(func=consolidate_candidates)

    p_doctor = sub.add_parser("doctor", help="Check jmem hook, index, Granola, and log health")
    p_doctor.set_defaults(func=cmd_doctor)

    p_trace = sub.add_parser("trace", help="Show recent hook retrieval activity")
    p_trace.add_argument("--limit", type=int, default=10)
    p_trace.add_argument("--paths", type=int, default=3, help="Number of matched paths to show per hook event")
    p_trace.add_argument("--json", action="store_true", help="Emit raw hook log records as JSON")
    p_trace.set_defaults(func=cmd_trace)

    p_candidates = sub.add_parser("candidates", help="Create or list memory candidate audit files")
    candidates_sub = p_candidates.add_subparsers(dest="candidate_cmd", required=True)

    p_candidates_add = candidates_sub.add_parser("add", help="Write a memory candidate audit file from text")
    p_candidates_add.add_argument("--cwd", default=os.getcwd())
    p_candidates_add.add_argument("--source", default="manual")
    p_candidates_add.add_argument("--session-id", default="")
    p_candidates_add.add_argument("--transcript-path", default="")
    p_candidates_add.add_argument("--text", default="")
    p_candidates_add.set_defaults(func=cmd_candidates_add)

    p_candidates_list = candidates_sub.add_parser("list", help="List recent memory candidates")
    p_candidates_list.add_argument("--limit", type=int, default=10)
    p_candidates_list.add_argument("--all", action="store_true", help="Include accepted and rejected candidates")
    p_candidates_list.set_defaults(func=cmd_candidates_list)

    p_candidates_show = candidates_sub.add_parser("show", help="Show a candidate by id, path, prefix, or newest")
    p_candidates_show.add_argument("identifier", nargs="?", default="")
    p_candidates_show.set_defaults(func=cmd_candidates_show)

    p_candidates_accept = candidates_sub.add_parser("accept", help="Promote candidate lines into memory/canon")
    p_candidates_accept.add_argument("identifier", nargs="?", default="")
    p_candidates_accept.add_argument("--bucket", default="general", help="Canon bucket filename under memory/canon")
    p_candidates_accept.add_argument("--line", type=int, action="append", help="Accept only this 1-based candidate line; repeatable")
    p_candidates_accept.set_defaults(func=cmd_candidates_accept)

    p_candidates_reject = candidates_sub.add_parser("reject", help="Move a candidate to rejected")
    p_candidates_reject.add_argument("identifier", nargs="?", default="")
    p_candidates_reject.add_argument("--reason", default="")
    p_candidates_reject.set_defaults(func=cmd_candidates_reject)

    p_candidates_prune = candidates_sub.add_parser("prune", help="Reject old unreviewed candidates")
    p_candidates_prune.add_argument("--days", type=int, default=30)
    p_candidates_prune.add_argument("--dry-run", action="store_true")
    p_candidates_prune.set_defaults(func=cmd_candidates_prune)

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
