import argparse
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from jmem import core


def _http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO())


class GranolaGoneNoteTest(unittest.TestCase):
    def _run(self, cache, side_effect):
        args = argparse.Namespace(recent=0, limit=0, force=False, verbose=False, index=False)
        with mock.patch.object(core, "GRANOLA_CACHE_DIR", cache), \
             mock.patch.object(core, "granola_api_token", return_value="t"), \
             mock.patch.object(core, "granola_state_note_ids", return_value={"not_x": "T"}), \
             mock.patch.object(core, "granola_get_json", side_effect=side_effect) as get, \
             mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            core.sync_granola_notes(args)
        return out.getvalue(), get.call_count

    def test_404_is_remembered_and_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            out, calls = self._run(cache, _http_error(404))
            self.assertIn("failed=0", out)
            self.assertTrue((cache / "not_x.gone").exists())
            out, calls = self._run(cache, _http_error(404))
            self.assertEqual(calls, 0)
            self.assertIn("skipped=1", out)

    def test_other_http_errors_still_fail_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            out, _ = self._run(cache, _http_error(500))
            self.assertIn("failed=1", out)
            self.assertFalse((cache / "not_x.gone").exists())


if __name__ == "__main__":
    unittest.main()
