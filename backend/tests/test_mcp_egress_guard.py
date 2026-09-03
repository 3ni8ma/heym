"""SSRF egress-guard tests for MCP http(s)/SSE transports (GHSA-jjvx-3wfc-p8hq)."""

import socket
import ssl
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import httpx

from app.services.mcp_tool_executor import (
    _guard_mcp_http_url,
    _install_egress_pin,
    _McpEgressPinBackend,
    _open_transport,
    _resolve_pinned_mcp_ip,
    _sse_client_fail_fast,
)


def _addrinfo(*ips: str) -> list:
    """Build a getaddrinfo-style result for the given IPv4/IPv6 literals."""
    out = []
    for ip in ips:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
        out.append((family, socket.SOCK_STREAM, 0, "", sockaddr))
    return out


class GuardIpLiteralTests(unittest.TestCase):
    """IP-literal hosts are validated without a DNS lookup."""

    def test_cloud_metadata_ip_blocked(self) -> None:
        with self.assertRaises(ValueError):
            _guard_mcp_http_url("http://169.254.169.254/latest/meta-data/")

    def test_ipv4_loopback_blocked(self) -> None:
        with self.assertRaises(ValueError):
            _guard_mcp_http_url("http://127.0.0.1:8080/mcp")

    def test_ipv4_private_blocked(self) -> None:
        for url in (
            "http://10.0.0.5/mcp",
            "http://192.168.1.10/mcp",
            "http://172.16.5.5/mcp",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _guard_mcp_http_url(url)

    def test_ipv6_loopback_blocked(self) -> None:
        with self.assertRaises(ValueError):
            _guard_mcp_http_url("http://[::1]:9000/mcp")

    def test_ipv4_mapped_ipv6_metadata_blocked(self) -> None:
        # ::ffff:169.254.169.254 must be unwrapped to its IPv4 form before the check.
        with self.assertRaises(ValueError):
            _guard_mcp_http_url("http://[::ffff:169.254.169.254]/mcp")

    def test_multicast_blocked(self) -> None:
        # is_global alone treats multicast as public; it must be rejected.
        for url in ("http://224.0.0.1/mcp", "http://239.255.255.250:1900/mcp"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _guard_mcp_http_url(url)

    def test_public_ip_allowed(self) -> None:
        # Should not raise for a globally routable literal.
        _guard_mcp_http_url("https://93.184.216.34/mcp")


class GuardSchemeTests(unittest.TestCase):
    def test_non_http_scheme_blocked(self) -> None:
        for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _guard_mcp_http_url(url)

    def test_missing_host_blocked(self) -> None:
        with self.assertRaises(ValueError):
            _guard_mcp_http_url("http:///mcp")


class GuardDnsResolutionTests(unittest.TestCase):
    """Host names are resolved and every returned address must be public."""

    def test_hostname_resolving_to_private_blocked(self) -> None:
        with patch("app.services.mcp_tool_executor.socket.getaddrinfo") as m:
            m.return_value = _addrinfo("10.1.2.3")
            with self.assertRaises(ValueError):
                _guard_mcp_http_url("https://internal.example.com/mcp")

    def test_hostname_mixed_public_and_private_blocked(self) -> None:
        # A rebinding-style split answer with one private record must be rejected.
        with patch("app.services.mcp_tool_executor.socket.getaddrinfo") as m:
            m.return_value = _addrinfo("93.184.216.34", "127.0.0.1")
            with self.assertRaises(ValueError):
                _guard_mcp_http_url("https://mixed.example.com/mcp")

    def test_hostname_resolving_to_public_allowed(self) -> None:
        with patch("app.services.mcp_tool_executor.socket.getaddrinfo") as m:
            m.return_value = _addrinfo("93.184.216.34")
            _guard_mcp_http_url("https://public.example.com/mcp")

    def test_unresolvable_host_blocked(self) -> None:
        with patch("app.services.mcp_tool_executor.socket.getaddrinfo") as m:
            m.side_effect = socket.gaierror("nope")
            with self.assertRaises(ValueError):
                _guard_mcp_http_url("https://nx.invalid/mcp")


class GuardOptOutTests(unittest.TestCase):
    def test_allow_private_urls_setting_disables_guard(self) -> None:
        with patch("app.services.mcp_tool_executor.settings") as fake_settings:
            fake_settings.mcp_allow_private_urls = True
            # Private and non-http targets pass through when explicitly opted in.
            _guard_mcp_http_url("http://127.0.0.1:8080/mcp")
            _guard_mcp_http_url("http://169.254.169.254/latest/meta-data/")


class OpenTransportGuardTests(unittest.IsolatedAsyncioTestCase):
    """The guard fires inside _open_transport, before any network client opens."""

    async def test_streamable_http_private_url_rejected(self) -> None:
        conn = {"transport": "streamable_http", "url": "http://127.0.0.1:9000/mcp"}
        with self.assertRaises(ValueError):
            async with _open_transport(conn, 5.0):
                pass  # pragma: no cover - guard raises first

    async def test_sse_metadata_url_rejected(self) -> None:
        conn = {"transport": "sse", "url": "http://169.254.169.254/sse"}
        with self.assertRaises(ValueError):
            async with _open_transport(conn, 5.0):
                pass  # pragma: no cover - guard raises first


class RedirectHardeningTests(unittest.IsolatedAsyncioTestCase):
    """Redirects must be disabled so a public URL cannot bounce to an internal one."""

    async def test_streamable_http_client_disables_redirects(self) -> None:
        captured: dict = {}

        class _FakeClient:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *_exc: object) -> bool:
                return False

        @asynccontextmanager
        async def _fake_streamable(url: str, http_client: object):  # type: ignore[no-untyped-def]
            yield (MagicMock(), MagicMock(), lambda: "sid")

        conn = {
            "transport": "streamable_http",
            "url": "https://public.example.com/mcp",
            "headers": {},
        }
        with (
            patch(
                "app.services.mcp_tool_executor.socket.getaddrinfo",
                return_value=_addrinfo("93.184.216.34"),
            ),
            patch("app.services.mcp_tool_executor.httpx.AsyncClient", _FakeClient),
            patch("app.services.mcp_tool_executor.streamable_http_client", _fake_streamable),
        ):
            async with _open_transport(conn, 5.0) as pair:
                self.assertIsNotNone(pair)

        self.assertFalse(captured.get("follow_redirects", True))
        # trust_env=False keeps the dial direct so the pin governs the target.
        self.assertFalse(captured.get("trust_env", True))
        self.assertIsInstance(captured.get("verify"), ssl.SSLContext)

    async def test_sse_client_disables_redirects_and_env_proxy(self) -> None:
        captured: dict = {}

        class _FakeClient:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *_exc: object) -> bool:
                return False

        class _StopBeforeConnectError(Exception):
            pass

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise _StopBeforeConnectError()

        with (
            patch("app.services.mcp_tool_executor.httpx.AsyncClient", _FakeClient),
            patch("app.services.mcp_tool_executor.aconnect_sse", _boom),
        ):
            with self.assertRaises(BaseException):
                async with _sse_client_fail_fast("https://public.example.com/sse"):
                    pass  # pragma: no cover - the patched connect raises first

        self.assertFalse(captured.get("follow_redirects", True))
        self.assertFalse(captured.get("trust_env", True))
        self.assertIsInstance(captured.get("verify"), ssl.SSLContext)


