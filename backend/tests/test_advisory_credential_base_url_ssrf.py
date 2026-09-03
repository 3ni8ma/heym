"""Regression tests for credential-controlled base URL SSRF."""

import asyncio
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore

from app.db.models import CredentialType
from app.services import grist_pool, ssrf_guard
from app.services.embedding import EmbeddingConfig, EmbeddingService
from app.services.github_service import GitHubService
from app.services.jira_service import JiraService
from app.services.llm_provider import fetch_custom_models
from app.services.llm_service import LLMService
from app.services.openai_client import create_guarded_openai_client
from app.services.sentry_service import SentryService
from app.services.ssrf_guard import (
    SsrfBlockedError,
    _AsyncHttpEgressPinBackend,
    _HttpEgressPinBackend,
    build_guarded_async_http_client,
    build_guarded_http_client,
)
from app.services.supabase_service import SupabaseService


def _addrinfo(ip: str) -> list:
    """Build a getaddrinfo-style result for one IPv4 address."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]


class CredentialBaseUrlPreflightTests(unittest.TestCase):
    """Every credential-derived destination is rejected before client creation."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)
        grist_pool.close_all_clients()
        self.addCleanup(grist_pool.close_all_clients)

    def test_sync_integration_clients_block_metadata_and_loopback_urls(self) -> None:
        cases = (
            (
                "jira",
                lambda: JiraService({"base_url": "http://169.254.169.254", "api_token": "secret"}),
            ),
            (
                "sentry",
                lambda: SentryService({"base_url": "http://127.0.0.1:9000", "api_token": "secret"}),
            ),
            (
                "github",
                lambda: GitHubService(
                    {"base_url": "http://169.254.169.254", "access_token": "secret"}
                ),
            ),
            (
                "grist",
                lambda: grist_pool.get_grist_client("http://127.0.0.1:8484", "secret"),
            ),
            (
                "supabase",
                lambda: SupabaseService(
                    {
                        "supabase_url": "http://169.254.169.254",
                        "supabase_key": "secret",
                    }
                ),
            ),
        )

        for name, build_client in cases:
            with self.subTest(integration=name), self.assertRaises(SsrfBlockedError):
                build_client()

    def test_custom_llm_execution_blocks_metadata_url(self) -> None:
        service = LLMService(
            CredentialType.custom,
            "secret",
            base_url="http://169.254.169.254",
        )

        with self.assertRaises(SsrfBlockedError):
            service._get_client()

    def test_custom_rag_embeddings_block_loopback_url(self) -> None:
        config = EmbeddingConfig(
            base_url="http://127.0.0.1:11434/v1",
            model="custom-embedding-model",
        )

        with self.assertRaises(SsrfBlockedError):
            EmbeddingService(config)

    def test_custom_model_discovery_does_not_create_client_for_private_url(self) -> None:
        with patch("app.services.llm_provider.build_guarded_async_http_client") as build_client:
            result = asyncio.run(fetch_custom_models("http://169.254.169.254", "secret"))

        self.assertEqual(result, [])
        build_client.assert_not_called()

    def test_guarded_openai_client_blocks_before_transport_creation(self) -> None:
        with patch("app.services.openai_client.build_guarded_http_client") as build_client:
            with self.assertRaises(SsrfBlockedError):
                create_guarded_openai_client(
                    api_key="secret",
                    base_url="http://127.0.0.1:8000/v1",
                    subject="Test credential base URL",
                )

        build_client.assert_not_called()

    def test_private_url_override_remains_the_single_opt_out(self) -> None:
        with patch.object(ssrf_guard.settings, "http_allow_private_urls", True):
            service = JiraService({"base_url": "http://127.0.0.1:8080", "api_token": "secret"})
        self.addCleanup(service.close)

        backend = service._client._transport._pool._network_backend
        self.assertNotIsInstance(backend, _HttpEgressPinBackend)


class GuardedCredentialTransportTests(unittest.IsolatedAsyncioTestCase):
    """Credential clients pin every connection, including redirect destinations."""

    def setUp(self) -> None:
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_sync_and_async_factories_install_pinning_backends(self) -> None:
        sync_client = build_guarded_http_client(follow_redirects=True)
        async_client = build_guarded_async_http_client(follow_redirects=True)
        self.addCleanup(sync_client.close)
        self.addAsyncCleanup(async_client.aclose)

        self.assertIsInstance(
            sync_client._transport._pool._network_backend,
            _HttpEgressPinBackend,
        )
        self.assertIsInstance(
            async_client._transport._pool._network_backend,
            _AsyncHttpEgressPinBackend,
        )
        self.assertFalse(sync_client._mounts)
        self.assertFalse(async_client._mounts)

    async def test_sync_backend_revalidates_a_redirect_destination(self) -> None:
        inner = MagicMock()
        backend = _HttpEgressPinBackend(inner)

        with patch.object(
            ssrf_guard.socket,
            "getaddrinfo",
            side_effect=[_addrinfo("93.184.216.34"), _addrinfo("127.0.0.1")],
        ):
            backend.connect_tcp("public.example", 443)
            with self.assertRaises(httpcore.ConnectError):
                backend.connect_tcp("redirect.example", 80)

        inner.connect_tcp.assert_called_once()

    async def test_async_backend_revalidates_a_redirect_destination(self) -> None:
        inner = MagicMock()
        inner.connect_tcp = AsyncMock(return_value=MagicMock())
        backend = _AsyncHttpEgressPinBackend(inner)

        with patch.object(
            ssrf_guard.socket,
            "getaddrinfo",
            side_effect=[_addrinfo("93.184.216.34"), _addrinfo("127.0.0.1")],
        ):
            await backend.connect_tcp("public.example", 443)
            with self.assertRaises(httpcore.ConnectError):
                await backend.connect_tcp("redirect.example", 80)

        inner.connect_tcp.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
