import tomllib
import unittest
from pathlib import Path
import tempfile

import tests  # noqa: F401  (env isolation)

from jmem.config import CONFIG_TEMPLATE, DEFAULTS, load_config, write_default_config


class ConfigTest(unittest.TestCase):
    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_config(Path(tmp)), DEFAULTS)

    def test_template_is_valid_toml_and_all_comments(self):
        parsed = tomllib.loads(CONFIG_TEMPLATE)
        # Every value is commented out, so parsing yields empty tables →
        # effective config equals DEFAULTS.
        for table in parsed.values():
            self.assertEqual(table, {})

    def test_override_merges_over_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.toml").write_text("[holdout]\nmodulus = 8\n")
            cfg = load_config(root)
            self.assertEqual(cfg["holdout"]["modulus"], 8)
            self.assertEqual(cfg["holdout"]["enabled"], True)
            self.assertEqual(cfg["retrieval"]["chunk_min_score"],
                             DEFAULTS["retrieval"]["chunk_min_score"])

    def test_write_default_config_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNotNone(write_default_config(root))
            (root / "config.toml").write_text("[holdout]\nmodulus = 8\n")
            self.assertIsNone(write_default_config(root))
            self.assertEqual(load_config(root)["holdout"]["modulus"], 8)


if __name__ == "__main__":
    unittest.main()
