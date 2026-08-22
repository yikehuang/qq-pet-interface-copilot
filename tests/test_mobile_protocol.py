from __future__ import annotations

import unittest
import hashlib
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qqpet_app.mobile_protocol import (
    MobileProtocolReader,
    MobileProtocolServerError,
    MobileProtocolUnavailable,
    FRIDA_TOOLS_VERSION,
    discover_adb_path,
    frida_architecture,
    select_adb_serial,
)
from qqpet_app.proto import field_bytes, field_fixed32


class MobileProtocolTests(unittest.TestCase):
    def test_persistent_connection_reuses_existing_agent(self) -> None:
        reader = MobileProtocolReader(".")

        class Exports:
            ping_calls = 0

            @classmethod
            def ping(cls):
                cls.ping_calls += 1

            @staticmethod
            def java_ready():
                return True

        class Script:
            exports_sync = Exports()

        reader._script = Script()
        reader._session = object()
        reader._attached_pid = 123
        reader._attach_count = 1

        first = reader.ensure_persistent_connection()
        second = reader.ensure_persistent_connection()

        self.assertEqual(Exports.ping_calls, 2)
        self.assertEqual(first["attach_count"], 1)
        self.assertEqual(second["reconnect_count"], 0)
        self.assertEqual(second["pid"], 123)

    def test_logged_out_runtime_is_rejected_even_when_uin_is_cached(self) -> None:
        reader = MobileProtocolReader(".")
        reader._connect = lambda: None  # type: ignore[method-assign]

        class Exports:
            @staticmethod
            def get_login_state():
                return {"uin": "123456", "logged_in": False, "source": "runtime.isLogin"}

        class Script:
            exports_sync = Exports()

        reader._script = Script()
        with self.assertRaisesRegex(MobileProtocolUnavailable, "已退出登录"):
            reader.get_self_uin()

    def test_encourage_is_open_on_mobile_one_shot_write_channel(self) -> None:
        self.assertIn(MobileProtocolReader.STORY_ENCOURAGE, MobileProtocolReader.WRITE_ALLOWLIST)
        hook = Path("hooks/qqpet_mobile_read_agent.js").read_text(encoding="utf-8")
        self.assertIn("'OidbSvcTrpcTcp.0x9c44_1': '40004:1'", hook)

    def test_mobile_hook_and_package_include_java_bridge_readiness(self) -> None:
        hook = Path("hooks/qqpet_mobile_read_agent.js").read_text(encoding="utf-8")
        spec = Path("QQPetInterfaceCopilot.spec").read_text(encoding="utf-8")
        self.assertIn("javaReady()", hook)
        self.assertIn("frida_java_fallback", spec)

    def test_missing_java_bridge_is_downloaded_verified_and_cached(self) -> None:
        bridge = b"var bridge={available:true};\n"
        member = f"frida_tools-{FRIDA_TOOLS_VERSION}/frida_tools/bridges/java.js"
        archive_file = io.BytesIO()
        with tarfile.open(fileobj=archive_file, mode="w:gz") as package:
            info = tarfile.TarInfo(member)
            info.size = len(bridge)
            package.addfile(info, io.BytesIO(bridge))
        archive = archive_file.getvalue()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary, patch(
            "qqpet_app.mobile_protocol.FRIDA_JAVA_BRIDGE_SHA256",
            hashlib.sha256(bridge).hexdigest(),
        ), patch(
            "qqpet_app.mobile_protocol.FRIDA_TOOLS_SDIST_SHA256",
            hashlib.sha256(archive).hexdigest(),
        ), patch(
            "qqpet_app.mobile_protocol.urllib.request.urlopen",
            return_value=Response(archive),
        ):
            target = Path(temporary) / "components" / "java.js"
            source = MobileProtocolReader._download_java_bridge(target)
            self.assertEqual(source, bridge.decode("utf-8"))
            self.assertEqual(target.read_bytes(), bridge)

    def test_write_server_error_preserves_numeric_code(self) -> None:
        reader = MobileProtocolReader(".")
        reader._connect = lambda: None  # type: ignore[method-assign]

        class Exports:
            @staticmethod
            def send_oidb_write_once(*_args):
                return {"code": 135061, "message": "你的宠物还未达到该职业参与要求"}

        class Script:
            exports_sync = Exports()

        reader._script = Script()
        with self.assertRaises(MobileProtocolServerError) as raised:
            reader.send_oidb_write_once(*reader.STORY_START, b"")
        self.assertEqual(raised.exception.code, 135061)
        self.assertIn("职业参与要求", str(raised.exception))

    def test_read_server_error_does_not_detach_live_frida_agent(self) -> None:
        reader = MobileProtocolReader(".")
        reader._connect = lambda: None  # type: ignore[method-assign]
        disconnects = []
        reader._disconnect = lambda: disconnects.append(True)  # type: ignore[method-assign]

        class Exports:
            @staticmethod
            def send_oidb_read(*_args):
                return {"code": 14561, "message": "你的宠物还未达到该职业参与要求"}

        class Script:
            exports_sync = Exports()

        reader._script = Script()
        with self.assertRaises(MobileProtocolServerError):
            reader.send_oidb_read(*reader.SCENE_OPTIONS, b"")
        self.assertEqual(disconnects, [])

    def test_empty_read_retries_without_detaching_live_frida_agent(self) -> None:
        reader = MobileProtocolReader(".")
        reader._connect = lambda: None  # type: ignore[method-assign]
        disconnects = []
        reader._disconnect = lambda: disconnects.append(True)  # type: ignore[method-assign]

        class Exports:
            calls = 0

            @classmethod
            def send_oidb_read(cls, *_args):
                cls.calls += 1
                return {"code": 0, "data_hex": ""}

        class Script:
            exports_sync = Exports()

        reader._script = Script()
        with self.assertRaisesRegex(Exception, "手机 QQ 返回空响应"):
            reader.send_oidb_read(*reader.STORY_STATUS, b"")
        self.assertEqual(Exports.calls, 2)
        self.assertEqual(disconnects, [])

    def test_select_adb_serial_prefers_configured_online_device(self) -> None:
        output = "List of devices attached\n127.0.0.1:16384\tdevice\nemulator-5554\tdevice\n"
        self.assertEqual(select_adb_serial(output, "emulator-5554"), "emulator-5554")

    def test_select_adb_serial_falls_back_to_running_mumu_instance(self) -> None:
        output = "List of devices attached\n127.0.0.1:16416\toffline\n127.0.0.1:16384\tdevice\n"
        self.assertEqual(select_adb_serial(output, "127.0.0.1:16416"), "127.0.0.1:16384")

    def test_frida_architecture_uses_kernel_architecture(self) -> None:
        self.assertEqual(frida_architecture("aarch64\n"), "arm64")
        self.assertEqual(frida_architecture("x86_64"), "x86_64")

    def test_frida_launch_timeout_is_accepted_when_server_is_running(self) -> None:
        reader = MobileProtocolReader(".")
        calls: list[tuple[str, ...]] = []

        def fake_adb(*args: str, **_kwargs):
            calls.append(args)
            if "--daemonize" in " ".join(args):
                raise MobileProtocolUnavailable("timed out after 10 seconds")
            return SimpleNamespace(stdout="18284\n", stderr="", returncode=0)

        reader._adb = fake_adb  # type: ignore[method-assign]
        messages: list[str] = []
        with patch("qqpet_app.mobile_protocol.time.sleep", return_value=None):
            pid = reader._start_frida_server(messages.append)

        self.assertEqual(pid, "18284")
        self.assertTrue(any("核验实际运行状态" in message for message in messages))
        launch = calls[0]
        self.assertIn("sh", launch)
        self.assertIn("</dev/null >/dev/null 2>&1 &", launch[-1])

    def test_adb_root_timeout_is_accepted_after_root_identity_check(self) -> None:
        reader = MobileProtocolReader(".")
        calls: list[tuple[str, ...]] = []

        def fake_adb(*args: str, **_kwargs):
            calls.append(args)
            if args == ("root",):
                raise MobileProtocolUnavailable("timed out after 12 seconds")
            stdout = "uid=0(root) gid=0(root)\n" if args == ("shell", "id") else ""
            return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

        reader._adb = fake_adb  # type: ignore[method-assign]
        messages: list[str] = []
        reader._ensure_adb_root(messages.append)

        self.assertIn(("wait-for-device",), calls)
        self.assertIn(("shell", "id"), calls)
        self.assertTrue(any("核验 Root 状态" in message for message in messages))

    def test_discovers_adb_below_custom_mumu12_install_root(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "MuMu12" / "MuMu Player 12" / "nx_main" / "adb.exe"
            adb.parent.mkdir(parents=True)
            adb.touch()
            with patch(
                "qqpet_app.mobile_protocol._mumu_install_locations",
                return_value=[root / "MuMu12"],
            ):
                self.assertEqual(discover_adb_path(root / "project"), adb)

    def test_mobile_state_and_gold_packets_are_decoded(self) -> None:
        display = b"".join(
            field_bytes(index, field_fixed32(3, value))
            for index, value in enumerate((98.0, 100.0, 97.0, 98.8), start=1)
        )
        personal = field_bytes(4, display)
        state = field_bytes(1, field_bytes(5, personal))
        gold = field_bytes(1, field_bytes(5, field_fixed32(3, 2147.0)))

        reader = MobileProtocolReader(".")
        replies = iter((state, gold))
        reader._send_read = lambda _spec, _body: next(replies)  # type: ignore[method-assign]

        values = reader.query_values("pet-id")
        self.assertEqual(values.feel, 98.0)
        self.assertEqual(values.hunger, 100.0)
        self.assertEqual(values.clean, 97.0)
        self.assertAlmostEqual(values.total, 98.8, places=2)
        self.assertEqual(values.gold, 2147.0)


if __name__ == "__main__":
    unittest.main()
