from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import launcher


class LauncherTests(unittest.TestCase):
    def test_manual_connection_is_saved_and_blank_values_restore_auto_mode(self) -> None:
        class Store:
            data = {"mobile_protocol": {"adb_path": "old", "adb_serial": "old"}}

            def save(self, value):
                self.data = value

        store = Store()
        with TemporaryDirectory() as temporary:
            adb = Path(temporary) / "adb.exe"
            adb.touch()
            launcher.save_manual_connection(store, str(adb), "127.0.0.1:16384")
            self.assertEqual(store.data["mobile_protocol"]["adb_path"], str(adb))
            self.assertEqual(store.data["mobile_protocol"]["adb_serial"], "127.0.0.1:16384")
            self.assertFalse(store.data["mobile_protocol"]["auto_device"])
            launcher.save_manual_connection(store, "", "")
            self.assertEqual(store.data["mobile_protocol"]["adb_path"], "")
            self.assertEqual(store.data["mobile_protocol"]["adb_serial"], "")
            self.assertTrue(store.data["mobile_protocol"]["auto_device"])

    def test_manual_connection_accepts_usb_serial(self) -> None:
        class Store:
            data = {"mobile_protocol": {"adb_path": "", "adb_serial": ""}}

            def save(self, value):
                self.data = value

        store = Store()
        launcher.save_manual_connection(store, "", "R58M123ABC")
        self.assertEqual(store.data["mobile_protocol"]["adb_serial"], "R58M123ABC")
        self.assertFalse(store.data["mobile_protocol"]["auto_device"])

    def test_manual_connection_rejects_whitespace_in_serial(self) -> None:
        class Store:
            data = {"mobile_protocol": {"adb_path": "", "adb_serial": ""}}

            def save(self, value):
                self.data = value

        with self.assertRaisesRegex(ValueError, "不能包含空格"):
            launcher.save_manual_connection(Store(), "", "bad serial")

    def test_frozen_console_child_uses_independent_pyinstaller_environment(self) -> None:
        command, environment = launcher.console_process_spec(frozen=True)
        self.assertEqual(command, [launcher.sys.executable, "--console"])
        self.assertEqual(environment.get("PYINSTALLER_RESET_ENVIRONMENT"), "1")

    def test_source_console_child_runs_main_script(self) -> None:
        command, environment = launcher.console_process_spec(frozen=False)
        self.assertEqual(command, [launcher.sys.executable, str(launcher.ROOT / "main.py")])
        self.assertEqual(
            environment.get("PYINSTALLER_RESET_ENVIRONMENT"),
            launcher.os.environ.get("PYINSTALLER_RESET_ENVIRONMENT"),
        )


if __name__ == "__main__":
    unittest.main()
