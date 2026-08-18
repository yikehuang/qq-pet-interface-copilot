from __future__ import annotations

import unittest
import hashlib
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qqpet_app.mobile_protocol import (
    EmulatorCandidate,
    MobileProtocolReader,
    MobileProtocolServerError,
    MobileProtocolUnavailable,
    FRIDA_TOOLS_VERSION,
    discover_adb_path,
    discover_mumu_serials,
    frida_architecture,
    parse_ldplayer_list2,
    parse_ldplayer_runninglist,
    parse_mumu_cli_serials,
    reader_from_config,
    select_adb_serial,
)
from qqpet_app.proto import field_bytes, field_fixed32


class MobileProtocolTests(unittest.TestCase):
    def test_reader_auto_mode_ignores_saved_device_fields(self) -> None:
        config = {
            "mobile_protocol": {
                "enabled": True,
                "auto_device": True,
                "adb_path": r"E:\\old\\adb.exe",
                "adb_serial": "emulator-5554",
            }
        }
        with patch(
            "qqpet_app.mobile_protocol.discover_adb_path",
            return_value=Path("auto-adb.exe"),
        ) as discover:
            reader = reader_from_config(config, project_root=".")
        discover.assert_called_once_with(Path("."), "")
        self.assertIsNotNone(reader)
        self.assertEqual(reader.adb_serial, "")
        self.assertTrue(reader.automatic_device)

    def test_saved_ldplayer_adb_uses_ldplayer_name(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            adb = root / "adb.exe"
            adb.touch()
            (root / "ldconsole.exe").touch()
            reader = MobileProtocolReader(".", adb_path=adb, adb_serial="emulator-5554")
            self.assertEqual(reader.device_name, "雷电模拟器")

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

    def test_select_adb_serial_keeps_usb_device_support(self) -> None:
        output = "List of devices attached\nR58M123ABC\tdevice\n"
        self.assertEqual(select_adb_serial(output), "R58M123ABC")

    def test_discovered_mumu_instance_is_preferred_in_auto_mode(self) -> None:
        output = "List of devices attached\nR58M123ABC\tdevice\n127.0.0.1:16384\tdevice\n"
        self.assertEqual(
            select_adb_serial(output, discovered=("127.0.0.1:16384",)),
            "127.0.0.1:16384",
        )

    def test_manual_usb_device_remains_higher_priority_than_mumu(self) -> None:
        output = "List of devices attached\nR58M123ABC\tdevice\n127.0.0.1:16384\tdevice\n"
        self.assertEqual(
            select_adb_serial(
                output,
                preferred="R58M123ABC",
                discovered=("127.0.0.1:16384",),
            ),
            "R58M123ABC",
        )

    def test_parse_ldplayer_list2_returns_only_android_ready_instances(self) -> None:
        output = (
            "0,雷电模拟器,4853062,2757694,1,556,33088,1920,1080,280\n"
            "1,停止实例,0,0,0,-1,-1,1920,1080,280\n"
            "2,工作实例,4853064,2757696,1,558,33090,1920,1080,280\n"
        )
        self.assertEqual(
            parse_ldplayer_list2(output),
            ("emulator-5554", "127.0.0.1:5555", "emulator-5558", "127.0.0.1:5559"),
        )

    def test_parse_ldplayer_runninglist_supports_legacy_numeric_output(self) -> None:
        self.assertEqual(
            parse_ldplayer_runninglist("0,雷电模拟器\n"),
            ("emulator-5554", "127.0.0.1:5555"),
        )

    def test_parse_mumu_cli_serials_returns_started_local_instances(self) -> None:
        output = """{
          "0": {"adb_host_ip":"127.0.0.1","adb_port":16384,"is_process_started":true,"is_android_started":true,"error_code":0},
          "1": {"adb_host_ip":"127.0.0.1","adb_port":16416,"is_process_started":true,"is_android_started":false,"error_code":0},
          "2": {"adb_host_ip":"192.168.1.2","adb_port":16448,"is_process_started":true,"is_android_started":true,"error_code":0}
        }"""
        self.assertEqual(parse_mumu_cli_serials(output), ("127.0.0.1:16384",))

    def test_discovers_running_instance_through_mumu_cli(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            nx_main = Path(temporary) / "nx_main"
            nx_main.mkdir()
            adb = nx_main / "adb.exe"
            cli = nx_main / "mumu-cli.exe"
            adb.touch()
            cli.touch()
            result = SimpleNamespace(
                stdout='{"0":{"adb_host_ip":"127.0.0.1","adb_port":16384,'
                '"is_process_started":true,"is_android_started":true,"error_code":0}}'
            )
            with patch("qqpet_app.mobile_protocol.subprocess.run", return_value=result) as run:
                self.assertEqual(discover_mumu_serials(adb), ("127.0.0.1:16384",))
            self.assertEqual(
                run.call_args.args[0],
                [str(cli), "info", "--vmindex", "all"],
            )

    def test_resolve_device_connects_cli_instance_after_stale_default(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            adb = Path(temporary) / "adb.exe"
            adb.touch()
            reader = MobileProtocolReader(
                ".",
                adb_path=adb,
                adb_serial="127.0.0.1:16416",
                automatic_device=True,
            )
            calls: list[list[str]] = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                if command[-1] == "devices":
                    return SimpleNamespace(
                        stdout="List of devices attached\n127.0.0.1:16384\tdevice\n"
                    )
                return SimpleNamespace(stdout="")

            emulator = EmulatorCandidate(
                "mumu", adb, ("127.0.0.1:16384",), ("127.0.0.1:16384",)
            )
            with patch(
                "qqpet_app.mobile_protocol.discover_running_emulators",
                return_value=(emulator,),
            ), patch("qqpet_app.mobile_protocol.subprocess.run", side_effect=fake_run):
                self.assertEqual(reader._resolve_device(), "127.0.0.1:16384")

            discovered_connect = [str(adb), "connect", "127.0.0.1:16384"]
            stale_connect = [str(adb), "connect", "127.0.0.1:16416"]
            device_calls = [index for index, call in enumerate(calls) if call == [str(adb), "devices"]]
            self.assertLess(calls.index(discovered_connect), device_calls[-1])
            self.assertNotIn(stale_connect, calls)

    def test_manual_offline_device_does_not_fall_back_to_emulator(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manual_adb = root / "manual-adb.exe"
            mumu_adb = root / "mumu-adb.exe"
            manual_adb.touch()
            mumu_adb.touch()
            reader = MobileProtocolReader(
                ".", adb_path=manual_adb, adb_serial="R58M-OFFLINE"
            )
            emulator = EmulatorCandidate(
                "mumu", mumu_adb, ("127.0.0.1:16384",), ("127.0.0.1:16384",)
            )

            with patch(
                "qqpet_app.mobile_protocol.discover_running_emulators",
                return_value=(emulator,),
            ) as discover, patch(
                "qqpet_app.mobile_protocol.subprocess.run",
                return_value=SimpleNamespace(stdout="List of devices attached\n"),
            ):
                with self.assertRaisesRegex(
                    MobileProtocolUnavailable, "R58M-OFFLINE.*未连接"
                ):
                    reader._resolve_device()

            discover.assert_not_called()
            self.assertEqual(reader.adb_path, manual_adb)
            self.assertEqual(reader.adb_serial, "R58M-OFFLINE")

    def test_resolve_device_connects_mumu_before_usb_fallback(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            adb = Path(temporary) / "adb.exe"
            adb.touch()
            reader = MobileProtocolReader(".", adb_path=adb, adb_serial="")

            def fake_run(command, **_kwargs):
                if command[-1] == "devices":
                    return SimpleNamespace(
                        stdout=(
                            "List of devices attached\n"
                            "R58M123ABC\tdevice\n"
                            "127.0.0.1:16384\tdevice\n"
                        )
                    )
                return SimpleNamespace(stdout="")

            emulator = EmulatorCandidate(
                "mumu", adb, ("127.0.0.1:16384",), ("127.0.0.1:16384",)
            )
            with patch(
                "qqpet_app.mobile_protocol.discover_running_emulators",
                return_value=(emulator,),
            ), patch("qqpet_app.mobile_protocol.subprocess.run", side_effect=fake_run):
                self.assertEqual(reader._resolve_device(), "127.0.0.1:16384")

    def test_resolve_device_waits_for_mumu_started_after_launcher(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            adb = Path(temporary) / "adb.exe"
            adb.touch()
            reader = MobileProtocolReader(".", adb_path=adb, adb_serial="")
            device_outputs = iter(
                (
                    "List of devices attached\n",
                    "List of devices attached\n",
                    "List of devices attached\n127.0.0.1:16384\tdevice\n",
                )
            )
            emulator = EmulatorCandidate(
                "mumu", adb, ("127.0.0.1:16384",), ("127.0.0.1:16384",)
            )
            discovered = iter(((), (emulator,)))
            clock = iter((0.0, 0.0, 2.0))
            messages: list[str] = []

            def fake_run(command, **_kwargs):
                if command[-1] == "devices":
                    return SimpleNamespace(stdout=next(device_outputs))
                return SimpleNamespace(stdout="")

            with patch(
                "qqpet_app.mobile_protocol.discover_running_emulators",
                side_effect=lambda: next(discovered),
            ), patch(
                "qqpet_app.mobile_protocol.subprocess.run", side_effect=fake_run
            ), patch(
                "qqpet_app.mobile_protocol.time.monotonic",
                side_effect=lambda: next(clock),
            ), patch("qqpet_app.mobile_protocol.time.sleep", return_value=None):
                self.assertEqual(
                    reader._resolve_device(wait_seconds=90, report=messages.append),
                    "127.0.0.1:16384",
                )

            self.assertTrue(any("等待安卓模拟器" in message for message in messages))

    def test_auto_reader_does_not_keep_previous_online_emulator(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous_adb = root / "previous-adb.exe"
            running_adb = root / "running-adb.exe"
            previous_adb.touch()
            running_adb.touch()
            reader = MobileProtocolReader(
                ".",
                adb_path=previous_adb,
                adb_serial="emulator-5554",
                automatic_device=True,
            )
            emulator = EmulatorCandidate(
                "mumu", running_adb, ("127.0.0.1:16384",), ("127.0.0.1:16384",)
            )

            def fake_run(command, **_kwargs):
                if command[0] == str(previous_adb) and command[-1] == "devices":
                    return SimpleNamespace(
                        stdout="List of devices attached\nemulator-5554\tdevice\n"
                    )
                if command[0] == str(running_adb) and command[-1] == "devices":
                    return SimpleNamespace(
                        stdout="List of devices attached\n127.0.0.1:16384\tdevice\n"
                    )
                return SimpleNamespace(stdout="")

            with patch(
                "qqpet_app.mobile_protocol.discover_running_emulators",
                return_value=(emulator,),
            ), patch("qqpet_app.mobile_protocol.subprocess.run", side_effect=fake_run):
                self.assertEqual(reader._resolve_device(), "127.0.0.1:16384")
            self.assertEqual(reader.adb_path, running_adb)
            self.assertEqual(reader.device_name, "MuMu 模拟器")

    def test_manual_ldplayer_adb_prefers_ldplayer_when_both_run(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            ld_adb = root / "ld-adb.exe"
            mumu_adb = root / "mumu-adb.exe"
            ld_adb.touch()
            mumu_adb.touch()
            (root / "ldconsole.exe").touch()
            reader = MobileProtocolReader(".", adb_path=ld_adb, adb_serial="")
            mumu = EmulatorCandidate(
                "mumu", mumu_adb, ("127.0.0.1:16384",), ("127.0.0.1:16384",)
            )
            ldplayer = EmulatorCandidate(
                "ldplayer", ld_adb, ("emulator-5554", "127.0.0.1:5555")
            )

            def fake_run(command, **_kwargs):
                if command[0] == str(ld_adb) and command[-1] == "devices":
                    return SimpleNamespace(
                        stdout="List of devices attached\nemulator-5554\tdevice\n"
                    )
                if command[0] == str(mumu_adb) and command[-1] == "devices":
                    return SimpleNamespace(
                        stdout="List of devices attached\n127.0.0.1:16384\tdevice\n"
                    )
                return SimpleNamespace(stdout="")

            with patch(
                "qqpet_app.mobile_protocol.discover_running_emulators",
                return_value=(mumu, ldplayer),
            ), patch("qqpet_app.mobile_protocol.subprocess.run", side_effect=fake_run):
                self.assertEqual(reader._resolve_device(), "emulator-5554")
            self.assertEqual(reader.device_name, "雷电模拟器")

    def test_resolve_device_switches_to_running_ldplayer_adb(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            mumu_adb = root / "mumu-adb.exe"
            ld_adb = root / "ld-adb.exe"
            mumu_adb.touch()
            ld_adb.touch()
            reader = MobileProtocolReader(
                ".",
                adb_path=mumu_adb,
                adb_serial="127.0.0.1:16416",
                automatic_device=True,
            )
            emulator = EmulatorCandidate(
                "ldplayer", ld_adb, ("emulator-5554", "127.0.0.1:5555")
            )

            def fake_run(command, **_kwargs):
                if command[0] == str(ld_adb) and command[-1] == "devices":
                    return SimpleNamespace(
                        stdout="List of devices attached\nemulator-5554\tdevice\n"
                    )
                return SimpleNamespace(stdout="List of devices attached\n")

            with patch(
                "qqpet_app.mobile_protocol.discover_running_emulators",
                return_value=(emulator,),
            ), patch("qqpet_app.mobile_protocol.subprocess.run", side_effect=fake_run):
                self.assertEqual(reader._resolve_device(), "emulator-5554")

            self.assertEqual(reader.adb_path, ld_adb)
            self.assertEqual(reader.device_name, "雷电模拟器")

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
