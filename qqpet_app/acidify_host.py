from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import urllib.parse
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .mobile_protocol import MobileProtocolReader
from .secure_store import SessionProtectionError, WindowsSessionVault


class AcidifyHostError(RuntimeError):
    pass


NODE_VERSION = "22.23.2"
NODE_ARCHIVE = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}"
NODE_SHA256 = "1177b4137ba5adaa56354ae40f1080c7450e8ae09cecb47da459d1c52ac99f97"


_SESSION_KEYS = {
    "uin",
    "password",
    "uid",
    "state",
    "wloginSigs",
    "guid",
    "androidId",
    "qimei",
    "deviceName",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def external_api_security(url: str) -> dict[str, Any]:
    """Describe an optional signer without exposing its host, path, or query."""
    value = str(url or "").strip()
    if not value:
        return {"enabled": False, "transport": "none", "security": "not_configured"}
    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").casefold()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme == "https":
        security = "encrypted"
    elif parsed.scheme == "http" and loopback:
        security = "loopback_only"
    else:
        security = "insecure_compatibility"
    return {
        "enabled": True,
        "transport": parsed.scheme or "unknown",
        "security": security,
    }


def sanitize_android_session(value: dict[str, Any]) -> dict[str, Any]:
    """Validate an already-authorized Acidify Android session for DPAPI storage."""
    if not isinstance(value, dict):
        raise AcidifyHostError("会话文件必须是 JSON 对象")
    if str(value.get("password") or ""):
        raise AcidifyHostError("会话文件包含 QQ 密码，已拒绝导入")
    try:
        uin = int(value.get("uin"))
    except (TypeError, ValueError) as exc:
        raise AcidifyHostError("会话文件缺少有效 QQ 账号") from exc
    if uin <= 0:
        raise AcidifyHostError("会话文件缺少有效 QQ 账号")
    sigs = value.get("wloginSigs")
    if not isinstance(sigs, dict):
        raise AcidifyHostError("会话文件缺少 Android 登录令牌")
    for name in ("a2", "d2", "d2Key"):
        if not isinstance(sigs.get(name), list) or not sigs[name]:
            raise AcidifyHostError(f"会话文件缺少 Android 登录令牌 {name}")
    guid = value.get("guid")
    if not isinstance(guid, list) or len(guid) != 16:
        raise AcidifyHostError("会话文件的 Android GUID 无效")
    for name in ("androidId", "qimei"):
        if not str(value.get(name) or "").strip():
            raise AcidifyHostError(f"会话文件缺少 {name}")
    sanitized = {key: value[key] for key in _SESSION_KEYS if key in value}
    sanitized["uin"] = uin
    sanitized["password"] = ""
    return sanitized


def import_android_session(source: str | Path, vault: WindowsSessionVault) -> str:
    try:
        value = json.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcidifyHostError("无法读取 Android 会话 JSON") from exc
    session = sanitize_android_session(value)
    vault.save(session)
    return str(session["uin"])


def find_node_executable(project_root: Path, explicit: str = "") -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(
        (
            project_root / "protocol-host-acidify" / "node.exe",
            project_root / "runtime" / "node.exe",
        )
    )
    discovered = shutil.which("node")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise AcidifyHostError("未找到 Node.js 运行组件，请先安装协议核心运行环境")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_acidify_runtime(
    project_root: Path,
    explicit_node: str = "",
) -> tuple[Path, Path]:
    """Return a verified Node/Acidify runtime, installing it once when absent."""
    source = project_root / "protocol-host-acidify"
    source_bridge = source / "bridge.mjs"
    source_package = source / "package.json"
    source_lock = source / "package-lock.json"
    if not all(path.is_file() for path in (source_bridge, source_package, source_lock)):
        raise AcidifyHostError("安装包缺少 Acidify 协议核心文件")
    try:
        local_node = find_node_executable(project_root, explicit_node)
    except AcidifyHostError:
        local_node = None
    if local_node and (source / "node_modules" / "@acidify" / "core" / "package.json").is_file():
        return local_node, source_bridge

    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    runtime = base / "QQPetInterfaceCopilot" / "runtime" / "acidify-1.6.3"
    node_root = runtime / f"node-v{NODE_VERSION}-win-x64"
    node = node_root / "node.exe"
    npm = node_root / "npm.cmd"
    app = runtime / "app"
    installed_lock = app / ".package-lock.sha256"
    lock_digest = _sha256(source_lock)
    core = app / "node_modules" / "@acidify" / "core" / "package.json"
    if not node.is_file():
        runtime.mkdir(parents=True, exist_ok=True)
        archive = runtime / NODE_ARCHIVE
        if not archive.is_file() or _sha256(archive) != NODE_SHA256:
            temporary = archive.with_suffix(".download")
            urllib.request.urlretrieve(NODE_URL, temporary)
            if _sha256(temporary) != NODE_SHA256:
                temporary.unlink(missing_ok=True)
                raise AcidifyHostError("Node.js 官方运行组件 SHA-256 校验失败")
            temporary.replace(archive)
        with zipfile.ZipFile(archive) as bundle:
            root = runtime.resolve()
            for member in bundle.infolist():
                target = (runtime / member.filename).resolve()
                if root not in target.parents and target != root:
                    raise AcidifyHostError("Node.js 压缩包包含不安全路径")
            bundle.extractall(runtime)
    if not node.is_file() or not npm.is_file():
        raise AcidifyHostError("Node.js 官方运行组件安装不完整")
    app.mkdir(parents=True, exist_ok=True)
    for item in (source_bridge, source_package, source_lock):
        destination = app / item.name
        if not destination.is_file() or _sha256(destination) != _sha256(item):
            shutil.copy2(item, destination)
    current_digest = installed_lock.read_text(encoding="ascii").strip() if installed_lock.is_file() else ""
    if not core.is_file() or current_digest != lock_digest:
        result = subprocess.run(
            [str(npm), "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=app,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not core.is_file():
            raise AcidifyHostError("Acidify 依赖安装失败，请检查网络后重试")
        installed_lock.write_text(lock_digest, encoding="ascii")
    return node, app / "bridge.mjs"


class AcidifyBridge:
    def __init__(self, node: Path, script: Path) -> None:
        if not script.is_file():
            raise AcidifyHostError("Acidify 协议桥文件缺失")
        self._process = subprocess.Popen(
            [str(node), str(script)],
            cwd=script.parent,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._lock = threading.Lock()
        self._next_id = 0

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    @property
    def pid(self) -> int:
        return int(self._process.pid)

    def call(self, method: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            if self._process.poll() is not None:
                raise AcidifyHostError("Acidify 协议桥已退出")
            self._next_id += 1
            request = {"id": self._next_id, "method": method, **payload}
            assert self._process.stdin is not None
            assert self._process.stdout is not None
            self._process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
            raw = self._process.stdout.readline()
            if not raw:
                raise AcidifyHostError("Acidify 协议桥没有返回结果")
            try:
                response = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AcidifyHostError("Acidify 协议桥返回格式错误") from exc
            if response.get("id") != self._next_id:
                raise AcidifyHostError("Acidify 协议桥响应序号不匹配")
            if response.get("ok") is not True:
                raise AcidifyHostError(str(response.get("error") or "手机协议请求失败"))
            return response

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                self.call("close")
            except Exception:
                pass
            self._process.terminate()


class AcidifyProtocolService:
    def __init__(
        self,
        project_root: Path,
        vault: WindowsSessionVault,
        *,
        node: str = "",
        sign_url: str = "",
        writes_enabled: bool = False,
        bridge_factory=AcidifyBridge,
    ) -> None:
        self.project_root = project_root
        self.vault = vault
        self.sign_url = sign_url.strip()
        self.writes_enabled = writes_enabled
        self._bridge_factory = bridge_factory
        self._node = node
        self._bridge: AcidifyBridge | None = None
        self._state = "needs_session_import"
        self._uin = ""
        self._last_error = ""
        self._connect_count = 0
        self._reconnect_count = 0
        self._last_transition_at = _utc_now()
        self._lock = threading.RLock()

    def start(self) -> None:
        try:
            session = self.vault.load()
        except SessionProtectionError as exc:
            self._set_error(str(exc))
            return
        if session is None:
            with self._lock:
                self._state = "needs_session_import"
                self._last_transition_at = _utc_now()
            return
        try:
            session = sanitize_android_session(session)
            node, script = ensure_acidify_runtime(self.project_root, self._node)
            bridge = self._bridge_factory(node, script)
            initialized = bridge.call(
                "init",
                session_json=json.dumps(session, separators=(",", ":")),
                sign_url=self.sign_url,
            )
            with self._lock:
                self._bridge = bridge
                self._uin = str(initialized.get("uin") or session["uin"])
                self._state = "connecting"
                self._connect_count += 1
                self._last_transition_at = _utc_now()
                self._last_error = ""
            threading.Thread(target=self._connect, daemon=True).start()
        except Exception as exc:
            self._set_error(str(exc))

    def _connect(self) -> None:
        try:
            bridge = self._require_bridge(online=False)
            result = bridge.call("online")
            refreshed = json.loads(str(result.get("session_json") or "{}"))
            refreshed = sanitize_android_session(refreshed)
            self.vault.save(refreshed)
            with self._lock:
                self._uin = str(refreshed["uin"])
                self._state = "online"
                self._last_transition_at = _utc_now()
                self._last_error = ""
        except Exception as exc:
            self._set_error(str(exc))

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._state = "error"
            self._last_error = message[:500]
            self._last_transition_at = _utc_now()

    def reconnect(self) -> None:
        """Rebuild the authenticated transport without replaying a business request."""
        with self._lock:
            if self._state in {"connecting", "reconnecting"}:
                return
            bridge = self._bridge
            self._bridge = None
            self._state = "reconnecting"
            self._last_error = ""
            self._reconnect_count += 1
            self._last_transition_at = _utc_now()
        if bridge is not None:
            bridge.close()
        self.start()

    def health(self) -> dict[str, Any]:
        with self._lock:
            bridge = self._bridge
            bridge_alive = bool(bridge and getattr(bridge, "alive", True))
            return {
                "ok": True,
                "protocol_family": "android_qq",
                "protocol_version": "9.2.80",
                "login_backend": "acidify_android_session",
                "session_state": self._state,
                "uin": self._uin,
                "last_error": self._last_error,
                "signer_state": "configured" if self.sign_url else "not_configured",
                "session_security": {
                    "password_stored": False,
                    "vault": "windows_dpapi",
                    "sensitive_fields": "redacted",
                },
                "transport": {
                    "local_api": "http_loopback",
                    "bridge": "jsonl_stdio",
                    "qq_channel": "android_core_tcp",
                    "bridge_alive": bridge_alive,
                    "connect_count": self._connect_count,
                    "reconnect_count": self._reconnect_count,
                    "last_transition_at": self._last_transition_at,
                },
                "external_api": external_api_security(self.sign_url),
                "writes_enabled": self.writes_enabled,
                "login_capabilities": {
                    "qr": False,
                    "password": False,
                    "session_import": True,
                    "session_restore": True,
                },
                "login_help": "请一次性导入已授权的 Android 会话；助手不会接收或保存 QQ 密码",
            }

    def _require_bridge(self, *, online: bool = True) -> AcidifyBridge:
        with self._lock:
            bridge = self._bridge
            state = self._state
        if bridge is None:
            raise AcidifyHostError("尚未导入 Android 手机 QQ 会话")
        if online and state != "online":
            raise AcidifyHostError(f"Android 手机 QQ 会话尚未在线（{state}）")
        return bridge

    def friends(self) -> list[dict[str, Any]]:
        return list(self._require_bridge().call("friends").get("friends") or [])

    def oidb(self, request: dict[str, Any]) -> str:
        try:
            spec = (
                str(request["command_name"]),
                int(request["command"]),
                int(request["sub_command"]),
            )
            body = str(request["body_base64"])
            base64.b64decode(body, validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise AcidifyHostError("OIDB 请求格式不正确") from exc
        write = bool(request.get("write", False))
        allowlist = (
            MobileProtocolReader.WRITE_ALLOWLIST if write else MobileProtocolReader.READ_ALLOWLIST
        )
        if spec not in allowlist:
            raise AcidifyHostError(f"{spec[0]} 不在手机协议白名单")
        if write and not self.writes_enabled:
            raise AcidifyHostError("写操作尚未启用；须先完成只读在线验证")
        result = self._require_bridge().call(
            "oidb",
            command_name=spec[0],
            command=spec[1],
            sub_command=spec[2],
            body_base64=body,
        )
        return str(result.get("body_base64") or "")

    def logout(self) -> None:
        with self._lock:
            bridge = self._bridge
            self._bridge = None
            self._state = "needs_session_import"
            self._uin = ""
            self._last_error = ""
            self._last_transition_at = _utc_now()
        if bridge is not None:
            bridge.close()
        self.vault.clear()

    def close(self) -> None:
        """Stop the runtime while preserving the DPAPI-encrypted fast-login session."""
        with self._lock:
            bridge = self._bridge
            self._bridge = None
            if self._state == "online":
                self._state = "offline"
                self._last_transition_at = _utc_now()
        if bridge is not None:
            bridge.close()


def _handler(service: AcidifyProtocolService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "QQPetAcidifyHost/0.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _json(self, status: int, value: dict[str, Any]) -> None:
            raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > 2 * 1024 * 1024:
                raise AcidifyHostError("请求内容过大")
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise AcidifyHostError("请求必须是 JSON 对象")
            return value

        def do_GET(self) -> None:  # noqa: N802
            try:
                if self.path == "/v1/health":
                    self._json(200, service.health())
                elif self.path == "/v1/friends":
                    self._json(200, {"ok": True, "friends": service.friends()})
                else:
                    self._json(404, {"ok": False, "code": "not_found", "message": "接口不存在"})
            except Exception as exc:
                self._json(409, {"ok": False, "code": "request_failed", "message": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._body()
                if self.path == "/v1/oidb":
                    result = service.oidb(payload)
                    self._json(200, {"ok": True, "body_base64": result})
                elif self.path == "/v1/login/logout":
                    service.logout()
                    self._json(200, {"ok": True})
                elif self.path == "/v1/session/reconnect":
                    service.reconnect()
                    self._json(202, {"ok": True, "session_state": service.health()["session_state"]})
                elif self.path == "/v1/login/qr":
                    self._json(501, {"ok": False, "code": "qr_unavailable", "message": "Android 后端不支持二维码登录，请导入已授权会话"})
                else:
                    self._json(404, {"ok": False, "code": "not_found", "message": "接口不存在"})
            except (AcidifyHostError, json.JSONDecodeError) as exc:
                self._json(400, {"ok": False, "code": "request_failed", "message": str(exc)})

    return Handler


def default_vault() -> WindowsSessionVault:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return WindowsSessionVault(root / "QQPetInterfaceCopilot" / "protocol" / "acidify-session.dat")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QQ 宠物纯电脑 Android 协议服务")
    parser.add_argument("--import-session", metavar="FILE")
    parser.add_argument("--listen", default="127.0.0.1:17890")
    parser.add_argument("--node", default="")
    parser.add_argument("--sign-url", default=os.environ.get("QQPET_ANDROID_SIGN_URL", ""))
    parser.add_argument("--enable-writes", action="store_true")
    args = parser.parse_args(argv)
    vault = default_vault()
    if args.import_session:
        uin = import_android_session(args.import_session, vault)
        print(f"Android 会话已加密保存：QQ {uin}")
        return 0
    host, separator, port_text = args.listen.rpartition(":")
    if not separator or host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("--listen 只允许本机回环地址")
    project_root = Path(
        getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])
    ).resolve()
    service = AcidifyProtocolService(
        project_root,
        vault,
        node=args.node,
        sign_url=args.sign_url,
        writes_enabled=args.enable_writes,
    )
    service.start()
    server = ThreadingHTTPServer((host, int(port_text)), _handler(service))
    print(f"QQ 宠物 Android 协议服务已启动：http://{args.listen}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        service.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
