from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .client import PetValues, QQFriend, QQPetConnectionError, QQPetError
from .mobile_protocol import MobileProtocolReader
from .proto import field_bytes, field_string, first_bytes, first_float, parse_message


class StandaloneProtocolUnavailable(QQPetConnectionError):
    """The pure-PC Android QQ protocol host is unavailable or incompatible."""


class StandaloneProtocolError(QQPetError):
    """The protocol host returned a structured QQ or transport error."""


class StandaloneProtocolReader:
    """Use a local pure-PC Android QQ session host.

    This adapter deliberately accepts only a host that identifies itself as an
    Android QQ protocol implementation.  A desktop/NTQQ session must not be
    silently reused because the QQ Pet server validates the client family.
    """

    READ_ALLOWLIST = MobileProtocolReader.READ_ALLOWLIST
    WRITE_ALLOWLIST = MobileProtocolReader.WRITE_ALLOWLIST
    STATE = MobileProtocolReader.STATE
    DISPLAY = MobileProtocolReader.DISPLAY

    def __init__(self, endpoint: str, timeout: float = 10) -> None:
        endpoint = endpoint.strip().rstrip("/")
        if not endpoint:
            raise StandaloneProtocolUnavailable("纯电脑协议服务地址为空")
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise StandaloneProtocolUnavailable("纯电脑协议服务地址必须以 http:// 或 https:// 开头")
        host = (parsed.hostname or "").casefold()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise StandaloneProtocolUnavailable("纯电脑协议服务目前只允许连接本机地址")
        self.endpoint = endpoint
        self.timeout = max(1.0, float(timeout))

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.endpoint}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise StandaloneProtocolUnavailable(
                "纯电脑手机协议服务未启动或无法连接；当前不会回退到桌面 QQ"
            ) from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StandaloneProtocolUnavailable("纯电脑协议服务返回了无效数据") from exc
        if not isinstance(result, dict):
            raise StandaloneProtocolUnavailable("纯电脑协议服务返回格式不正确")
        if result.get("ok") is False:
            code = result.get("code", "unknown")
            message = str(result.get("message") or "未知错误")
            raise StandaloneProtocolError(f"手机协议返回错误 {code}：{message}")
        return result

    def health(self) -> dict:
        result = self._request("GET", "/v1/health")
        family = str(result.get("protocol_family") or "").casefold()
        if family not in {"android_qq", "mobile_qq"}:
            raise StandaloneProtocolUnavailable(
                "协议服务不是 Android 手机 QQ 会话，已拒绝发送宠物请求"
            )
        backend = str(result.get("login_backend") or "").casefold()
        if backend and backend != "acidify_android_session":
            raise StandaloneProtocolUnavailable(
                "检测到旧版手机协议核心；它已无法完成当前 Android QQ 登录，已拒绝使用"
            )
        return result

    def get_self_uin(self) -> str:
        status = self.health()
        if str(status.get("session_state") or "").casefold() != "online":
            raise StandaloneProtocolUnavailable("纯电脑手机 QQ 尚未登录，请先导入已授权会话")
        uin = str(status.get("uin") or "")
        if not uin.isdigit():
            raise StandaloneProtocolUnavailable("纯电脑协议服务未返回有效 QQ 账号")
        return uin

    def request_login_qr(self) -> bytes:
        status = self.health()
        capabilities = status.get("login_capabilities")
        if isinstance(capabilities, dict) and capabilities.get("qr") is False:
            help_text = str(status.get("login_help") or "").strip()
            detail = f"：{help_text}" if help_text else ""
            raise StandaloneProtocolUnavailable(f"纯电脑手机版二维码登录当前不可用{detail}")
        result = self._request("POST", "/v1/login/qr", {})
        encoded = str(result.get("image_base64") or "")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise StandaloneProtocolUnavailable("二维码登录接口未返回有效图片") from exc
        if not image:
            raise StandaloneProtocolUnavailable("二维码登录接口返回空图片")
        return image

    def _send(
        self,
        command_name: str,
        command: int,
        sub_command: int,
        body: bytes,
        *,
        write: bool,
    ) -> bytes:
        spec = (command_name, int(command), int(sub_command))
        allowlist = self.WRITE_ALLOWLIST if write else self.READ_ALLOWLIST
        if spec not in allowlist:
            kind = "写入" if write else "只读"
            raise StandaloneProtocolUnavailable(f"{command_name} 未开放纯电脑手机协议{kind}通道")
        self.get_self_uin()
        result = self._request(
            "POST",
            "/v1/oidb",
            {
                "command_name": command_name,
                "command": int(command),
                "sub_command": int(sub_command),
                "body_base64": base64.b64encode(body).decode("ascii"),
                "write": bool(write),
            },
        )
        encoded = str(result.get("body_base64") or "")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise StandaloneProtocolUnavailable(f"{command_name} 响应不是有效封包") from exc
        if not decoded:
            raise StandaloneProtocolUnavailable(f"{command_name} 返回空响应")
        return decoded

    def send_oidb_read(
        self, command_name: str, command: int, sub_command: int, body: bytes
    ) -> bytes:
        return self._send(command_name, command, sub_command, body, write=False)

    def send_oidb_write_once(
        self, command_name: str, command: int, sub_command: int, body: bytes
    ) -> bytes:
        return self._send(command_name, command, sub_command, body, write=True)

    def query_friend_list(self) -> tuple[QQFriend, ...]:
        result = self._request("GET", "/v1/friends")
        rows = result.get("friends") or []
        friends: list[QQFriend] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            uin = str(row.get("uin") or row.get("user_id") or "")
            if not uin.isdigit():
                continue
            friends.append(
                QQFriend(
                    user_id=uin,
                    nickname=str(row.get("nickname") or ""),
                    remark=str(row.get("remark") or ""),
                    category_id=int(row.get("category_id") or 0),
                )
            )
        return tuple(friends)

    @staticmethod
    def _current(root: dict[int, list], field: int) -> float:
        raw = first_bytes(root, field)
        return first_float(parse_message(raw), 3) if raw else 0.0

    def query_values(self, pet_id: str) -> PetValues:
        if not pet_id:
            raise StandaloneProtocolUnavailable("宠物 ID 为空，无法读取状态")
        state_body = self.send_oidb_read(*self.STATE, field_string(1, pet_id))
        pet = parse_message(first_bytes(parse_message(state_body), 1))
        personal = parse_message(first_bytes(pet, 5))
        display_raw = first_bytes(personal, 4)
        if not display_raw:
            raise StandaloneProtocolUnavailable("手机 QQ 状态响应缺少数值字段")
        display = parse_message(display_raw)
        gold_request = field_string(1, pet_id) + field_bytes(2, b"\x06")
        gold_body = self.send_oidb_read(*self.DISPLAY, gold_request)
        gold_root = parse_message(first_bytes(parse_message(gold_body), 1))
        return PetValues(
            feel=self._current(display, 1),
            hunger=self._current(display, 2),
            clean=self._current(display, 3),
            total=self._current(display, 4),
            gold=self._current(gold_root, 5),
        )


def reader_from_config(config: dict, project_root: str | Path | None = None) -> StandaloneProtocolReader | None:
    del project_root
    connection = config.get("connection") or {}
    if str(connection.get("mode") or "legacy_mobile_bridge") != "standalone_mobile":
        return None
    settings = config.get("standalone_protocol") or {}
    if not bool(settings.get("enabled", True)):
        return None
    return StandaloneProtocolReader(
        str(settings.get("endpoint") or "http://127.0.0.1:17890"),
        float(settings.get("timeout_seconds") or 10),
    )
