from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qqpet_app.acidify_host import (
    AcidifyHostError,
    AcidifyProtocolService,
    import_android_session,
    sanitize_android_session,
)
from qqpet_app.mobile_protocol import MobileProtocolReader


def valid_session() -> dict:
    return {
        "uin": 123456789,
        "password": "",
        "uid": "u_test",
        "state": {},
        "wloginSigs": {"a2": [1], "d2": [2], "d2Key": [3]},
        "guid": list(range(16)),
        "androidId": "0123456789abcdef",
        "qimei": "qimei-test",
        "deviceName": "Android",
    }


class MemoryVault:
    def __init__(self, value=None):
        self.value = value

    def save(self, value):
        self.value = value

    def load(self):
        return self.value

    def clear(self):
        self.value = None


class FakeBridge:
    def __init__(self, _node, _script):
        self.requests = []

    def call(self, method, **payload):
        self.requests.append((method, payload))
        if method == "init":
            return {"uin": "123456789"}
        if method == "online":
            return {"uin": "123456789", "session_json": json.dumps(valid_session())}
        if method == "oidb":
            return {"body_base64": base64.b64encode(b"ok").decode("ascii")}
        if method == "friends":
            return {"friends": [{"uin": "2", "nickname": "friend"}]}
        return {}

    def close(self):
        return None


class AcidifyHostTests(unittest.TestCase):
    def test_rejects_password_and_missing_tokens(self) -> None:
        session = valid_session()
        session["password"] = "secret"
        with self.assertRaisesRegex(AcidifyHostError, "密码"):
            sanitize_android_session(session)
        session = valid_session()
        session["wloginSigs"]["d2"] = []
        with self.assertRaisesRegex(AcidifyHostError, "d2"):
            sanitize_android_session(session)

    def test_import_saves_only_known_fields_and_empty_password(self) -> None:
        vault = MemoryVault()
        with TemporaryDirectory() as temporary:
            source = Path(temporary) / "session.json"
            session = valid_session()
            session["unexpected"] = "not persisted"
            source.write_text(json.dumps(session), encoding="utf-8")
            self.assertEqual(import_android_session(source, vault), "123456789")
        self.assertNotIn("unexpected", vault.value)
        self.assertEqual(vault.value["password"], "")

    def test_service_blocks_writes_until_explicitly_enabled(self) -> None:
        service = AcidifyProtocolService(Path("."), MemoryVault(valid_session()))
        service._bridge = FakeBridge(None, None)
        service._state = "online"
        command = next(iter(MobileProtocolReader.WRITE_ALLOWLIST))
        request = {
            "command_name": command[0],
            "command": command[1],
            "sub_command": command[2],
            "body_base64": "",
            "write": True,
        }
        with self.assertRaisesRegex(AcidifyHostError, "尚未启用"):
            service.oidb(request)

    def test_health_never_exposes_session_or_sign_url(self) -> None:
        service = AcidifyProtocolService(
            Path("."), MemoryVault(valid_session()), sign_url="http://secret.local/sign"
        )
        status = service.health()
        rendered = json.dumps(status)
        self.assertNotIn("secret.local", rendered)
        self.assertNotIn("wloginSigs", rendered)
        self.assertEqual(status["signer_state"], "configured")

    def test_normal_close_preserves_encrypted_session(self) -> None:
        vault = MemoryVault(valid_session())
        service = AcidifyProtocolService(Path("."), vault)
        service._bridge = FakeBridge(None, None)
        service._state = "online"
        service.close()
        self.assertIsNotNone(vault.value)
        self.assertEqual(service.health()["session_state"], "offline")


if __name__ == "__main__":
    unittest.main()
