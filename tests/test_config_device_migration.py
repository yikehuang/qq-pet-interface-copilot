from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qqpet_app.config import ConfigStore, DEFAULT_CONFIG


class DeviceConfigMigrationTests(unittest.TestCase):
    def _load_mobile(self, mobile: dict) -> dict:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            config = {
                **DEFAULT_CONFIG,
                "mobile_protocol": {**DEFAULT_CONFIG["mobile_protocol"], **mobile},
            }
            config["mobile_protocol"].pop("auto_device", None)
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            return ConfigStore(path).data["mobile_protocol"]

    def test_historical_mumu_default_migrates_to_auto_mode(self) -> None:
        mobile = self._load_mobile({"adb_path": "", "adb_serial": "127.0.0.1:16416"})
        self.assertTrue(mobile["auto_device"])
        self.assertEqual(mobile["adb_path"], "")
        self.assertEqual(mobile["adb_serial"], "")

    def test_old_auto_saved_ldplayer_migrates_to_auto_mode(self) -> None:
        mobile = self._load_mobile(
            {
                "adb_path": r"E:\leidian\LDPlayer14\adb.exe",
                "adb_serial": "emulator-5554",
            }
        )
        self.assertTrue(mobile["auto_device"])
        self.assertEqual(mobile["adb_path"], "")
        self.assertEqual(mobile["adb_serial"], "")

    def test_ldplayer_multi_instance_remains_manual(self) -> None:
        mobile = self._load_mobile(
            {
                "adb_path": r"E:\leidian\LDPlayer14\adb.exe",
                "adb_serial": "emulator-5558",
            }
        )
        self.assertFalse(mobile["auto_device"])
        self.assertEqual(mobile["adb_path"], r"E:\leidian\LDPlayer14\adb.exe")
        self.assertEqual(mobile["adb_serial"], "emulator-5558")

    def test_mumu_multi_instance_remains_manual(self) -> None:
        mobile = self._load_mobile(
            {
                "adb_path": r"D:\MuMuPlayer\nx_main\adb.exe",
                "adb_serial": "127.0.0.1:16416",
            }
        )
        self.assertFalse(mobile["auto_device"])
        self.assertEqual(mobile["adb_path"], r"D:\MuMuPlayer\nx_main\adb.exe")
        self.assertEqual(mobile["adb_serial"], "127.0.0.1:16416")

    def test_custom_tcp_endpoint_remains_manual(self) -> None:
        mobile = self._load_mobile(
            {"adb_path": "", "adb_serial": "192.168.1.20:5555"}
        )
        self.assertFalse(mobile["auto_device"])
        self.assertEqual(mobile["adb_serial"], "192.168.1.20:5555")

    def test_usb_serial_remains_manual(self) -> None:
        mobile = self._load_mobile({"adb_path": "", "adb_serial": "R58M123ABC"})
        self.assertFalse(mobile["auto_device"])
        self.assertEqual(mobile["adb_serial"], "R58M123ABC")


if __name__ == "__main__":
    unittest.main()
