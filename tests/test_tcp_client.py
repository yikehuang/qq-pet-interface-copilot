from __future__ import annotations

import socket
import threading
import time
import unittest

from qqpet_app.tcp_client import (
    HPSocketAgentCompat,
    LengthPrefixedFramer,
    TcpClient,
)


class TcpClientTests(unittest.TestCase):
    def test_length_prefixed_framer_round_trips_frames(self) -> None:
        framer = LengthPrefixedFramer()
        blob = framer.pack(b"abc") + framer.pack(b"defg")
        self.assertEqual(framer.feed(blob[:2]), ())
        self.assertEqual(framer.feed(blob[2:7]), (b"abc",))
        self.assertEqual(framer.feed(blob[7:]), (b"defg",))

    def test_client_can_connect_send_receive_and_close(self) -> None:
        ready = threading.Event()
        stop = threading.Event()
        port_holder: list[int] = []

        def server() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                sock.listen(1)
                port_holder.append(sock.getsockname()[1])
                ready.set()
                conn, _addr = sock.accept()
                with conn:
                    conn.settimeout(1.0)
                    data = conn.recv(1024)
                    conn.sendall(b"ack:" + data)
                    stop.wait(1.0)

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(2.0))

        received: list[bytes] = []
        closed: list[str] = []
        client = TcpClient("127.0.0.1", port_holder[0])
        client.set_callbacks(
            on_receive=lambda _c, data: received.append(data),
            on_close=lambda _c, reason: closed.append(reason),
        )
        client.connect()
        client.send_text("ping")
        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.01)
        client.disconnect()
        stop.set()

        self.assertEqual(received, [b"ack:ping"])
        self.assertTrue(closed)

    def test_hpsocket_compat_aliases_match_expected_call_shape(self) -> None:
        client = HPSocketAgentCompat("127.0.0.1", 1)
        events = []
        client.OnConnect = lambda _c: events.append("connect")
        client.OnReceive = lambda _c, data: events.append(("recv", data))
        client.OnClose = lambda _c, reason: events.append(("close", reason))

        self.assertIs(client.OnConnect, client.on_connect)
        self.assertIs(client.OnReceive, client.on_receive)
        self.assertIs(client.OnClose, client.on_close)


if __name__ == "__main__":
    unittest.main()
