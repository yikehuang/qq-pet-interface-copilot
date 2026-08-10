from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


NAPCAT_RELEASE_API = "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest"
NAPCAT_RUNTIME_ASSET = "NapCat.Shell.Windows.Node.zip"
NAPCAT_CONFIG_RELATIVE = Path("runtime") / "NapCatQQ" / "config"
NAPCAT_DIRECT_CONFIG_RELATIVE = Path("napcat") / "config"
DEFAULT_ONEBOT_PORT = 6201


@dataclass(frozen=True)
class OneBotEndpoint:
    url: str
    token: str = ""
    uin_hint: str = ""
    config_path: Path | None = None


@dataclass(frozen=True)
class LoginSession:
    endpoint: OneBotEndpoint
    uin: str
    nickname: str = ""


@dataclass(frozen=True)
class DependencyState:
    napcat_root: Path | None
    qq_path: Path | None
    sessions: tuple[LoginSession, ...]


@dataclass(frozen=True)
class RuntimeAsset:
    url: str
    name: str
    version: str
    sha256: str


def _is_loopback(host: str) -> bool:
    return host.lower() in {"127.0.0.1", "localhost", "::1"}


def napcat_roots() -> tuple[Path, ...]:
    candidates: list[Path] = []
    program_data = os.environ.get("PROGRAMDATA")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if program_data:
        candidates.append(Path(program_data) / "NapCatQQ Desktop")
    if local_app_data:
        candidates.extend(
            (
                Path(local_app_data)
                / "QQPetInterfaceCopilot"
                / "runtime"
                / "NapCat.Shell.Windows.Node",
                Path(local_app_data) / "NapCatQQ Desktop",
                Path(local_app_data) / "Programs" / "NapCatQQ Desktop",
            )
        )
    unique: list[Path] = []
    for path in candidates:
        if path not in unique:
            unique.append(path)
    return tuple(unique)


def managed_runtime_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "QQPetInterfaceCopilot" / "runtime" / "NapCat.Shell.Windows.Node"


def napcat_config_dir(root: Path) -> Path | None:
    direct = root / NAPCAT_DIRECT_CONFIG_RELATIVE
    if direct.is_dir() and (root / "node.exe").is_file() and (root / "index.js").is_file():
        return direct
    desktop = root / NAPCAT_CONFIG_RELATIVE
    if desktop.is_dir():
        return desktop
    return None


def is_managed_runtime(root: Path) -> bool:
    return (
        (root / "node.exe").is_file()
        and (root / "index.js").is_file()
        and (root / NAPCAT_DIRECT_CONFIG_RELATIVE).is_dir()
    )


def find_napcat_root() -> Path | None:
    for root in napcat_roots():
        if napcat_config_dir(root) is not None:
            return root
    return None


def _uin_from_filename(path: Path) -> str:
    match = re.search(r"onebot11_(\d+)\.json$", path.name, re.IGNORECASE)
    return match.group(1) if match else ""


