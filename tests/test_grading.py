import json
import unittest
from unittest import mock

import tests  # noqa: F401  (env isolation)

from jmem import judge


class GradeInjectionsTest(unittest.TestCase):
    def _mock_run(self, payload):
        return mock.patch(
            "jmem.judge.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout=json.dumps(payload), stderr=""),
        )

    def test_grades_aligned_by_event(self):
        payload = [
            {"event": 0, "grade": "relevant"},
            {"event": 1, "grade": "noise"},
            {"event": 7, "grade": "relevant"},  # out of range: ignored
        ]
        events = [
            {"prompt": "deploy question", "items": ["deploy fact"]},
            {"prompt": "lunch", "items": ["deploy fact"]},
        ]
        with self._mock_run(payload):
            grades = judge.grade_injections(events, {"judge": {}})
        self.assertEqual(grades, ["relevant", "noise"])

    def test_invalid_grade_stays_skipped(self):
        with self._mock_run([{"event": 0, "grade": "amazing"}]):
            grades = judge.grade_injections(
                [{"prompt": "p", "items": ["i"]}], {"judge": {}}
            )
        self.assertEqual(grades, ["skipped"])

    def test_judge_failure_returns_none(self):
        with mock.patch(
            "jmem.judge.subprocess.run",
            return_value=mock.Mock(returncode=1, stdout="", stderr=""),
        ):
            self.assertIsNone(
                judge.grade_injections([{"prompt": "p", "items": ["i"]}], {"judge": {}})
            )

    def test_empty_events_no_subprocess(self):
        with mock.patch("jmem.judge.subprocess.run") as run:
            self.assertEqual(judge.grade_injections([], {"judge": {}}), [])
            run.assert_not_called()


class GradeGapsTest(unittest.TestCase):
    def test_verdicts_aligned(self):
        payload = [{"event": 0, "verdict": "miss"}, {"event": 1, "verdict": "ok"}]
        events = [
            {"prompt": "granola decision?", "candidates": ["granola stays first-class"]},
            {"prompt": "unrelated", "candidates": ["nothing useful"]},
        ]
        with mock.patch(
            "jmem.judge.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout=json.dumps(payload), stderr=""),
        ):
            verdicts = judge.grade_gaps(events, {"judge": {}})
        self.assertEqual(verdicts, ["miss", "ok"])


if __name__ == "__main__":
    unittest.main()
