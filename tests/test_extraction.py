import json
import unittest
from unittest import mock

import tests  # noqa: F401  (env isolation)

from jmem import judge
from jmem.core import extract_candidate_lines


class ExtractCandidateLinesTest(unittest.TestCase):
    def test_no_verbatim_fallback(self):
        # Text with no keyword matches must produce NO candidates —
        # previously the first 480 chars were stored verbatim (plan 1.2.1).
        text = "Here is a long transcript about nothing in particular.\n" * 20
        self.assertEqual(extract_candidate_lines(text), [])

    def test_keyword_lines_still_extracted(self):
        text = "random chatter\nJohn prefers tabs over spaces in this repo\nmore chatter"
        lines = extract_candidate_lines(text)
        self.assertEqual(lines, ["John prefers tabs over spaces in this repo"])


class TemplateMarkerTest(unittest.TestCase):
    def test_rejects_prompt_templates(self):
        for text in [
            "ABSOLUTE RULE: never write to the ledger directly",
            "you MUST respond with valid JSON only",
            "Fill in the {ticker} placeholder before sending",
            "You are a memory extraction judge for a system",
            "<local-command-caveat>ignore this</local-command-caveat>",
        ]:
            self.assertTrue(judge.looks_like_template(text), text)

    def test_accepts_durable_facts(self):
        for text in [
            "John prefers vanilla HTML + Firebase over React for new web apps.",
            "The jmem holdout skips injection for 1 in 4 sessions.",
        ]:
            self.assertFalse(judge.looks_like_template(text), text)


class CleanFactTest(unittest.TestCase):
    def test_caps_and_validates(self):
        self.assertIsNone(judge.clean_fact({"text": "x" * 400}))
        self.assertIsNone(judge.clean_fact({"text": ""}))
        fact = judge.clean_fact(
            {"text": "John uses AgentMail for outbound email.", "kind": "bogus", "confidence": 2.0}
        )
        self.assertEqual(fact["kind"], "general")
        self.assertEqual(fact["confidence"], 0.95)


class ParseJsonArrayTest(unittest.TestCase):
    def test_plain_and_fenced(self):
        expected = [{"a": 1}]
        self.assertEqual(judge._parse_json_array('[{"a": 1}]'), expected)
        self.assertEqual(judge._parse_json_array('```json\n[{"a": 1}]\n```'), expected)
        self.assertEqual(judge._parse_json_array('Sure! [{"a": 1}] done'), expected)
        self.assertEqual(judge._parse_json_array("no json here"), [])


class JudgeParsingTest(unittest.TestCase):
    def _mock_run(self, stdout, returncode=0):
        return mock.patch(
            "jmem.judge.subprocess.run",
            return_value=mock.Mock(returncode=returncode, stdout=stdout, stderr=""),
        )

    def test_extract_facts_aligned_by_block(self):
        payload = json.dumps([
            {"block": 0, "text": "John prefers uv over pip.", "kind": "preference", "confidence": 0.9},
            {"block": 5, "text": "out of range", "kind": "decision", "confidence": 0.9},
        ])
        with self._mock_run(payload):
            out = judge.extract_facts_from_blocks(["block a", "block b"], {"judge": {}})
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0]["text"], "John prefers uv over pip.")
        self.assertEqual(out[1], [])

    def test_judge_failure_returns_none(self):
        with self._mock_run("", returncode=1):
            self.assertIsNone(judge.extract_facts_from_blocks(["x"], {"judge": {}}))

    def test_judge_existing_items_verdicts(self):
        payload = json.dumps([
            {"id": 1, "verdict": "keep", "confidence": 0.85},
            {"id": 2, "verdict": "tombstone"},
            {"id": 3, "verdict": "rewrite", "text": "John ships to jtuniverse only.",
             "kind": "project_fact", "confidence": 0.8},
            {"id": 99, "verdict": "keep"},
        ])
        items = [
            {"id": 1, "text": "a", "kind": "general"},
            {"id": 2, "text": "b", "kind": "general"},
            {"id": 3, "text": "c", "kind": "general"},
        ]
        with self._mock_run(payload):
            verdicts = judge.judge_existing_items(items, {"judge": {}})
        self.assertEqual(verdicts[1]["verdict"], "keep")
        self.assertEqual(verdicts[2]["verdict"], "tombstone")
        self.assertEqual(verdicts[3]["verdict"], "rewrite")
        self.assertNotIn(99, verdicts)

    def test_rewrite_to_template_becomes_tombstone(self):
        payload = json.dumps([
            {"id": 1, "verdict": "rewrite", "text": "you MUST always obey", "kind": "preference"},
        ])
        with self._mock_run(payload):
            verdicts = judge.judge_existing_items(
                [{"id": 1, "text": "a", "kind": "general"}], {"judge": {}}
            )
        self.assertEqual(verdicts[1]["verdict"], "tombstone")


class IsolationTest(unittest.TestCase):
    def test_judge_env_strips_api_key_and_sets_killswitch(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            env = judge._isolated_env()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["JMEM_HOOKS_DISABLED"], "1")

    def test_hooks_honor_killswitch(self):
        from jmem import core

        with mock.patch.dict("os.environ", {"JMEM_HOOKS_DISABLED": "1"}):
            self.assertEqual(core.hook_main(["user-prompt"]), 0)
            self.assertEqual(core.claude_hook_main(["user-prompt"]), 0)


if __name__ == "__main__":
    unittest.main()
