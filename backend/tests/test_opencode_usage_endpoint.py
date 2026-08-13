import uuid
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import get_opencode_usage
from app.db.models import CredentialType
from app.models.schemas import OpenCodeUsageResponse


class OpenCodeUsageEndpointTest(IsolatedAsyncioTestCase):
    async def test_non_opencode_returns_400(self) -> None:
        cred = MagicMock()
        cred.type = CredentialType.codex
        with patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=cred)):
            with self.assertRaises(HTTPException) as ctx:
                await get_opencode_usage(uuid.uuid4(), current_user=MagicMock(), db=AsyncMock())
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_not_found_returns_404(self) -> None:
        with patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await get_opencode_usage(uuid.uuid4(), current_user=MagicMock(), db=AsyncMock())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_passes_credential_api_key_and_base_url(self) -> None:
        cred = MagicMock()
        cred.id = uuid.uuid4()
        cred.type = CredentialType.opencode
        cred.encrypted_config = "enc"
        expected = OpenCodeUsageResponse(available=True)
        with (
            patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=cred)),
            patch(
                "app.api.credentials.decrypt_config",
                return_value={"api_key": "sk-1", "base_url": "https://opencode.ai/zen/go/v1"},
            ),
            patch(
                "app.api.credentials.fetch_opencode_usage",
                AsyncMock(return_value=expected),
            ) as fetch,
        ):
            result = await get_opencode_usage(cred.id, current_user=MagicMock(), db=AsyncMock())
        self.assertIs(result, expected)
        self.assertEqual(fetch.await_args.kwargs["api_key"], "sk-1")
        self.assertEqual(fetch.await_args.kwargs["base_url"], "https://opencode.ai/zen/go/v1")