class ResolvePinnedIpTests(unittest.TestCase):
    def test_public_literal_returned(self) -> None:
        self.assertEqual(_resolve_pinned_mcp_ip("93.184.216.34"), "93.184.216.34")

    def test_private_literal_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_pinned_mcp_ip("10.0.0.9")

    def test_hostname_pins_public_ip(self) -> None:
        with patch("app.services.mcp_tool_executor.socket.getaddrinfo") as m:
            m.return_value = _addrinfo("93.184.216.34")
            self.assertEqual(_resolve_pinned_mcp_ip("public.example.com"), "93.184.216.34")


class PinBackendTests(unittest.IsolatedAsyncioTestCase):
    """The pinning backend connects to a validated IP and blocks rebinds/unix sockets."""

    async def test_connect_tcp_pins_public_ip(self) -> None:
        inner = AsyncMock()
        inner.connect_tcp.return_value = "stream"
        backend = _McpEgressPinBackend(inner)
        with (
            patch(
                "app.services.mcp_tool_executor.socket.getaddrinfo",
                return_value=_addrinfo("93.184.216.34"),
            ),
            patch(
                "app.services.mcp_tool_executor.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda function, *args: function(*args)),
            ) as to_thread,
        ):
            result = await backend.connect_tcp("public.example.com", 443)
        self.assertEqual(result, "stream")
        to_thread.assert_awaited_once_with(_resolve_pinned_mcp_ip, "public.example.com")
        # The socket target is the validated IP, not the attacker-controlled name.
        pinned_host = inner.connect_tcp.call_args.args[0]
        self.assertEqual(pinned_host, "93.184.216.34")

    async def test_connect_tcp_blocks_dns_rebind_to_private(self) -> None:
        inner = AsyncMock()
        backend = _McpEgressPinBackend(inner)
        # A name that resolves to a private IP at dial time is refused before connect.
        with patch(
            "app.services.mcp_tool_executor.socket.getaddrinfo",
            return_value=_addrinfo("10.0.0.9"),
        ):
            with self.assertRaises(httpcore.ConnectError):
                await backend.connect_tcp("rebind.example.com", 443)
        inner.connect_tcp.assert_not_called()

    async def test_connect_unix_socket_blocked(self) -> None:
        inner = AsyncMock()
        backend = _McpEgressPinBackend(inner)
        with self.assertRaises(httpcore.ConnectError):
            await backend.connect_unix_socket("/tmp/evil.sock")
        inner.connect_unix_socket.assert_not_called()


class InstallEgressPinTests(unittest.IsolatedAsyncioTestCase):
    async def test_install_wraps_pool_backend_idempotently(self) -> None:
        async with httpx.AsyncClient() as client:
            _install_egress_pin(client)
            backend = client._transport._pool._network_backend
            self.assertIsInstance(backend, _McpEgressPinBackend)
            # Re-installing must not double-wrap.
            _install_egress_pin(client)
            self.assertIs(client._transport._pool._network_backend, backend)

    async def test_install_skipped_when_opted_out(self) -> None:
        async with httpx.AsyncClient() as client:
            with patch("app.services.mcp_tool_executor.settings") as fake_settings:
                fake_settings.mcp_allow_private_urls = True
                _install_egress_pin(client)
            self.assertNotIsInstance(client._transport._pool._network_backend, _McpEgressPinBackend)


if __name__ == "__main__":
    unittest.main()
