import sqlite3
import unittest
from unittest import mock

import tests  # noqa: F401  (env isolation)

from jmem import brain
from jmem import core


class BrainRenderTest(unittest.TestCase):
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        core.init_db(conn)
        return conn

    def test_renders_items_grouped_and_escaped(self):
        conn = self._conn()
        core.upsert_memory_item(
            conn, text="John prefers <b>plain</b> HTML & Firebase.",
            kind="preference", scope="project:jawnty-me", status="soft",
            confidence=0.9, source_type="test", source_path="/tmp/x",
        )
        core.upsert_memory_item(
            conn, text="Global fact about timezones.", kind="project_fact",
            scope="global", status="soft", confidence=0.8,
            source_type="test", source_path="/tmp/x",
        )
        html_text = brain.render_brain_html(conn)
        self.assertIn("&lt;b&gt;plain&lt;/b&gt;", html_text)   # escaped
        self.assertNotIn("<b>plain</b>", html_text)
        self.assertIn("jawnty-me", html_text)
        self.assertIn("Global", html_text)
        self.assertIn("2</b> memories", html_text)

    def test_tombstoned_items_excluded(self):
        conn = self._conn()
        core.upsert_memory_item(
            conn, text="dead memory", kind="general", scope="global",
            status="tombstoned", confidence=0.9,
            source_type="test", source_path="/tmp/x",
        )
        self.assertNotIn("dead memory", brain.render_brain_html(conn))

    def test_write_brain_view_creates_file(self):
        with mock.patch.object(core, "connect", side_effect=self._conn):
            path = brain.write_brain_view()
        self.assertTrue(path.exists())
        self.assertTrue(path.read_text().startswith("<!doctype html>"))


if __name__ == "__main__":
    unittest.main()
