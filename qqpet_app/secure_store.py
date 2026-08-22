from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any


_MAGIC = b"QQPET-DPAPI-1\0"


class SessionProtectionError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    return _DataBlob(len(data), pointer), buffer


def protect_for_current_windows_user(data: bytes) -> bytes:
    if os.name != "nt":
        raise SessionProtectionError("QQ 会话加密存储目前只支持 Windows")
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(b"QQPetInterfaceCopilot/session/v2")
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    # CRYPTPROTECT_UI_FORBIDDEN: never display a system credential dialog.
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        "QQ Pet standalone session",
        ctypes.byref(entropy),
        None,
        None,
        0x1,
        ctypes.byref(output),
    )
    del source_buffer, entropy_buffer
    if not ok:
        raise SessionProtectionError(f"Windows 会话加密失败：{ctypes.get_last_error()}")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def unprotect_for_current_windows_user(data: bytes) -> bytes:
    if os.name != "nt":
        raise SessionProtectionError("QQ 会话加密存储目前只支持 Windows")
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(b"QQPetInterfaceCopilot/session/v2")
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        0x1,
        ctypes.byref(output),
    )
    del source_buffer, entropy_buffer
    if not ok:
        raise SessionProtectionError(
            "QQ 会话无法解密；该文件可能来自另一台电脑或另一个 Windows 用户"
        )
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


class WindowsSessionVault:
    """Atomically store a protocol session encrypted for the current user."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, session: dict[str, Any]) -> None:
        plain = json.dumps(session, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = protect_for_current_windows_user(plain)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(_MAGIC + encrypted)
        temporary.replace(self.path)

    def load(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        raw = self.path.read_bytes()
        if not raw.startswith(_MAGIC):
            raise SessionProtectionError("QQ 会话文件格式不正确")
        try:
            value = json.loads(unprotect_for_current_windows_user(raw[len(_MAGIC) :]))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SessionProtectionError("QQ 会话内容损坏") from exc
        if not isinstance(value, dict):
            raise SessionProtectionError("QQ 会话内容格式不正确")
        return value

    def clear(self) -> None:
        if self.path.is_file():
            self.path.unlink()
