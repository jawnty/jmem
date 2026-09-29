import json
import os
import tempfile
import time
import unittest

import tests  # noqa: F401  (env isolation)

from jmem import core
from jmem.core import (
    is_followup_prompt,
    select_packet,
    session_context,
    write_session_state,
)
from tests.test_gating import make_chunk_rows, make_memory_rows, trace_with

SID = "11111111-2222-3333-4444-555555555555"


def write_transcript(entries):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
    return path


def tool_use(path, ts="2026-09-28T18:00:00.000Z"):
    return {
        "type": "assistant", "timestamp": ts,
        "message": {"content": [{"type": "tool_use", "name": "Read",
                                 "input": {"file_path": path}}]},
    }


def compact(ts):
    return {"type": "system", "subtype": "compact_boundary", "timestamp": ts}


class FollowupPromptTest(unittest.TestCase):
    def test_short_followups_gated_after_first_turn(self):
        for prompt in ["no - create a new draft", "show me satya's note",
                       "create a gmail draft with this version"]:
            self.assertTrue(is_followup_prompt(prompt, first_turn=False), prompt)

    def test_first_turn_never_followup(self):
        self.assertFalse(is_followup_prompt("show me satya's note", first_turn=True))

    def test_substantive_prompt_passes(self):
        self.assertFalse(is_followup_prompt(
            "why did the morning brief heartbeat fail to send the granola digest?",
            first_turn=False,
        ))


class SessionContextTest(unittest.TestCase):
    def test_collects_touched_paths(self):
        path = write_transcript([tool_use("/p/a.md"), tool_use("/p/b.md")])
        ctx = session_context(path)
        self.assertEqual(ctx["paths"], {"/p/a.md", "/p/b.md"})
        self.assertIsNone(ctx["compacted_at"])

    def test_compaction_resets_paths(self):
        path = write_transcript([
            tool_use("/p/a.md"),
            compact("2026-09-28T19:00:00.000Z"),
            tool_use("/p/b.md", ts="2026-09-28T19:05:00.000Z"),
        ])
        ctx = session_context(path)
        self.assertEqual(ctx["paths"], {"/p/b.md"})
        self.assertEqual(ctx["compacted_at"], "2026-09-28T19:00:00.000Z")

    def test_missing_transcript_is_empty(self):
        ctx = session_context("/nonexistent/x.jsonl")
        self.assertEqual(ctx["paths"], set())


class SelectExcludesSessionEchoTest(unittest.TestCase):
    def test_skips_chunks_from_touched_paths(self):
        chunks = make_chunk_rows([
            {"id": 1, "content": "deploy firebase", "path": "/p/touched.md"},
            {"id": 2, "content": "deploy firebase", "path": "/p/other.md"},
        ])
        trace = trace_with(chunks=[(14.0, chunks[0]), (14.0, chunks[1])])
        sel = select_packet(trace, session_id="",
                            exclude={"paths": {"/p/touched.md"}, "memory_ids": set()})
        self.assertEqual([r["id"] for _, r in sel["chunks"]], [2])

    def test_skips_own_session_memory(self):
        memory = make_memory_rows([
            {"id": 7, "text": "firebase deploy target is jtuniverse"},
            {"id": 8, "text": "firebase deploy uses hosting dir"},
        ])
        trace = trace_with(memory=[(12.0, memory[0]), (12.0, memory[1])])
        sel = select_packet(trace, session_id="",
                            exclude={"paths": set(), "memory_ids": {7}})
        self.assertEqual([r["id"] for _, r in sel["memory"]], [8])


class OwnSessionMemoryTest(unittest.TestCase):
    def setUp(self):
        core.ensure_index()
        self.conn = core.connect()
        core.init_db(self.conn)
        now = "2026-09-28T19:30:00+00:00"
        for mid, text, h in [(901, "own item", "h901"), (902, "shared item", "h902"),
                             (903, "old own item", "h903")]:
            self.conn.execute(
                "INSERT INTO memory_items (id,text,kind,scope,status,confidence,first_seen_at,"
                "last_seen_at,evidence_count,source_hash,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (mid, text, "general", "global", "soft", 0.9, now, now, 1, h, now),
            )
        cand = core.CANDIDATES_DIR
        ev = [
            (901, f"{cand}/20260928-123000-{SID}.md"),
            (902, f"{cand}/20260928-123000-{SID}.md"),
            (902, f"{cand}/20260927-090000-other-session.md"),
            (903, f"{cand}/20260928-100000-{SID}.md"),
        ]
        for mid, p in ev:
            self.conn.execute(
                "INSERT INTO memory_evidence (memory_id,source_type,source_path,source_excerpt,created_at)"
                " VALUES (?,?,?,?,?)", (mid, "claude_stop_hook", p, "x", now))
        self.conn.commit()

    def tearDown(self):
        self.conn.execute("DELETE FROM memory_evidence WHERE memory_id IN (901,902,903)")
        self.conn.execute("DELETE FROM memory_items WHERE id IN (901,902,903)")
        self.conn.commit()

    def test_only_items_sourced_solely_from_this_session(self):
        ids = core.own_session_memory_ids(self.conn, SID, None)
        self.assertEqual(ids, {901, 903})

    def test_compaction_releases_older_items(self):
        # 903's candidate predates the compaction; its content is no longer
        # verbatim in context, so it may be injected again.
        boundary = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(
            time.mktime(time.strptime("20260928-110000", "%Y%m%d-%H%M%S"))
        )) + ".000Z"
        ids = core.own_session_memory_ids(self.conn, SID, boundary)
        self.assertEqual(ids, {901})


if __name__ == "__main__":
    unittest.main()
