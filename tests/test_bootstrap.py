from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from qqpet_app.bootstrap import (
    OneBotEndpoint,
    RuntimeAsset,
    configure_local_onebot,
    endpoints_from_config,
    ensure_vc_runtime,
    install_napcat_runtime,
    is_managed_runtime,
    login_qrcode_path,
    napcat_config_dir,
    probe_login,
    start_napcat,
)
from qqpet_app.single_instance import SingleInstance


class BootstrapTests(unittest.TestCase):
    def test_reads_only_enabled_loopback_http_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "onebot11_123456.json"
            path.write_text(
                json.dumps(
                    {
                        "network": {
                            "httpServers": [
                                {"enable": True, "host": "127.0.0.1", "port": 6201, "token": "local"},
                                {"enable": True, "host": "0.0.0.0", "port": 6202, "token": "unsafe"},
                                {"enable": False, "host": "127.0.0.1", "port": 6203},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                endpoints_from_config(path),
                (OneBotEndpoint("http://127.0.0.1:6201", "local", "123456", path),),
            )

    def test_configure_adds_random_token_without_replacing_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "onebot11_987654.json"
            path.write_text(
                json.dumps({"musicSignUrl": "kept", "network": {"websocketClients": []}}),
                encoding="utf-8",
            )
            endpoint = configure_local_onebot(path, 6210)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["musicSignUrl"], "kept")
            self.assertEqual(endpoint.url, "http://127.0.0.1:6210")
            self.assertGreater(len(endpoint.token), 20)
            self.assertEqual(saved["network"]["httpServers"][0]["host"], "127.0.0.1")
            self.assertFalse(saved["network"]["httpServers"][0]["enableCors"])

    @mock.patch("qqpet_app.bootstrap.onebot_action")
    def test_probe_requires_real_login_info(self, action):
        action.return_value = {
            "status": "ok",
            "retcode": 0,
            "data": {"user_id": 123456, "nickname": "tester"},
        }
        endpoint = OneBotEndpoint("http://127.0.0.1:6201", "secret")
        session = probe_login(endpoint)
        self.assertIsNotNone(session)
        self.assertEqual(session.uin, "123456")
        self.assertEqual(session.nickname, "tester")

    def test_single_instance_releases_its_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            first = SingleInstance(Path(directory) / "console.lock")
            self.assertTrue(first.acquire())
            first.release()
            second = SingleInstance(Path(directory) / "console.lock")
            self.assertTrue(second.acquire())
            second.release()

    @unittest.skipUnless(os.name == "nt", "Windows runtime package")
    def test_installs_complete_runtime_without_desktop_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "runtime.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("node.exe", b"node")
                output.writestr("index.js", b"entry")
                output.writestr("wrapper.node", b"wrapper")
                output.writestr("napcat/napcat.mjs", b"napcat")
                output.writestr("napcat/config/napcat.json", "{}")
            asset = RuntimeAsset(
                "https://example.invalid/runtime.zip",
                "NapCat.Shell.Windows.Node.zip",
                "v-test",
                "0" * 64,
            )
            root = install_napcat_runtime(archive, asset, base / "installed")
            self.assertTrue((root / "node.exe").is_file())
            self.assertEqual(napcat_config_dir(root), root / "napcat" / "config")
            metadata = json.loads((root / ".qqpet-runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["source"], "NapNeko/NapCatQQ")
            self.assertTrue(is_managed_runtime(root))

    @unittest.skipUnless(os.name == "nt", "Windows runtime package")
    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../outside.txt", "unsafe")
            asset = RuntimeAsset("", "unsafe.zip", "v-test", "0" * 64)
            with self.assertRaisesRegex(RuntimeError, "不安全路径"):
                install_napcat_runtime(archive, asset, base / "installed")
            self.assertFalse((base / "outside.txt").exists())

    @mock.patch("qqpet_app.bootstrap.subprocess.Popen")
    @mock.patch("qqpet_app.bootstrap.find_napcat_root")
    def test_managed_runtime_passes_quick_login_flag(self, find_root, popen):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "node.exe").write_bytes(b"node")
            (root / "index.js").write_text("", encoding="utf-8")
            (root / "napcat" / "config").mkdir(parents=True)
            find_root.return_value = root
            start_napcat("123456")
            command = popen.call_args.args[0]
            self.assertEqual(command[-2:], ["-q", "123456"])
            self.assertEqual(popen.call_args.kwargs["cwd"], root)

    @mock.patch("qqpet_app.bootstrap.find_napcat_root")
    def test_qrcode_is_returned_only_after_png_is_complete(self, find_root):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "node.exe").write_bytes(b"node")
            (root / "index.js").write_text("", encoding="utf-8")
            (root / "napcat" / "config").mkdir(parents=True)
            cache = root / "napcat" / "cache"
            cache.mkdir()
            qr = cache / "qrcode.png"
            find_root.return_value = root

            qr.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 512)
            self.assertIsNone(login_qrcode_path())

            qr.write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"x" * 512 + b"\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            self.assertEqual(login_qrcode_path(), qr)

    @mock.patch("qqpet_app.bootstrap.vc_runtime_installed", return_value=True)
    def test_vc_runtime_install_is_skipped_when_already_available(self, installed):
        messages = []
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(ensure_vc_runtime(Path(directory), messages.append))
        installed.assert_called_once_with()
        self.assertTrue(any("已就绪" in message for message in messages))

    @unittest.skipUnless(os.name == "nt", "Windows VC++ runtime installer")
    @mock.patch("qqpet_app.bootstrap.subprocess.run")
    @mock.patch("qqpet_app.bootstrap._verify_microsoft_signature")
    @mock.patch("qqpet_app.bootstrap.urllib.request.urlretrieve")
    @mock.patch("qqpet_app.bootstrap.vc_runtime_installed", side_effect=[False, True])
    def test_vc_runtime_is_downloaded_verified_and_installed(
        self, installed, download, verify, run
    ):
        run.return_value = mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(ensure_vc_runtime(root))
            installer = root / "vc_redist.x64.exe"
            download.assert_called_once()
            verify.assert_called_once_with(installer)
            command = run.call_args.args[0]
            self.assertEqual(command[0], str(installer))
            self.assertIn("/quiet", command)
            self.assertIn("/norestart", command)
        self.assertEqual(installed.call_count, 2)


if __name__ == "__main__":
    unittest.main()
