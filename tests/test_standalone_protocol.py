from __future__ import annotations

import base64
import unittest
from unittest.mock import Mock, patch

from qqpet_app.standalone_protocol import (
    StandaloneProtocolReader,
    StandaloneProtocolUnavailable,
    reader_from_config,
)


class StandaloneProtocolTests(unittest.TestCase):
    def test_rejects_non_loopback_endpoint(self) -> None:
        with self.assertRaisesRegex(StandaloneProtocolUnavailable, "本机地址"):
            StandaloneProtocolReader("http://192.168.1.20:17890")

    def test_rejects_desktop_protocol_family(self) -> None:
        reader = StandaloneProtocolReader("http://127.0.0.1:17890")
        with patch.object(
            reader,
            "_request",
            return_value={
                "ok": True,
                "protocol_family": "ntqq",
                "session_state": "online",
                "uin": "123456",
            },
        ):
            with self.assertRaisesRegex(StandaloneProtocolUnavailable, "不是 Android"):
                reader.get_self_uin()

    def test_rejects_obsolete_android_login_backend(self) -> None:
        reader = StandaloneProtocolReader("http://127.0.0.1:17890")
        with patch.object(
            reader,
            "_request",
            return_value={
                "ok": True,
                "protocol_family": "android_qq",
                "login_backend": "mirai_go_legacy",
                "session_state": "offline",
            },
        ):
            with self.assertRaisesRegex(StandaloneProtocolUnavailable, "旧版"):
                reader.health()

    def test_oidb_read_uses_base64_and_requires_online_mobile_session(self) -> None:
        reader = StandaloneProtocolReader("http://127.0.0.1:17890")
        expected = b"server-body"
        request = Mock(
            side_effect=[
                {
                    "ok": True,
                    "protocol_family": "android_qq",
                    "session_state": "online",
                    "uin": "123456",
                },
                {"ok": True, "body_base64": base64.b64encode(expected).decode("ascii")},
            ]
        )
        with patch.object(reader, "_request", request):
            actual = reader.send_oidb_read(*reader.STATE, b"request-body")
        self.assertEqual(actual, expected)
        payload = request.call_args_list[1].args[2]
        self.assertEqual(base64.b64decode(payload["body_base64"]), b"request-body")
        self.assertFalse(payload["write"])

    def test_config_factory_only_selects_standalone_mode(self) -> None:
        config = {
            "connection": {"mode": "standalone_mobile"},
            "standalone_protocol": {
                "enabled": True,
                "endpoint": "http://127.0.0.1:17890",
                "timeout_seconds": 4,
            },
        }
        self.assertIsInstance(reader_from_config(config), StandaloneProtocolReader)
        config["connection"]["mode"] = "legacy_mobile_bridge"
        self.assertIsNone(reader_from_config(config))

    def test_qr_request_stops_when_mobile_backend_reports_it_unavailable(self) -> None:
        reader = StandaloneProtocolReader("http://127.0.0.1:17890")
        with patch.object(
            reader,
            "_request",
            return_value={
                "ok": True,
                "protocol_family": "android_qq",
                "session_state": "offline",
                "login_capabilities": {"qr": False},
                "login_help": "需要新的 Android 登录实现",
            },
        ) as request:
            with self.assertRaisesRegex(StandaloneProtocolUnavailable, "二维码登录当前不可用"):
                reader.request_login_qr()
        request.assert_called_once_with("GET", "/v1/health")


if __name__ == "__main__":
    unittest.main()
