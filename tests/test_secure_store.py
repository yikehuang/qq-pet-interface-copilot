from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from qqpet_app.secure_store import WindowsSessionVault


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
class SecureStoreTests(unittest.TestCase):
    def test_round_trip_is_encrypted_for_current_user(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.dat"
            vault = WindowsSessionVault(path)
            session = {"uin": "123456789", "ticket": "test-secret-ticket"}
            vault.save(session)
            self.assertEqual(vault.load(), session)
            self.assertNotIn(b"test-secret-ticket", path.read_bytes())
            vault.clear()
            self.assertIsNone(vault.load())
