from __future__ import annotations

import os
import unittest

from qqpet_app.paths import config_path, normalize_profile, progress_path


class PathTests(unittest.TestCase):
    def test_legacy_is_default_profile(self) -> None:
        self.assertEqual(normalize_profile(""), "legacy")
        self.assertTrue(str(config_path()).endswith("config.yaml"))
        self.assertTrue(str(progress_path()).endswith(r"runs\daily_progress.json"))

    def test_standalone_profile_uses_separate_root(self) -> None:
        previous = os.environ.get("QQPET_PROFILE")
        try:
            os.environ["QQPET_PROFILE"] = "standalone"
            self.assertEqual(normalize_profile(""), "standalone")
            self.assertIn(r"profiles\standalone", str(config_path()))
            self.assertIn(r"profiles\standalone", str(progress_path()))
        finally:
            if previous is None:
                os.environ.pop("QQPET_PROFILE", None)
            else:
                os.environ["QQPET_PROFILE"] = previous


if __name__ == "__main__":
    unittest.main()
