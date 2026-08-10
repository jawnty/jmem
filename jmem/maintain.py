"""Background maintenance: the single home for all DB mutation.

`jmem maintain` runs from the com.jmem.maintain LaunchAgent (hourly) and is
the only place indexing, consolidation (including the LLM judge), pruning,
log rotation, session-state cleanup, and backup happen. Hooks never mutate
the DB (IMPROVEMENT-PLAN 1.10). A flock serializes overlapping runs.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import re
import shutil
import sqlite3
import tarfile
import time
from pathlib import Path

from jmem import core
from jmem import judge as judge_mod
from jmem.config import get_config


MAINTAIN_LOCK = core.ROOT / "logs" / "maintain.lock"
REINDEX_MARKER = core.ROOT / "index" / "reindex-requested"
SESSIONS_DIR = core.ROOT / "logs" / "sessions"
BACKUPS_DIR = core.ROOT / "backups"


@contextlib.contextmanager
def maintain_lock():
    MAINTAIN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with MAINTAIN_LOCK.open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def index_if_needed(config: dict) -> str:
    max_age = int(config["maintain"]["index_max_age_seconds"])
    requested = REINDEX_MARKER.exists()
    stale = True
    conn = core.connect()
    core.init_db(conn)
    last = core.get_metadata(conn, "last_indexed_at")
    conn.close()
    if last:
        try:
            last_dt = dt.datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=dt.timezone.utc)
            stale = (dt.datetime.now(dt.timezone.utc) - last_dt).total_seconds() > max_age
        except ValueError:
            pass
    if not (requested or stale):
        return "fresh"
    core.index_sources(None)
    REINDEX_MARKER.unlink(missing_ok=True)
    return "indexed"


def granola_sync(config: dict) -> str:
    if not core.granola_api_token():
        return "no-token"
    args = argparse.Namespace(
        recent=30, limit=0, force=False, sleep=0.22, verbose=False, index=False
    )
    try:
        rc = core.sync_granola_notes(args)
    except Exception as exc:  # network failures must not kill the run
        return f"failed:{exc.__class__.__name__}"
    return "synced" if rc == 0 else f"failed:rc{rc}"


def prune_candidates(config: dict) -> int:
    days = int(config["maintain"]["candidate_prune_days"])
    cutoff = time.time() - days * 86400
    pruned = 0
    for path in core.candidate_paths(include_reviewed=False):
        if path.stat().st_mtime >= cutoff:
            continue
        core.update_candidate_status(path, "pruned", [f"- reason: older than {days} days"])
        core.move_candidate(path, "rejected")
        pruned += 1
    return pruned


def rotate_hook_log(config: dict) -> str:
    max_bytes = int(config["maintain"]["log_rotate_bytes"])
    keep = int(config["maintain"]["log_keep_files"])
    log = core.LOG_PATH
    if not log.exists() or log.stat().st_size < max_bytes:
        return "ok"
    # Fold the file's totals into metadata counters before archiving so
    # `jmem stats` token accounting survives rotation.
    totals = {"events": 0, "ups": 0, "injections": 0, "injected_chars": 0}
    for line in log.read_text(errors="ignore").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        totals["events"] += 1
        if record.get("event") == "UserPromptSubmit":
            totals["ups"] += 1
            chars = int(record.get("injected_chars") or 0)
            if chars > 0:
                totals["injections"] += 1
                totals["injected_chars"] += chars
    conn = core.connect()
    core.init_db(conn)
    for key, value in totals.items():
        current = int(core.get_metadata(conn, f"archived_{key}") or 0)
        core.set_metadata(conn, f"archived_{key}", str(current + value))
    conn.commit()
    conn.close()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log.rename(log.with_name(f"hooks-{stamp}.jsonl"))
    archives = sorted(log.parent.glob("hooks-*.jsonl"))
    for old in archives[:-keep]:
        old.unlink(missing_ok=True)
    return "rotated"


def clean_session_state(config: dict) -> int:
    if not SESSIONS_DIR.exists():
        return 0
    max_age = int(config["maintain"]["session_state_max_age_days"]) * 86400
    cutoff = time.time() - max_age
    removed = 0
    for path in SESSIONS_DIR.glob("*.json"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _rotate(folder: Path, pattern: str, keep: int) -> None:
    snaps = sorted(folder.glob(pattern))
    for old in snaps[:-keep]:
        old.unlink(missing_ok=True)


def run_backup(config: dict, force: bool = False) -> list[str]:
    """Daily DB+canon snapshot, weekly candidates tarball (plan 1.11)."""
    done: list[str] = []
    daily_dir = BACKUPS_DIR / "daily"
    weekly_dir = BACKUPS_DIR / "weekly"
    daily_dir.mkdir(parents=True, exist_ok=True)
    weekly_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    day_stamp = today.strftime("%Y%m%d")
    week_stamp = today.strftime("%G-W%V")

    db_snap = daily_dir / f"jmem-{day_stamp}.sqlite"
    if force or not db_snap.exists():
        if core.DB_PATH.exists():
            src = sqlite3.connect(core.DB_PATH)
            dst = sqlite3.connect(db_snap)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            done.append(f"db={db_snap.name}")
        canon_snap = daily_dir / f"canon-{day_stamp}.tar.gz"
        if core.CANON_DIR.exists() and (force or not canon_snap.exists()):
            with tarfile.open(canon_snap, "w:gz") as tar:
                tar.add(core.CANON_DIR, arcname="canon")
            done.append(f"canon={canon_snap.name}")
    keep_daily = int(config["maintain"]["backup_keep_daily"])
    _rotate(daily_dir, "jmem-*.sqlite", keep_daily)
    _rotate(daily_dir, "canon-*.tar.gz", keep_daily)

    cand_snap = weekly_dir / f"candidates-{week_stamp}.tar.gz"
    if core.CANDIDATES_DIR.exists() and (force or not cand_snap.exists()):
        with tarfile.open(cand_snap, "w:gz") as tar:
            tar.add(core.CANDIDATES_DIR, arcname="candidates")
        done.append(f"candidates={cand_snap.name}")
    _rotate(weekly_dir, "candidates-*.tar.gz", int(config["maintain"]["backup_keep_weekly"]))
    return done


def cmd_backup(args: argparse.Namespace) -> int:
    config = get_config()
    done = run_backup(config, force=True)
    print("backup " + (" ".join(done) if done else "nothing-to-back-up"))
    print(f"backups_dir={BACKUPS_DIR}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot).expanduser()
    if not snapshot.exists():
        print(f"snapshot not found: {snapshot}")
        return 1
    if core.DB_PATH.exists():
        safety = core.DB_PATH.with_suffix(".pre-restore.sqlite")
        shutil.copy2(core.DB_PATH, safety)
        print(f"current db saved to {safety}")
    shutil.copy2(snapshot, core.DB_PATH)
    # Drop stale WAL/SHM so the restored file is authoritative.
    for suffix in ("-wal", "-shm"):
        Path(str(core.DB_PATH) + suffix).unlink(missing_ok=True)
    print(f"restored {core.DB_PATH} from {snapshot}")
    return 0


def cmd_maintain(args: argparse.Namespace) -> int:
    config = get_config()
    started = time.time()
    with maintain_lock() as acquired:
        if not acquired:
            print("maintain: another run holds the lock, skipping")
            return 0
        summary: list[str] = []
        steps = [
            ("granola", lambda: granola_sync(config)),
            ("index", lambda: index_if_needed(config)),
            ("consolidate", lambda: core.run_consolidation(limit=200, use_judge=True)),
            ("prune", lambda: prune_candidates(config)),
            ("rotate_log", lambda: rotate_hook_log(config)),
            ("sessions", lambda: clean_session_state(config)),
            ("backup", lambda: ",".join(run_backup(config)) or "current"),
        ]
        for name, step in steps:
            try:
                summary.append(f"{name}={step()}")
            except Exception as exc:
                summary.append(f"{name}=error:{exc.__class__.__name__}")
        elapsed = time.time() - started
        print(f"maintain {' '.join(str(s) for s in summary)} elapsed={elapsed:.1f}s")
    return 0


def cmd_migrate_store(args: argparse.Namespace) -> int:
    """One-time cleanup of existing memory_items via the LLM judge
    (plan 1.2.5). Snapshot-first is non-optional."""
    config = get_config()
    if getattr(args, "model", ""):
        config = dict(config)
        config["judge"] = {**config["judge"], "model": args.model}
    dry_run = bool(getattr(args, "dry_run", False))
    if not judge_mod.judge_available(config):
        print("migrate-store requires the LLM judge (claude CLI) — aborting")
        return 1
    if not dry_run:
        done = run_backup(config, force=True)
        print("pre-migration backup: " + " ".join(done))
    conn = core.connect()
    core.init_db(conn)
    query = "SELECT id, text, kind, scope FROM memory_items WHERE status = 'soft' ORDER BY id"
    if getattr(args, "limit", 0):
        query += f" LIMIT {int(args.limit)}"
    rows = conn.execute(query).fetchall()
    print(f"judging {len(rows)} soft items (batches of {args.batch_size})")
    counts = {"keep": 0, "rewrite": 0, "tombstone": 0, "merged": 0, "unjudged": 0}
    now = core.now_utc()
    for start in range(0, len(rows), args.batch_size):
        batch = [dict(row) for row in rows[start : start + args.batch_size]]
        verdicts = judge_mod.judge_existing_items(batch, config)
        if verdicts is None:
            counts["unjudged"] += len(batch)
            print(f"  batch {start}: judge failed, left unjudged")
            continue
        for item in batch:
            item_id = int(item["id"])
            verdict = verdicts.get(item_id, {"verdict": "unjudged"})
            action = verdict["verdict"]
            if action == "unjudged":
                counts["unjudged"] += 1
                continue
            if dry_run:
                counts[action] = counts.get(action, 0) + 1
                preview = re.sub(r"\s+", " ", str(item["text"]))[:90]
                rewritten = verdict.get("text", "")
                print(f"    [{item_id}] {action}: {preview}"
                      + (f" -> {rewritten}" if rewritten else ""))
                continue
            if action == "tombstone":
                conn.execute(
                    "UPDATE memory_items SET status='tombstoned', updated_at=? WHERE id=?",
                    (now, item_id),
                )
                conn.execute("DELETE FROM memory_items_fts WHERE rowid=?", (item_id,))
                conn.execute(
                    "INSERT INTO memory_events(memory_id, event_type, note, created_at)"
                    " VALUES (?, 'tombstoned', 'migrate-store: judged not durable', ?)",
                    (item_id, now),
                )
                counts["tombstone"] += 1
            elif action == "rewrite":
                new_text = core.normalize_memory_text(verdict["text"])
                new_kind = verdict["kind"]
                scope_row = conn.execute(
                    "SELECT scope FROM memory_items WHERE id=?", (item_id,)
                ).fetchone()
                scope = str(scope_row["scope"]) if scope_row else "global"
                new_hash = core.memory_hash(new_kind, scope, new_text)
                clash = conn.execute(
                    "SELECT id FROM memory_items WHERE source_hash=? AND id!=?",
                    (new_hash, item_id),
                ).fetchone()
                if clash:
                    keep_id = int(clash["id"])
                    conn.execute(
                        "UPDATE memory_items SET evidence_count = evidence_count + 1,"
                        " last_seen_at=?, updated_at=? WHERE id=?",
                        (now, now, keep_id),
                    )
                    conn.execute(
                        "UPDATE memory_items SET status='tombstoned', updated_at=? WHERE id=?",
                        (now, item_id),
                    )
                    conn.execute("DELETE FROM memory_items_fts WHERE rowid=?", (item_id,))
                    conn.execute(
                        "INSERT INTO memory_events(memory_id, event_type, note, created_at)"
                        " VALUES (?, 'tombstoned', ?, ?)",
                        (item_id, f"migrate-store: merged into {keep_id}", now),
                    )
                    counts["merged"] += 1
                else:
                    conn.execute(
                        "UPDATE memory_items SET text=?, kind=?, confidence=?,"
                        " source_hash=?, updated_at=? WHERE id=?",
                        (new_text, new_kind, verdict["confidence"], new_hash, now, item_id),
                    )
                    conn.execute("DELETE FROM memory_items_fts WHERE rowid=?", (item_id,))
                    scope_val = scope
                    conn.execute(
                        "INSERT INTO memory_items_fts(rowid, text, kind, scope) VALUES (?,?,?,?)",
                        (item_id, new_text, new_kind, scope_val),
                    )
                    conn.execute(
                        "INSERT INTO memory_events(memory_id, event_type, note, created_at)"
                        " VALUES (?, 'rewritten', 'migrate-store: judged and rewritten', ?)",
                        (item_id, now),
                    )
                    counts["rewrite"] += 1
            else:  # keep
                conn.execute(
                    "UPDATE memory_items SET confidence=?, updated_at=? WHERE id=?",
                    (verdict.get("confidence", 0.8), now, item_id),
                )
                counts["keep"] += 1
        if not dry_run:
            conn.commit()
        judged_so_far = min(start + args.batch_size, len(rows))
        print(
            f"  {judged_so_far}/{len(rows)}: "
            + " ".join(f"{k}={v}" for k, v in counts.items())
        )
    if not dry_run:
        core.render_soft_memory_view(conn)
        core.set_metadata(conn, "store_migrated_at", now)
        conn.commit()
    conn.close()
    print(
        "migrate-store "
        + " ".join(f"{k}={v}" for k, v in counts.items())
        + (" dry_run=true" if dry_run else "")
    )
    return 0
