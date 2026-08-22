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
            launcher.save_manual_connection(store, "", "")
            self.assertEqual(store.data["mobile_protocol"]["adb_path"], "")
            self.assertEqual(store.data["mobile_protocol"]["adb_serial"], "")

    def test_manual_connection_rejects_invalid_address(self) -> None:
        class Store:
            data = {"mobile_protocol": {"adb_path": "", "adb_serial": ""}}

            def save(self, value):
                self.data = value

        with self.assertRaisesRegex(ValueError, "格式不正确"):
            launcher.save_manual_connection(Store(), "", "127.0.0.1")

    def test_automatic_session_export_path_is_in_downloads_and_unique(self) -> None:
        first = launcher.automatic_android_session_export_path("QQ-2360091679", now=0)
        self.assertIn("android-sessions", str(first))
        self.assertTrue(first.name.startswith("android-session-2360091679-"))

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

    def test_console_child_can_carry_profile_selection(self) -> None:
        command, environment = launcher.console_process_spec(frozen=False, profile="standalone")
        self.assertEqual(command, [launcher.sys.executable, str(launcher.ROOT / "main.py")])
        self.assertEqual(environment.get("QQPET_PROFILE"), "standalone")

    def test_source_acidify_host_uses_python_module(self) -> None:
        command, environment = launcher.acidify_host_process_spec(frozen=False)
        self.assertEqual(command, [launcher.sys.executable, "-m", "qqpet_app.acidify_host"])
        self.assertNotIn("QQPET_APP_ROOT", environment)

    def test_acidify_host_child_receives_signer_url_only_when_configured(self) -> None:
        _, environment = launcher.acidify_host_process_spec(
            frozen=False, sign_url="http://127.0.0.1:9000/sign"
        )
        self.assertEqual(environment["QQPET_ANDROID_SIGN_URL"], "http://127.0.0.1:9000/sign")

    def test_acidify_host_child_does_not_keep_empty_signer_environment(self) -> None:
        _, environment = launcher.acidify_host_process_spec(frozen=False, sign_url="")
        self.assertNotIn("QQPET_ANDROID_SIGN_URL", environment)

    def test_frozen_acidify_host_uses_independent_child(self) -> None:
        command, environment = launcher.acidify_host_process_spec(frozen=True)
        self.assertEqual(command, [launcher.sys.executable, "--acidify-host"])
        self.assertEqual(environment["PYINSTALLER_RESET_ENVIRONMENT"], "1")


if __name__ == "__main__":
    unittest.main()
