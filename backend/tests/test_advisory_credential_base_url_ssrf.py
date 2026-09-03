"""Regression tests for credential-controlled base URL SSRF."""

import asyncio
import os
import socket
import ssl
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import httpx
from fastapi import HTTPException

from app.api.credentials import get_credential_models
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
            with self.assertRaises(SsrfBlockedError):
                asyncio.run(fetch_custom_models("http://169.254.169.254", "secret"))

        build_client.assert_not_called()

    def test_private_url_rejection_explains_the_self_hosted_opt_out(self) -> None:
        with self.assertRaises(SsrfBlockedError) as raised:
            ssrf_guard.guard_http_url(
                "http://127.0.0.1:11434/v1",
                "Custom LLM credential base URL",
            )

        self.assertIn("HEYM_HTTP_ALLOW_PRIVATE_URLS=true", str(raised.exception))

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
        async_client = await build_guarded_async_http_client(follow_redirects=True)
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

    async def test_guarded_factories_keep_environment_ca_bundle_without_proxies(self) -> None:
        default_certificates = httpx.create_ssl_context(trust_env=False).get_ca_certs(
            binary_form=True
        )
        self.assertTrue(default_certificates)
        expected_certificate = default_certificates[0]

        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle_path = Path(temporary_directory) / "operator-ca.pem"
            bundle_path.write_text(
                ssl.DER_cert_to_PEM_cert(expected_certificate),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"SSL_CERT_FILE": str(bundle_path)},
                clear=True,
            ):
                sync_client = build_guarded_http_client()
                async_client = await build_guarded_async_http_client()

        self.addCleanup(sync_client.close)
        self.addAsyncCleanup(async_client.aclose)
        sync_context = sync_client._transport._pool._ssl_context
        async_context = async_client._transport._pool._ssl_context
        self.assertIn(expected_certificate, sync_context.get_ca_certs(binary_form=True))
        self.assertIn(expected_certificate, async_context.get_ca_certs(binary_form=True))
        self.assertFalse(sync_client._mounts)
        self.assertFalse(async_client._mounts)

    async def test_async_factory_closes_client_when_pin_installation_fails(self) -> None:
        client = httpx.AsyncClient(trust_env=False)
        with (
            patch.object(ssrf_guard.httpx, "AsyncClient", return_value=client),
            patch.object(
                ssrf_guard,
                "_install_async_egress_pin",
                side_effect=RuntimeError("pin unavailable"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "pin unavailable"):
                await build_guarded_async_http_client()

        self.assertTrue(client.is_closed)

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


class CredentialModelListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_custom_model_url_is_an_http_400(self) -> None:
        credential = MagicMock(
            type=CredentialType.custom,
            encrypted_config="encrypted",
        )
        query_result = MagicMock()
        query_result.scalar_one_or_none.return_value = credential
        db = AsyncMock()
        db.execute.return_value = query_result
        current_user = MagicMock(id=uuid.uuid4())

        with (
            patch(
                "app.api.credentials.decrypt_config",
                return_value={"base_url": "http://127.0.0.1:11434", "api_key": "secret"},
            ),
            patch(
                "app.services.llm_provider.fetch_models",
                new=AsyncMock(side_effect=SsrfBlockedError("Custom LLM URL is not allowed")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await get_credential_models(uuid.uuid4(), current_user, db)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Custom LLM URL is not allowed")


class GitHubGuardCoverageTests(unittest.TestCase):
    def test_service_copies_config_and_prechecks_uploads_origin(self) -> None:
        config = {"base_url": "https://api.github.com", "api_key": "secret"}
        client = MagicMock()

        with (
            patch("app.services.github_service.guard_http_url") as guard_url,
            patch(
                "app.services.github_service.build_guarded_http_client",
                return_value=client,
            ),
        ):
            service = GitHubService(config)

        config["base_url"] = "http://127.0.0.1"
        self.assertEqual(service._base_url(), "https://api.github.com")
        guard_url.assert_any_call("https://api.github.com", "GitHub credential base URL")
        guard_url.assert_any_call("https://uploads.github.com", "GitHub credential uploads URL")


if __name__ == "__main__":
    unittest.main()