def endpoints_from_config(path: Path) -> tuple[OneBotEndpoint, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return ()
    network = data.get("network") if isinstance(data, dict) else None
    servers = network.get("httpServers") if isinstance(network, dict) else None
    if not isinstance(servers, list):
        return ()
    result: list[OneBotEndpoint] = []
    for server in servers:
        if not isinstance(server, dict) or not server.get("enable", False):
            continue
        host = str(server.get("host") or "127.0.0.1")
        if not _is_loopback(host):
            continue
        try:
            port = int(server.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if not (1 <= port <= 65535):
            continue
        result.append(
            OneBotEndpoint(
                url=f"http://127.0.0.1:{port}",
                token=str(server.get("token") or ""),
                uin_hint=_uin_from_filename(path),
                config_path=path,
            )
        )
    return tuple(result)


def discover_endpoints(
    configured_url: str = "", configured_token: str = ""
) -> tuple[OneBotEndpoint, ...]:
    candidates: list[OneBotEndpoint] = []
    if configured_url.startswith(("http://127.0.0.1", "http://localhost")):
        candidates.append(OneBotEndpoint(configured_url.rstrip("/"), configured_token))
    for root in napcat_roots():
        config_dir = napcat_config_dir(root)
        if config_dir is None:
            continue
        for path in sorted(config_dir.glob("onebot11_*.json")):
            candidates.extend(endpoints_from_config(path))
    unique: list[OneBotEndpoint] = []
    keys: set[tuple[str, str]] = set()
    for endpoint in candidates:
        key = (endpoint.url, endpoint.token)
        if key not in keys:
            unique.append(endpoint)
            keys.add(key)
    return tuple(unique)


def onebot_action(
    endpoint: OneBotEndpoint, action: str, params: dict | None = None, timeout: float = 3
) -> dict:
    headers = {"Content-Type": "application/json"}
    if endpoint.token:
        headers["Authorization"] = f"Bearer {endpoint.token}"
    request = urllib.request.Request(
        f"{endpoint.url.rstrip('/')}/{action}",
        data=json.dumps(params or {}).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("NapCat 返回了无法识别的数据")
    return result


def probe_login(endpoint: OneBotEndpoint, timeout: float = 3) -> LoginSession | None:
    try:
        result = onebot_action(endpoint, "get_login_info", timeout=timeout)
    except (OSError, TimeoutError, TypeError, urllib.error.URLError, ValueError, RuntimeError):
        return None
    if result.get("status") != "ok" or int(result.get("retcode", -1)) != 0:
        return None
    data = result.get("data") or {}
    uin = str(data.get("user_id") or endpoint.uin_hint or "")
    if not uin.isdigit():
        return None
    return LoginSession(endpoint=endpoint, uin=uin, nickname=str(data.get("nickname") or ""))


def active_sessions(
    configured_url: str = "", configured_token: str = ""
) -> tuple[LoginSession, ...]:
    result: list[LoginSession] = []
    seen: set[tuple[str, str]] = set()
    for endpoint in discover_endpoints(configured_url, configured_token):
        session = probe_login(endpoint)
        if session and (session.uin, endpoint.url) not in seen:
            result.append(session)
            seen.add((session.uin, endpoint.url))
    return tuple(result)


def _registry_qq_paths() -> Iterable[Path]:
    if os.name != "nt":
        return ()
    try:
        import winreg
    except ImportError:
        return ()
    roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    keys = (
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
    )
    found: list[Path] = []
    for root in roots:
        for key_name in keys:
            try:
                with winreg.OpenKey(root, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, "UninstallString")
            except OSError:
                continue
            raw = str(value).strip().strip('"')
            parent = Path(raw).parent
            found.extend((parent / "QQ.exe", parent.parent / "QQ.exe"))
    return tuple(found)


def find_qq_path() -> Path | None:
    candidates = list(_registry_qq_paths())
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.extend(
                (
                    Path(base) / "Tencent" / "QQNT" / "QQ.exe",
                    Path(base) / "Tencent" / "QQ" / "QQ.exe",
                )
            )
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def dependency_state(configured_url: str = "", configured_token: str = "") -> DependencyState:
    return DependencyState(
        napcat_root=find_napcat_root(),
        qq_path=find_qq_path(),
        sessions=active_sessions(configured_url, configured_token),
    )


def configure_local_onebot(config_path: Path, port: int = DEFAULT_ONEBOT_PORT) -> OneBotEndpoint:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            pass
    network = data.setdefault("network", {})
    servers = network.setdefault("httpServers", [])
    for server in servers:
        if (
            isinstance(server, dict)
            and server.get("enable", False)
            and _is_loopback(str(server.get("host") or "127.0.0.1"))
        ):
            return OneBotEndpoint(
                f"http://127.0.0.1:{int(server['port'])}",
                str(server.get("token") or ""),
                _uin_from_filename(config_path),
                config_path,
            )
    token = secrets.token_urlsafe(32)
    servers.append(
        {
            "enable": True,
            "name": "QQPetInterfaceCopilot",
            "port": int(port),
            "host": "127.0.0.1",
            "enableCors": False,
            "enableWebsocket": False,
            "messagePostFormat": "array",
            "token": token,
            "debug": False,
        }
    )
    for key in ("httpSseServers", "httpClients", "websocketServers", "websocketClients", "plugins"):
        network.setdefault(key, [])
    config_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return OneBotEndpoint(
        f"http://127.0.0.1:{port}", token, _uin_from_filename(config_path), config_path
    )


def _free_local_port(preferred: int = DEFAULT_ONEBOT_PORT) -> int:
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("找不到可用的本机端口")


def start_napcat(uin: str = "", qq_path: Path | None = None) -> subprocess.Popen:
    root = find_napcat_root()
    if not root:
        raise RuntimeError("尚未安装 NapCat 运行环境")
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if is_managed_runtime(root):
        command = [str(root / "node.exe"), str(root / "index.js")]
        if uin.isdigit():
            command.extend(("-q", uin))
        return subprocess.Popen(command, cwd=root, creationflags=creationflags)
    runtime = root / "runtime" / "NapCatQQ"
    boot = runtime / "NapCatWinBootMain.exe"
    hook = runtime / "NapCatWinBootHook.dll"
    qq = qq_path or find_qq_path()
    if not boot.is_file() or not hook.is_file():
        raise RuntimeError("NapCat 运行文件不完整，请重新安装")
    if not qq or not qq.is_file():
        raise RuntimeError("没有找到电脑版 QQ，请先安装 QQ")
    command = [str(boot), str(qq), str(hook)]
    if uin.isdigit():
        command.append(uin)
    return subprocess.Popen(command, cwd=runtime, creationflags=creationflags)


def latest_napcat_runtime() -> RuntimeAsset:
    request = urllib.request.Request(
        NAPCAT_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "QQPetInterfaceCopilot"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.loads(response.read().decode("utf-8"))
    assets = release.get("assets") or []
    asset = next(
        (
            asset
            for asset in assets
            if str(asset.get("name", "")).lower() == NAPCAT_RUNTIME_ASSET.lower()
        ),
        None,
    )
    if not asset:
        raise RuntimeError("NapCat 官方发布中没有找到完整 Windows 运行包")
    digest = str(asset.get("digest") or "")
    if not digest.lower().startswith("sha256:"):
        raise RuntimeError("NapCat 官方运行包没有提供 SHA-256，已停止下载")
    sha256 = digest.split(":", 1)[1].strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise RuntimeError("NapCat 官方运行包的 SHA-256 格式无效")
    return RuntimeAsset(
        url=str(asset["browser_download_url"]),
        name=str(asset["name"]),
        version=str(release.get("tag_name") or "unknown"),
        sha256=sha256,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def download_napcat_runtime(
    target_dir: Path,
    progress: Callable[[str], None] | None = None,
) -> tuple[Path, RuntimeAsset]:
    notify = progress or (lambda _message: None)
    target_dir.mkdir(parents=True, exist_ok=True)
    asset = latest_napcat_runtime()
    target = target_dir / asset.name
    notify(f"正在下载 NapCat 完整运行环境 {asset.version}（约 120 MB）……")
    urllib.request.urlretrieve(asset.url, target)
    actual = _file_sha256(target)
    if not secrets.compare_digest(actual, asset.sha256):
        target.unlink(missing_ok=True)
        raise RuntimeError("NapCat 运行包校验失败，已删除下载文件")
    notify("NapCat 官方 SHA-256 校验通过。")
    return target, asset


def _safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(destination_root)
            except ValueError as exc:
                raise RuntimeError("NapCat 压缩包包含不安全路径，已停止安装") from exc
        archive.extractall(destination)


def install_napcat_runtime(
    archive_path: Path,
    asset: RuntimeAsset,
    install_root: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    if os.name != "nt":
        raise RuntimeError("一键安装目前仅支持 Windows")
    notify = progress or (lambda _message: None)
    root = install_root or managed_runtime_root()
    if is_managed_runtime(root):
        notify("NapCat 完整运行环境已经安装，无需重复安装。")
        return root
    staging = root.with_name(root.name + ".installing")
    if staging.exists():
        shutil.rmtree(staging)
    notify("正在解压并配置 NapCat、Node 和 QQ 运行组件……")
    _safe_extract_zip(archive_path, staging)
    required = (
        staging / "node.exe",
        staging / "index.js",
        staging / "wrapper.node",
        staging / "napcat" / "napcat.mjs",
        staging / "napcat" / "config",
    )
    if not all(path.exists() for path in required):
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("NapCat 完整运行包缺少启动文件，已停止安装")
    metadata = {
        "source": "NapNeko/NapCatQQ",
        "asset": asset.name,
        "version": asset.version,
        "sha256": asset.sha256,
    }
    (staging / ".qqpet-runtime.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists():
        backup = root.with_name(root.name + f".incomplete-{int(time.time())}")
        root.replace(backup)
    staging.replace(root)
    notify("NapCat 完整运行环境安装完成；无需打开 NapCatQQ Desktop。")
    return root


def ensure_napcat_runtime(
    target_dir: Path,
    progress: Callable[[str], None] | None = None,
) -> Path:
    current = find_napcat_root()
    if current:
        return current
    archive, asset = download_napcat_runtime(target_dir, progress)
    return install_napcat_runtime(archive, asset, progress=progress)


def wait_for_session(
    configured_url: str = "",
    configured_token: str = "",
    preferred_uin: str = "",
    timeout: float = 120,
    interval: float = 2,
    on_wait: Callable[[], None] | None = None,
) -> LoginSession | None:
    deadline = time.monotonic() + timeout
    configured_for: set[Path] = set()
    while time.monotonic() < deadline:
        if on_wait:
            on_wait()
        sessions = active_sessions(configured_url, configured_token)
        if preferred_uin:
            match = next((item for item in sessions if item.uin == preferred_uin), None)
            if match:
                return match
        elif sessions:
            return sessions[0]
        # A fresh QR login creates onebot11_<uin>.json before an HTTP server
        # exists. Add one loopback-only server; current NapCat releases reload
        # this file automatically. Existing enabled servers are never replaced.
        root = find_napcat_root()
        if root:
            config_dir = napcat_config_dir(root)
            if config_dir is None:
                time.sleep(interval)
                continue
            paths = sorted(
                config_dir.glob("onebot11_*.json"),
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            )
            for path in paths:
                if path in configured_for or endpoints_from_config(path):
                    continue
                file_uin = _uin_from_filename(path)
                if preferred_uin and file_uin != preferred_uin:
                    continue
                configure_local_onebot(path, _free_local_port())
                configured_for.add(path)
                break
        time.sleep(interval)
    return None


def login_qrcode_path(root: Path | None = None) -> Path | None:
    selected = root or find_napcat_root()
    if not selected or not is_managed_runtime(selected):
        return None
    path = selected / "napcat" / "cache" / "qrcode.png"
    return path if path.is_file() else None


def ensure_onebot_for_uin(uin: str) -> OneBotEndpoint:
    root = find_napcat_root()
    if not root:
        raise RuntimeError("尚未安装 NapCat 运行环境")
    config_dir = napcat_config_dir(root)
    if config_dir is None:
        raise RuntimeError("NapCat 配置目录不存在，请使用启动器修复运行环境")
    config_path = config_dir / f"onebot11_{uin}.json"
    return configure_local_onebot(config_path, _free_local_port())
