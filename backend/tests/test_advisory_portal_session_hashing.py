"""GHSA-6x65-w7q7-wg93 finding 3: portal session tokens at rest."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.portal import _create_session, _validate_session
from app.services.secret_tokens import hash_secret


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class PortalSessionHashingTests(unittest.IsolatedAsyncioTestCase):
    async def test_created_session_stores_only_the_digest(self) -> None:
        added: list[object] = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=added.append)

        token, _ = await _create_session(db, uuid.uuid4(), "alice")

        self.assertEqual(added[0].token, hash_secret(token))
        # The browser gets the plaintext, the row never does.
        self.assertNotEqual(added[0].token, token)

    async def test_valid_token_resolves_against_the_digest(self) -> None:
        workflow_id = uuid.uuid4()
        session = SimpleNamespace(
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        captured: list[object] = []

        async def capture(statement):
            captured.append(statement)
            return _ScalarResult(session)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=capture)

        self.assertTrue(await _validate_session(db, "plain-token", workflow_id))

        compiled = str(captured[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn(hash_secret("plain-token"), compiled)
        self.assertNotIn("'plain-token'", compiled)

    async def test_stored_digest_is_not_itself_a_session_token(self) -> None:
        """Reading portal_sessions must not yield a replayable session."""
        stored = hash_secret("plain-token")
        captured: list[object] = []

        async def capture(statement):
            captured.append(statement)
            return _ScalarResult(None)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=capture)

        self.assertFalse(await _validate_session(db, stored, uuid.uuid4()))

        compiled = str(captured[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn(hash_secret(stored), compiled)
        self.assertNotIn(f"'{stored}'", compiled)

    async def test_expired_session_is_rejected_and_deleted(self) -> None:
        session = SimpleNamespace(
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(session))

        self.assertFalse(await _validate_session(db, "plain-token", uuid.uuid4()))
        db.delete.assert_awaited_once_with(session)


if __name__ == "__main__":
    unittest.main()
