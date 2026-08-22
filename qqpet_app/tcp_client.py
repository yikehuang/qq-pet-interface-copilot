from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from typing import Callable, Protocol


class TcpClientError(RuntimeError):
    pass


class TcpClientClosed(TcpClientError):
    pass


class PacketFramer(Protocol):
    def pack(self, payload: bytes) -> bytes: ...

    def feed(self, chunk: bytes) -> tuple[bytes, ...]: ...


@dataclass
class LengthPrefixedFramer:
    """Simple length-prefixed packet codec for TCP payload framing."""

    header_size: int = 4
    byteorder: str = "big"

    def __post_init__(self) -> None:
        if self.header_size not in {2, 4}:
            raise ValueError("header_size must be 2 or 4")
        self._buffer = bytearray()

    def pack(self, payload: bytes) -> bytes:
        body = bytes(payload)
        return len(body).to_bytes(self.header_size, self.byteorder) + body

    def feed(self, chunk: bytes) -> tuple[bytes, ...]:
        if chunk:
            self._buffer.extend(chunk)
        frames: list[bytes] = []
        while len(self._buffer) >= self.header_size:
            size = int.from_bytes(
                self._buffer[: self.header_size], self.byteorder, signed=False
            )
            if len(self._buffer) < self.header_size + size:
                break
            start = self.header_size
            end = start + size
            frames.append(bytes(self._buffer[start:end]))
            del self._buffer[:end]
        return tuple(frames)


OnConnect = Callable[["TcpClient"], None]
OnReceive = Callable[["TcpClient", bytes], None]
OnClose = Callable[["TcpClient", str], None]
OnError = Callable[["TcpClient", Exception], None]


