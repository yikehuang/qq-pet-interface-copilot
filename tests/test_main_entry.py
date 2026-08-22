from __future__ import annotations

import unittest

from qqpet_app.paths import config_path, progress_path


class MainEntryPathTests(unittest.TestCase):
    def test_command_line_defaults_match_legacy_root(self) -> None:
        self.assertTrue(str(config_path()).endswith("config.yaml"))
        self.assertTrue(str(progress_path()).endswith(r"runs\daily_progress.json"))


if __name__ == "__main__":
    unittest.main()
