import sqlite3
import unittest

import tests  # noqa: F401  (env isolation)

from jmem import core
from jmem.core import (
    RetrievalTrace,
    is_trivial_prompt,
    read_session_state,
    select_packet,
    render_packet,
    session_is_holdout,
    write_session_state,
)


def make_memory_rows(specs):
    """Real sqlite3.Row objects for memory_items-shaped data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE m (id INTEGER, text TEXT, kind TEXT, scope TEXT,"
        " status TEXT, confidence REAL, evidence_count INTEGER)"
    )
    for spec in specs:
        conn.execute(
            "INSERT INTO m VALUES (?,?,?,?,?,?,?)",
            (spec["id"], spec["text"], spec.get("kind", "preference"),
             spec.get("scope", "global"), "soft", spec.get("confidence", 0.9),
             spec.get("evidence", 3)),
        )
    return conn.execute("SELECT * FROM m").fetchall()


def make_chunk_rows(specs):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE c (id INTEGER, source TEXT, path TEXT, title TEXT,"
        " mtime REAL, sha256 TEXT, chunk_index INTEGER, content TEXT)"
    )
    for spec in specs:
        conn.execute(
            "INSERT INTO c VALUES (?,?,?,?,?,?,?,?)",
            (spec["id"], spec.get("source", "project_doc"),
             spec.get("path", "/tmp/doc.md"), spec.get("title", "Doc"),
             0.0, "x", 0, spec.get("content", "content")),
        )
    return conn.execute("SELECT * FROM c").fetchall()


def trace_with(memory=(), chunks=(), q_terms=("deploy", "firebase")):
    return RetrievalTrace(
        cwd="/tmp", prompt="how do we deploy firebase", query_terms=list(q_terms),
        project_terms=[], fts_query="", candidates_seen=len(chunks),
        matches=list(chunks), memory_matches=list(memory),
    )


class TrivialPromptTest(unittest.TestCase):
    def test_trivial_variants(self):
        for prompt in ["ok", "  yes ", "/compact", "do it", "go ahead", ""]:
            self.assertTrue(is_trivial_prompt(prompt), repr(prompt))

    def test_real_prompts_pass(self):
        self.assertFalse(is_trivial_prompt("why did the morning brief heartbeat fail?"))


class HoldoutTest(unittest.TestCase):
    def test_deterministic_and_roughly_one_in_four(self):
        ids = [f"session-{i}" for i in range(400)]
        first = [session_is_holdout(s) for s in ids]
        second = [session_is_holdout(s) for s in ids]
        self.assertEqual(first, second)
        rate = sum(first) / len(first)
        self.assertGreater(rate, 0.15)
        self.assertLess(rate, 0.35)

    def test_no_session_id_never_holdout(self):
        self.assertFalse(session_is_holdout(""))


class SessionStateTest(unittest.TestCase):
    def test_roundtrip(self):
        write_session_state("s1", {"injected": ["m:1"], "turns": 2})
        state = read_session_state("s1")
        self.assertEqual(state["injected"], ["m:1"])
        self.assertEqual(state["turns"], 2)

    def test_missing_is_fresh(self):
        state = read_session_state("nope")
        self.assertEqual(state, {"injected": [], "turns": 0})


class SelectPacketTest(unittest.TestCase):
    def test_chunk_threshold_gates_recency_only(self):
        chunks = make_chunk_rows([{"id": 1, "content": "deploy firebase now"}])
        trace = trace_with(chunks=[(3.0, chunks[0])])  # recency-only score
        sel = select_packet(trace, session_id="")
        self.assertEqual(sel["chunks"], [])

    def test_strong_chunk_passes(self):
        chunks = make_chunk_rows([{"id": 1, "content": "deploy firebase now"}])
        trace = trace_with(chunks=[(14.0, chunks[0])])
        sel = select_packet(trace, session_id="")
        self.assertEqual(len(sel["chunks"]), 1)
        self.assertTrue(sel["strong"])

    def test_delta_suppresses_already_injected(self):
        memory = make_memory_rows([{"id": 7, "text": "John prefers firebase deploys"}])
        chunks = make_chunk_rows([{"id": 9, "content": "deploy firebase runbook"}])
        write_session_state("s-delta", {"injected": ["m:7", "c:9"], "turns": 1})
        trace = trace_with(memory=[(12.0, memory[0])], chunks=[(14.0, chunks[0])])
        sel = select_packet(trace, session_id="s-delta")
        self.assertEqual(sel["memory"], [])
        self.assertEqual(sel["chunks"], [])
        context, injected = render_packet(trace, sel)
        self.assertEqual(context, "")
        self.assertEqual(injected, [])

    def test_later_turn_requires_term_overlap_for_memory(self):
        memory = make_memory_rows([
            {"id": 1, "text": "totally unrelated fact about lunch"},
            {"id": 2, "text": "the firebase deploy target is jtuniverse"},
        ])
        write_session_state("s-turn2", {"injected": [], "turns": 3})
        trace = trace_with(memory=[(11.0, memory[0]), (11.0, memory[1])])
        sel = select_packet(trace, session_id="s-turn2")
        kept_ids = [row["id"] for _, row in sel["memory"]]
        self.assertEqual(kept_ids, [2])

    def test_first_turn_allows_scope_memory_without_terms(self):
        memory = make_memory_rows([{"id": 1, "text": "unrelated ambient project fact"}])
        trace = trace_with(memory=[(11.0, memory[0])])
        sel = select_packet(trace, session_id="s-fresh-turn1")
        self.assertEqual(len(sel["memory"]), 1)

    def test_weak_matches_shrink_packet(self):
        chunks = make_chunk_rows(
            [{"id": i, "content": f"deploy firebase doc {i}", "path": f"/tmp/d{i}.md"}
             for i in range(6)]
        )
        trace = trace_with(chunks=[(7.0, c) for c in chunks])
        sel = select_packet(trace, session_id="")
        self.assertFalse(sel["strong"])
        self.assertLessEqual(len(sel["chunks"]), 3)
        context, injected = render_packet(trace, sel)
        self.assertLessEqual(len(context), sel["max_chars"])
        self.assertTrue(all(i["id"].startswith("c:") for i in injected))

    def test_render_reports_injected_ids_and_scores(self):
        memory = make_memory_rows([{"id": 5, "text": "the firebase deploy target is jtuniverse"}])
        trace = trace_with(memory=[(12.5, memory[0])])
        sel = select_packet(trace, session_id="")
        context, injected = render_packet(trace, sel)
        self.assertIn("jmem Ambient Context", context)
        self.assertEqual(injected, [{"id": "m:5", "score": 12.5}])


class EnsureIndexReadOnlyTest(unittest.TestCase):
    def test_missing_db_touches_marker_not_index(self):
        marker = core.ROOT / "index" / "reindex-requested"
        marker.unlink(missing_ok=True)
        if core.DB_PATH.exists():
            core.DB_PATH.unlink()
        core.ensure_index()
        self.assertTrue(marker.exists())
        self.assertFalse(core.DB_PATH.exists())


if __name__ == "__main__":
    unittest.main()