class TcpClient:
    """Small event-driven TCP client for the pure-PC stack.

    It mirrors the useful parts of the old HPSocket-style module:
    connect, disconnect, send, send_text, send_part, framed sends,
    and receive callbacks.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float = 5.0,
        recv_buffer_size: int = 65536,
        framer: PacketFramer | None = None,
        auto_reconnect: bool = False,
        reconnect_delay: float = 1.0,
    ) -> None:
        self.host = str(host).strip()
        self.port = int(port)
        self.timeout = max(0.1, float(timeout))
        self.recv_buffer_size = max(1, int(recv_buffer_size))
        self.framer = framer
        self.auto_reconnect = bool(auto_reconnect)
        self.reconnect_delay = max(0.1, float(reconnect_delay))

        self.on_connect: OnConnect | None = None
        self.on_receive: OnReceive | None = None
        self.on_close: OnClose | None = None
        self.on_error: OnError | None = None

        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._connected = threading.Event()
        self._last_error: Exception | None = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set() and self._socket is not None

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def set_callbacks(
        self,
        *,
        on_connect: OnConnect | None = None,
        on_receive: OnReceive | None = None,
        on_close: OnClose | None = None,
        on_error: OnError | None = None,
    ) -> "TcpClient":
        self.on_connect = on_connect
        self.on_receive = on_receive
        self.on_close = on_close
        self.on_error = on_error
        return self

    def connect(self, *, async_connect: bool = False) -> bool:
        if async_connect:
            thread = threading.Thread(
                target=self._connect_sync, name="TcpClientConnect", daemon=True
            )
            thread.start()
            return True
        return self._connect_sync()

    def connect_async(self) -> threading.Thread:
        thread = threading.Thread(
            target=self._connect_sync, name="TcpClientConnect", daemon=True
        )
        thread.start()
        return thread

    def disconnect(self) -> None:
        self._close("manual close")

    def close(self) -> None:
        self.disconnect()

    def send(self, data: bytes | bytearray | memoryview) -> int:
        payload = bytes(data)
        with self._state_lock:
            sock = self._socket
        if sock is None or not self.connected:
            raise TcpClientClosed("TCP client is not connected")
        with self._send_lock:
            sock.sendall(payload)
        return len(payload)

    def send_part(self, data: bytes | bytearray | memoryview, offset: int, length: int) -> int:
        start = max(0, int(offset))
        end = start + max(0, int(length))
        return self.send(bytes(data)[start:end])

    def send_text(self, text: str, encoding: str = "utf-8") -> int:
        return self.send(text.encode(encoding))

    def send_packets(self, *parts: bytes | bytearray | memoryview) -> int:
        payload = b"".join(bytes(part) for part in parts)
        return self.send(payload)

    def send_packet(self, payload: bytes | bytearray | memoryview) -> int:
        if self.framer is None:
            return self.send(payload)
        return self.send(self.framer.pack(bytes(payload)))

    def _connect_sync(self) -> bool:
        with self._state_lock:
            self._stop_event.clear()
            self._last_error = None
            if self.connected:
                return True
            try:
                sock = socket.create_connection((self.host, self.port), self.timeout)
                sock.settimeout(0.5)
            except OSError as exc:
                self._last_error = exc
                self._emit_error(exc)
                raise TcpClientError(f"failed to connect to {self.host}:{self.port}") from exc
            self._socket = sock
            self._connected.set()
            self._reader = threading.Thread(
                target=self._recv_loop, name="TcpClientRecv", daemon=True
            )
            self._reader.start()
        self._emit_connect()
        return True

    def _recv_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                sock = self._socket
                if sock is None:
                    break
                try:
                    chunk = sock.recv(self.recv_buffer_size)
                except socket.timeout:
                    continue
                except OSError as exc:
                    self._last_error = exc
                    self._emit_error(exc)
                    break
                if not chunk:
                    break
                if self.framer is None:
                    self._emit_receive(chunk)
                    continue
                for frame in self.framer.feed(chunk):
                    self._emit_receive(frame)
        finally:
            self._close("remote closed", from_reader=True)

    def _close(self, reason: str, *, from_reader: bool = False) -> None:
        with self._state_lock:
            sock = self._socket
            self._socket = None
            was_connected = self._connected.is_set()
            self._connected.clear()
            self._stop_event.set()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if was_connected and not from_reader:
            self._emit_close(reason)
        elif was_connected and from_reader:
            self._emit_close(reason)

    def _emit_connect(self) -> None:
        if self.on_connect is None:
            return
        try:
            self.on_connect(self)
        except Exception as exc:
            self._last_error = exc
            self._emit_error(exc)

    def _emit_receive(self, data: bytes) -> None:
        if self.on_receive is None:
            return
        try:
            self.on_receive(self, data)
        except Exception as exc:
            self._last_error = exc
            self._emit_error(exc)

    def _emit_close(self, reason: str) -> None:
        if self.on_close is None:
            return
        try:
            self.on_close(self, reason)
        except Exception as exc:
            self._last_error = exc
            self._emit_error(exc)

    def _emit_error(self, exc: Exception) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(self, exc)
        except Exception:
            pass


class HPSocketAgentCompat(TcpClient):
    """Compatibility wrapper with HPSocket-style method and event names."""

    @property
    def OnConnect(self) -> OnConnect | None:  # noqa: N802
        return self.on_connect

    @OnConnect.setter
    def OnConnect(self, handler: OnConnect | None) -> None:  # noqa: N802
        self.on_connect = handler

    @property
    def OnReceive(self) -> OnReceive | None:  # noqa: N802
        return self.on_receive

    @OnReceive.setter
    def OnReceive(self, handler: OnReceive | None) -> None:  # noqa: N802
        self.on_receive = handler

    @property
    def OnClose(self) -> OnClose | None:  # noqa: N802
        return self.on_close

    @OnClose.setter
    def OnClose(self, handler: OnClose | None) -> None:  # noqa: N802
        self.on_close = handler

    @property
    def OnError(self) -> OnError | None:  # noqa: N802
        return self.on_error

    @OnError.setter
    def OnError(self, handler: OnError | None) -> None:  # noqa: N802
        self.on_error = handler

    def Connect(self, async_connect: bool = False) -> bool:  # noqa: N802
        return self.connect(async_connect=async_connect)

    def ConnectAsync(self) -> threading.Thread:  # noqa: N802
        return self.connect_async()

    def Disconnect(self) -> None:  # noqa: N802
        self.disconnect()

    def Close(self) -> None:  # noqa: N802
        self.close()

    def Send(self, data: bytes | bytearray | memoryview) -> int:  # noqa: N802
        return self.send(data)

    def SendPart(
        self, data: bytes | bytearray | memoryview, offset: int, length: int
    ) -> int:  # noqa: N802
        return self.send_part(data, offset, length)

    def SendText(self, text: str, encoding: str = "utf-8") -> int:  # noqa: N802
        return self.send_text(text, encoding)

    def SendPackets(self, *parts: bytes | bytearray | memoryview) -> int:  # noqa: N802
        return self.send_packets(*parts)

    def SendPacket(self, payload: bytes | bytearray | memoryview) -> int:  # noqa: N802
        return self.send_packet(payload)
