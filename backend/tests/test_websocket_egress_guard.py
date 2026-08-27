"""SSRF egress-guard tests for the WebSocket Send node and Trigger.

Mirrors tests/test_http_node_ssrf_guard.py: the address policy is shared, so
these assert the ws/wss entry point into it, the handshake-header rejection,
and the socket ownership the pinned dial needs.
"""

import asyncio
import socket
import threading
import unittest
from unittest.mock import AsyncMock, patch

from app.services import ssrf_guard
from app.services.ssrf_guard import (
    SsrfBlockedError,
    SsrfResolutionError,
    _open_pinned_websocket_socket,
    guard_websocket_url,
    open_guarded_websocket,
    reject_reserved_websocket_headers,
)
from app.services.websocket_utils import (
    build_websocket_connect_kwargs,
    send_websocket_message,
)


def _addrinfo(*ips: str) -> list:
    """Build a getaddrinfo-style result for the given IPv4/IPv6 literals."""
    out = []
    for ip in ips:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
        out.append((family, socket.SOCK_STREAM, 0, "", sockaddr))
    return out


class _PinnedOptOutOff(unittest.TestCase):
    """Pin the opt-out so assertions do not depend on the ambient setting."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)


class GuardIpLiteralTests(_PinnedOptOutOff):
    """IP-literal hosts are validated without a DNS lookup."""

    def test_loopback_blocked(self) -> None:
        for url in ("ws://127.0.0.1:8080/", "wss://[::1]:9000/"):
            with self.subTest(url=url), self.assertRaises(SsrfBlockedError):
                guard_websocket_url(url)

    def test_private_blocked(self) -> None:
        for url in ("ws://10.0.0.5/", "ws://192.168.1.10/", "ws://172.16.5.5/"):
            with self.subTest(url=url), self.assertRaises(SsrfBlockedError):
                guard_websocket_url(url)

    def test_cloud_metadata_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_websocket_url("ws://169.254.169.254/latest/meta-data/")

    def test_ipv4_mapped_and_compatible_metadata_blocked(self) -> None:
        for url in ("ws://[::ffff:169.254.169.254]/", "ws://[::169.254.169.254]/"):
            with self.subTest(url=url), self.assertRaises(SsrfBlockedError):
                guard_websocket_url(url)

    def test_nat64_metadata_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_websocket_url("ws://[64:ff9b::a9fe:a9fe]/")

    def test_multicast_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_websocket_url("ws://239.255.255.250/")

    def test_public_allowed(self) -> None:
        guard_websocket_url("ws://1.1.1.1/")
        guard_websocket_url("wss://1.1.1.1/")

    def test_http_scheme_blocked(self) -> None:
        """The http(s) guard's schemes are not this guard's schemes."""
        for url in ("http://1.1.1.1/", "https://1.1.1.1/", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(SsrfBlockedError):
                guard_websocket_url(url)

    def test_missing_host_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_websocket_url("ws:///path-only")

    def test_invalid_port_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            guard_websocket_url("ws://1.1.1.1:notaport/")


class GuardDnsTests(_PinnedOptOutOff):
    """Every A/AAAA answer must be public, not just the first."""

    def test_mixed_answer_blocked(self) -> None:
        with patch.object(
            ssrf_guard.socket,
            "getaddrinfo",
            return_value=_addrinfo("93.184.216.34", "127.0.0.1"),
        ):
            with self.assertRaises(SsrfBlockedError):
                guard_websocket_url("ws://mixed.example.com/")

    def test_public_answer_allowed(self) -> None:
        with patch.object(
            ssrf_guard.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")
        ):
            guard_websocket_url("ws://public.example.com/")

    def test_resolution_failure_is_classified_as_transient(self) -> None:
        with patch.object(
            ssrf_guard.socket,
            "getaddrinfo",
            side_effect=socket.gaierror("temporary failure"),
        ):
            with self.assertRaises(SsrfResolutionError):
                guard_websocket_url("ws://unresolved.example.com/")


class GuardOptOutTests(unittest.TestCase):
    """HEYM_HTTP_ALLOW_PRIVATE_URLS relaxes the address block, not the scheme."""

    def test_private_allowed_when_opted_out(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            guard_websocket_url("ws://127.0.0.1:8080/")

    def test_scheme_still_enforced_when_opted_out(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            with self.assertRaises(SsrfBlockedError):
                guard_websocket_url("http://127.0.0.1:8080/")


class ReservedHeaderTests(unittest.TestCase):
    """Handshake-steering headers are refused; data headers still pass."""

    def test_protocol_headers_rejected(self) -> None:
        for name in (
            "Host",
            "host",
            "Connection",
            "Upgrade",
            "Sec-WebSocket-Key",
            "sec-websocket-extensions",
            "Sec-WebSocket-Version",
        ):
            with self.subTest(header=name), self.assertRaises(SsrfBlockedError):
                reject_reserved_websocket_headers({name: "x"})

    def test_data_headers_allowed(self) -> None:
        reject_reserved_websocket_headers(
            {"Authorization": "Bearer t", "X-Trace": "1", "User-Agent": "ua"}
        )

    def test_empty_headers_allowed(self) -> None:
        reject_reserved_websocket_headers({})
        reject_reserved_websocket_headers(None)

    def test_connect_kwargs_rejects_reserved_header(self) -> None:
        """Both egress paths build kwargs here, so one check covers both."""
        with self.assertRaises(SsrfBlockedError):
            build_websocket_connect_kwargs('{"Upgrade": "h2c"}', "")

    def test_connect_kwargs_keeps_data_headers(self) -> None:
        kwargs = build_websocket_connect_kwargs('{"Authorization": "Bearer t"}', "")
        self.assertEqual(kwargs["additional_headers"]["Authorization"], "Bearer t")

    def test_origin_uses_the_dedicated_connect_argument(self) -> None:
        kwargs = build_websocket_connect_kwargs('{"oRiGiN": "https://client.example"}', "")

        self.assertEqual(kwargs["origin"], "https://client.example")
        self.assertNotIn("additional_headers", kwargs)

    def test_duplicate_origin_headers_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "only one origin"):
            build_websocket_connect_kwargs(
                '{"Origin": "https://one.example", "origin": "https://two.example"}',
                "",
            )


class HeaderInjectionWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_header_bytes_never_reach_the_wire(self) -> None:
        captured_requests: list[bytes] = []

        async def capture_request(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            try:
                captured_requests.append(await reader.readuntil(b"\r\n\r\n"))
                writer.write(
                    b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(capture_request, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        invalid_headers = (
            (
                {"Authorization": "Bearer t\r\nHost: internal-admin\r\nUpgrade: h2c"},
                "invalid control character",
            ),
            ({"Origin": "https://client.example\r\nHost: internal-admin"}, "invalid control"),
            ({"X-Trace\r\nHost": "internal-admin"}, "header name"),
            ({"Authorization": "Bearer\x00token"}, "invalid control character"),
        )

        try:
            with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
                for headers, error_pattern in invalid_headers:
                    with self.subTest(headers=headers):
                        with self.assertRaisesRegex(ValueError, error_pattern):
                            await send_websocket_message(
                                url=f"ws://127.0.0.1:{port}/",
                                headers=headers,
                                subprotocols=[],
                                message="test",
                            )
            await asyncio.sleep(0.05)
        finally:
            server.close()
            await server.wait_closed()

        self.assertEqual(captured_requests, [])


class OpenGuardedWebSocketTests(unittest.IsolatedAsyncioTestCase):
    """The dial is pinned, proxy-free, and owns its socket until handoff."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_refuses_before_dialling(self) -> None:
        with patch.object(ssrf_guard.websockets, "connect", new=AsyncMock()) as dial:
            with self.assertRaises(SsrfBlockedError):
                await open_guarded_websocket("ws://169.254.169.254/")
            dial.assert_not_awaited()

    async def test_proxy_disabled_on_the_dial(self) -> None:
        sock = socket.socket()
        self.addCleanup(sock.close)
        with patch.object(
            ssrf_guard, "_open_pinned_websocket_socket", new=AsyncMock(return_value=sock)
        ) as opener:
            with patch.object(ssrf_guard.websockets, "connect", new=AsyncMock()) as dial:
                await open_guarded_websocket("ws://1.1.1.1/")
            opener.assert_awaited_once()
            self.assertIsNone(dial.await_args.kwargs["proxy"])

    async def test_socket_closed_when_handshake_fails(self) -> None:
        """websockets closes a caller socket on cancellation but not on a failed
        handshake; without this the Trigger's retry loop leaks one descriptor
        per attempt against a host that accepts TCP without speaking WebSocket."""
        opened: list[socket.socket] = []
        real = ssrf_guard._open_pinned_websocket_socket

        async def spy(url: str) -> socket.socket:
            sock = await real(url)
            opened.append(sock)
            return sock

        # A raw TCP listener that accepts and never completes the handshake.
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        self.addCleanup(server.close)

        with patch.object(
            ssrf_guard,
            "_resolve_pinned_addresses",
            return_value=[(socket.AF_INET, "127.0.0.1")],
        ):
            with patch.object(
                ssrf_guard.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")
            ):
                with patch.object(ssrf_guard, "_open_pinned_websocket_socket", new=spy):
                    with self.assertRaises(BaseException):
                        await asyncio.wait_for(
                            open_guarded_websocket(f"ws://public.example.com:{port}/"),
                            timeout=1.5,
                        )

        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError):
            opened[0].getsockname()  # closed

    async def test_opt_out_skips_the_pin_and_preserves_proxy_behavior(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            with patch.object(
                ssrf_guard, "_open_pinned_websocket_socket", new=AsyncMock()
            ) as opener:
                with patch.object(ssrf_guard.websockets, "connect", new=AsyncMock()) as dial:
                    await open_guarded_websocket("ws://127.0.0.1:9/")
                opener.assert_not_awaited()
                self.assertNotIn("proxy", dial.await_args.kwargs)

    async def test_dns_resolution_does_not_block_the_event_loop(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def blocking_resolution(*_args: object, **_kwargs: object) -> list:
            started.set()
            release.wait(timeout=2)
            return _addrinfo("127.0.0.1")

        with patch.object(ssrf_guard.socket, "getaddrinfo", side_effect=blocking_resolution):
            task = asyncio.create_task(open_guarded_websocket("ws://slow-dns.example/"))
            try:
                await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=1)
                await asyncio.sleep(0.01)
                self.assertFalse(task.done())
            finally:
                release.set()

            with self.assertRaises(SsrfBlockedError):
                await task

    async def test_open_timeout_covers_the_pinned_tcp_connect(self) -> None:
        loop = asyncio.get_running_loop()

        async def never_connect(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(10)

        with (
            patch.object(
                ssrf_guard,
                "_resolve_pinned_addresses",
                return_value=[(socket.AF_INET, "1.1.1.1")],
            ),
            patch.object(loop, "sock_connect", new=AsyncMock(side_effect=never_connect)),
        ):
            with self.assertRaisesRegex(TimeoutError, "timed out while resolving"):
                await open_guarded_websocket("ws://1.1.1.1/", open_timeout=0.01)

    async def test_pinned_dial_falls_back_to_the_next_validated_address(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.closed = False

            def setblocking(self, _value: bool) -> None:
                return

            def close(self) -> None:
                self.closed = True

        sockets = [FakeSocket(), FakeSocket()]
        loop = asyncio.get_running_loop()
        with (
            patch.object(
                ssrf_guard,
                "_resolve_pinned_addresses",
                return_value=[
                    (socket.AF_INET6, "2606:4700:4700::1111"),
                    (socket.AF_INET, "1.1.1.1"),
                ],
            ),
            patch.object(ssrf_guard.socket, "socket", side_effect=sockets),
            patch.object(
                loop,
                "sock_connect",
                new=AsyncMock(side_effect=[OSError("unreachable"), None]),
            ) as connect,
        ):
            result = await _open_pinned_websocket_socket("wss://public.example/")

        self.assertIs(result, sockets[1])
        self.assertTrue(sockets[0].closed)
        self.assertFalse(sockets[1].closed)
        self.assertEqual(connect.await_count, 2)

    async def test_redirect_is_reported_as_a_policy_block(self) -> None:
        response_sent = asyncio.Event()

        async def redirect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 302 Found\r\n"
                    b"Location: ws://other.example/socket\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                response_sent.set()

        server = await asyncio.start_server(redirect, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with (
                patch.object(
                    ssrf_guard.socket,
                    "getaddrinfo",
                    return_value=_addrinfo("93.184.216.34"),
                ),
                patch.object(
                    ssrf_guard,
                    "_resolve_pinned_addresses",
                    return_value=[(socket.AF_INET, "127.0.0.1")],
                ),
            ):
                with self.assertRaisesRegex(SsrfBlockedError, "redirects are not allowed"):
                    await open_guarded_websocket(f"ws://public.example:{port}/")
                await asyncio.wait_for(response_sent.wait(), timeout=1)
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
