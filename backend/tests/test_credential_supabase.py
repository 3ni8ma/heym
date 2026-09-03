import unittest
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import (
    _merge_supabase_test_config,
    _merge_supabase_update_config,
    get_masked_value,
    get_public_credential_fields,
    list_supabase_columns,
    list_supabase_tables,
    run_credential_connection_test,
    update_credential,
    validate_credential_config,
)
from app.db.models import Credential, CredentialType
from app.models.schemas import CredentialTestRequest, CredentialUpdate


def make_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class SupabaseCredentialValidationTests(unittest.TestCase):
    def test_validate_requires_project_url(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.supabase,
                {
                    "supabase_key": "sb-secret-key",
                },
            )
        self.assertIn("supabase_url", str(ctx.exception.detail))

    def test_validate_requires_api_key(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.supabase,
                {
                    "supabase_url": "https://example.supabase.co",
                },
            )
        self.assertIn("supabase_key", str(ctx.exception.detail))

    def test_validate_accepts_complete_config(self) -> None:
        validate_credential_config(
            CredentialType.supabase,
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_key": "sb-secret-key",
                "supabase_schema": "app",
            },
        )

    def test_masked_value_includes_schema(self) -> None:
        masked = get_masked_value(
            CredentialType.supabase,
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_schema": "app",
            },
        )
        self.assertEqual(masked, "https://example.supabase.co (app)")

    def test_masked_value_defaults_schema_to_public(self) -> None:
        masked = get_masked_value(
            CredentialType.supabase,
            {
                "supabase_url": "https://example.supabase.co",
            },
        )
        self.assertEqual(masked, "https://example.supabase.co (public)")

    def test_masked_value_without_url_returns_none(self) -> None:
        masked = get_masked_value(
            CredentialType.supabase,
            {
                "supabase_schema": "public",
            },
        )
        self.assertIsNone(masked)

    def test_public_credential_fields_include_schema_defaults(self) -> None:
        public_fields = get_public_credential_fields(
            CredentialType.supabase,
            {
                "supabase_url": "https://example.supabase.co",
            },
        )
        self.assertEqual(public_fields["supabase_url"], "https://example.supabase.co")
        self.assertEqual(public_fields["supabase_schema"], "public")

    def test_public_credential_fields_omit_non_supabase_types(self) -> None:
        public_fields = get_public_credential_fields(
            CredentialType.openai,
            {
                "api_key": "secret",
            },
        )
        self.assertEqual(public_fields, {})


class SupabaseCredentialConnectionTests(unittest.TestCase):
    def test_merge_supabase_test_config_prefers_inline_values(self) -> None:
        merged = _merge_supabase_test_config(
            {
                "supabase_url": "https://new.example.supabase.co",
                "supabase_key": "",
                "supabase_schema": "app",
            },
            {
                "supabase_url": "https://old.example.supabase.co",
                "supabase_key": "stored-key",
                "supabase_schema": "public",
            },
        )
        self.assertEqual(merged["supabase_url"], "https://new.example.supabase.co")
        self.assertEqual(merged["supabase_key"], "stored-key")
        self.assertEqual(merged["supabase_schema"], "app")

    def test_merge_supabase_update_config_preserves_blank_secret(self) -> None:
        merged = _merge_supabase_update_config(
            {
                "supabase_url": "https://new.example.supabase.co",
                "supabase_key": "",
                "supabase_schema": "",
            },
            {
                "supabase_url": "https://old.example.supabase.co",
                "supabase_key": "stored-key",
                "supabase_schema": "app",
            },
        )
        self.assertEqual(merged["supabase_url"], "https://new.example.supabase.co")
        self.assertEqual(merged["supabase_key"], "stored-key")
        self.assertEqual(merged["supabase_schema"], "public")


class SupabaseCredentialConnectionApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from app.services import ssrf_guard

        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(ssrf_guard.close_guarded_http_client)

    async def test_test_connection_returns_success(self) -> None:
        user_id = uuid.uuid4()
        current_user = MagicMock(id=user_id)
        with patch(
            "app.services.supabase_service.SupabaseService.test_connection",
            return_value=None,
        ):
            result = await run_credential_connection_test(
                CredentialTestRequest(
                    type=CredentialType.supabase,
                    config={
                        "supabase_url": "https://example.supabase.co",
                        "supabase_key": "sb-secret-key",
                    },
                ),
                current_user=current_user,
                db=AsyncMock(),
            )
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Connection successful")

    async def test_test_connection_returns_failure_message(self) -> None:
        user_id = uuid.uuid4()
        current_user = MagicMock(id=user_id)
        with patch(
            "app.services.supabase_service.SupabaseService.test_connection",
            side_effect=ValueError("Supabase API key is invalid or unauthorized"),
        ):
            result = await run_credential_connection_test(
                CredentialTestRequest(
                    type=CredentialType.supabase,
                    config={
                        "supabase_url": "https://example.supabase.co",
                        "supabase_key": "bad-key",
                    },
                ),
                current_user=current_user,
                db=AsyncMock(),
            )
        self.assertFalse(result.success)
        self.assertIn("invalid or unauthorized", result.message)

    async def test_list_supabase_tables_returns_discovered_tables(self) -> None:
        user_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        current_user = MagicMock(id=user_id)
        credential = Credential(
            id=credential_id,
            owner_id=user_id,
            name="Supabase",
            type=CredentialType.supabase,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(credential))

        with patch(
            "app.api.credentials.decrypt_config",
            return_value={
                "supabase_url": "https://example.supabase.co",
                "supabase_key": "stored-key",
                "supabase_schema": "app",
            },
        ):
            with patch("app.services.supabase_service.SupabaseService.list_tables") as mock_tables:
                mock_tables.return_value = {"tables": ["profiles", "users"], "success": True}
                result = await list_supabase_tables(
                    credential_id=credential_id,
                    schema="app",
                    current_user=current_user,
                    db=db,
                )

        self.assertTrue(result.success)
        self.assertEqual(result.tables, ["profiles", "users"])
        mock_tables.assert_called_once_with(schema="app")

    async def test_list_supabase_columns_returns_discovered_columns(self) -> None:
        user_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        current_user = MagicMock(id=user_id)
        credential = Credential(
            id=credential_id,
            owner_id=user_id,
            name="Supabase",
            type=CredentialType.supabase,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(credential))

        with patch(
            "app.api.credentials.decrypt_config",
            return_value={
                "supabase_url": "https://example.supabase.co",
                "supabase_key": "stored-key",
                "supabase_schema": "public",
            },
        ):
            with patch(
                "app.services.supabase_service.SupabaseService.list_columns"
            ) as mock_columns:
                mock_columns.return_value = {"columns": ["id", "email"], "success": True}
                result = await list_supabase_columns(
                    credential_id=credential_id,
                    table="users",
                    schema="public",
                    current_user=current_user,
                    db=db,
                )

        self.assertTrue(result.success)
        self.assertEqual(result.columns, ["id", "email"])
        mock_columns.assert_called_once_with("users", schema="public")

    async def test_test_connection_merges_stored_secret_when_editing(self) -> None:
        user_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        current_user = MagicMock(id=user_id)
        credential = Credential(
            id=credential_id,
            owner_id=user_id,
            name="Supabase",
            type=CredentialType.supabase,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(credential))
        with patch(
            "app.api.credentials.decrypt_config",
            return_value={
                "supabase_url": "https://example.supabase.co",
                "supabase_key": "stored-key",
                "supabase_schema": "public",
            },
        ):
            with patch("app.services.supabase_service.SupabaseService") as mock_service_cls:
                mock_service = MagicMock()
                mock_service.test_connection.return_value = None
                mock_service_cls.return_value = mock_service
                result = await run_credential_connection_test(
                    CredentialTestRequest(
                        type=CredentialType.supabase,
                        credential_id=credential_id,
                        config={
                            "supabase_url": "https://example.supabase.co",
                            "supabase_key": "",
                            "supabase_schema": "app",
                        },
                    ),
                    current_user=current_user,
                    db=db,
                )
        self.assertTrue(result.success)
        mock_service_cls.assert_called_once_with(
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_key": "stored-key",
                "supabase_schema": "app",
            }
        )

    async def test_update_supabase_credential_preserves_secret_when_key_blank(self) -> None:
        user_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        now = datetime.now(UTC)
        current_user = MagicMock(id=user_id)
        credential = Credential(
            id=credential_id,
            owner_id=user_id,
            name="Supabase",
            type=CredentialType.supabase,
            encrypted_config="encrypted",
        )
        credential.created_at = now
        credential.updated_at = now
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(credential))

        with patch(
            "app.api.credentials.decrypt_config",
            return_value={
                "supabase_url": "https://old.example.supabase.co",
                "supabase_key": "stored-key",
                "supabase_schema": "public",
            },
        ):
            with patch(
                "app.api.credentials.encrypt_config", return_value="new-encrypted"
            ) as mock_encrypt:
                result = await update_credential(
                    credential_id=credential_id,
                    credential_data=CredentialUpdate(
                        config={
                            "supabase_url": "https://new.example.supabase.co",
                            "supabase_key": "",
                            "supabase_schema": "app",
                        },
                    ),
                    current_user=current_user,
                    db=db,
                )

        mock_encrypt.assert_called_once_with(
            {
                "supabase_url": "https://new.example.supabase.co",
                "supabase_key": "stored-key",
                "supabase_schema": "app",
            }
        )
        self.assertEqual(credential.encrypted_config, "new-encrypted")
        self.assertEqual(result.public_fields["supabase_url"], "https://new.example.supabase.co")
        self.assertEqual(result.public_fields["supabase_schema"], "app")

    async def test_test_connection_rejects_unsupported_type(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await run_credential_connection_test(
                CredentialTestRequest(
                    type=CredentialType.openai,
                    config={"api_key": "secret"},
                ),
                current_user=MagicMock(id=uuid.uuid4()),
                db=AsyncMock(),
            )
        self.assertEqual(ctx.exception.status_code, 400)
