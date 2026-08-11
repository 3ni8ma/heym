"""Tests for the Heym platform event publisher and delivery claims."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import heym_event_service


class StartedDedupeKeyTest(unittest.TestCase):
    def test_workers_inside_one_bucket_share_a_key(self) -> None:
        base = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
        keys = {
            heym_event_service.started_dedupe_key(base + timedelta(seconds=offset))
            for offset in (0, 7, 61, 299)
        }

        self.assertEqual(len(keys), 1)

    def test_next_bucket_gets_a_different_key(self) -> None:
        base = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)

        self.assertNotEqual(
            heym_event_service.started_dedupe_key(base),
            heym_event_service.started_dedupe_key(base + timedelta(seconds=300)),
        )

    def test_a_restart_seconds_later_still_publishes(self) -> None:
        """A new boot has a new parent process, so a quick restart is a real start."""
        base = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)

        self.assertNotEqual(
            heym_event_service.started_dedupe_key(base, boot_id="1000"),
            heym_event_service.started_dedupe_key(base + timedelta(seconds=3), boot_id="1001"),
        )

    def test_workers_of_one_boot_share_a_key(self) -> None:
        base = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
        keys = {
            heym_event_service.started_dedupe_key(base + timedelta(seconds=offset), boot_id="1000")
            for offset in range(8)
        }

        self.assertEqual(len(keys), 1)


class PublishEventTest(unittest.IsolatedAsyncioTestCase):
    def _session(self) -> tuple[MagicMock, AsyncMock]:
        db = AsyncMock()
        maker = MagicMock()
        maker.return_value.__aenter__.return_value = db
        maker.return_value.__aexit__.return_value = False
        return maker, db

    async def test_publish_inserts_and_commits(self) -> None:
        maker, db = self._session()
        with patch.object(heym_event_service, "async_session_maker", maker):
            await heym_event_service.publish_event(
                name=heym_event_service.EVENT_WORKFLOW_CREATED,
                payload={"workflow_id": "w1"},
                owner_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                dedupe_key="workflow.created:w1",
            )

        db.execute.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_publish_swallows_database_errors(self) -> None:
        maker, db = self._session()
        db.execute.side_effect = RuntimeError("connection reset")

        with patch.object(heym_event_service, "async_session_maker", maker):
            await heym_event_service.publish_event(
                name=heym_event_service.EVENT_HEYM_STARTED,
                payload={},
            )

        # No exception escaped: a failed publish must never break the caller.


class ClaimHeymEventTest(unittest.IsolatedAsyncioTestCase):
    def _session(self, first_row: object) -> tuple[MagicMock, AsyncMock]:
        db = AsyncMock()
        result = MagicMock()
        result.first.return_value = first_row
        db.execute.return_value = result
        maker = MagicMock()
        maker.return_value.__aenter__.return_value = db
        maker.return_value.__aexit__.return_value = False
        return maker, db

    async def test_first_claim_wins(self) -> None:
        maker, db = self._session(first_row=(uuid.uuid4(),))

        with patch.object(heym_event_service, "async_session_maker", maker):
            claimed = await heym_event_service.claim_heym_event(
                event_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                node_id="n1",
            )

        self.assertTrue(claimed)
        db.commit.assert_awaited_once()

    async def test_second_claim_loses(self) -> None:
        maker, _db = self._session(first_row=None)

        with patch.object(heym_event_service, "async_session_maker", maker):
            claimed = await heym_event_service.claim_heym_event(
                event_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                node_id="n1",
            )

        self.assertFalse(claimed)

    async def test_claim_fails_closed_on_error(self) -> None:
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("deadlock")
        maker = MagicMock()
        maker.return_value.__aenter__.return_value = db
        maker.return_value.__aexit__.return_value = False

        with patch.object(heym_event_service, "async_session_maker", maker):
            claimed = await heym_event_service.claim_heym_event(
                event_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                node_id="n1",
            )

        self.assertFalse(claimed)


class CleanupTest(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_deletes_past_the_retention_window(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 3
        db.execute.return_value = result

        deleted = await heym_event_service.cleanup_heym_events(db)

        self.assertEqual(deleted, 3)
        db.execute.assert_awaited_once()


class WorkflowEventPayloadTest(unittest.TestCase):
    def test_payload_carries_identity_and_actor(self) -> None:
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.name = "Nightly report"
        workflow.owner_id = uuid.uuid4()
        workflow.updated_at = datetime(2026, 8, 11, 9, 30, tzinfo=timezone.utc)
        actor_id = uuid.uuid4()

        payload = heym_event_service.workflow_event_payload(workflow, actor_user_id=actor_id)

        self.assertEqual(payload["workflow_id"], str(workflow.id))
        self.assertEqual(payload["name"], "Nightly report")
        self.assertEqual(payload["owner_id"], str(workflow.owner_id))
        self.assertEqual(payload["actor_user_id"], str(actor_id))
        self.assertEqual(payload["updated_at"], "2026-08-11T09:30:00+00:00")

    def test_payload_tolerates_a_missing_updated_at(self) -> None:
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.name = "Draft"
        workflow.owner_id = uuid.uuid4()
        workflow.updated_at = None

        payload = heym_event_service.workflow_event_payload(workflow, actor_user_id=None)

        self.assertIsNone(payload["updated_at"])
        self.assertIsNone(payload["actor_user_id"])


class ReleaseClaimsTest(unittest.IsolatedAsyncioTestCase):
    async def test_release_deletes_the_claims(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 2
        db.execute.return_value = result
        maker = MagicMock()
        maker.return_value.__aenter__.return_value = db
        maker.return_value.__aexit__.return_value = False

        with patch.object(heym_event_service, "async_session_maker", maker):
            released = await heym_event_service.release_heym_event_claims(
                event_ids=[uuid.uuid4(), uuid.uuid4()],
                workflow_id=uuid.uuid4(),
                node_id="n1",
            )

        self.assertEqual(released, 2)
        db.commit.assert_awaited_once()

    async def test_release_without_events_touches_nothing(self) -> None:
        maker = MagicMock()

        with patch.object(heym_event_service, "async_session_maker", maker):
            released = await heym_event_service.release_heym_event_claims(
                event_ids=[], workflow_id=uuid.uuid4(), node_id="n1"
            )

        self.assertEqual(released, 0)
        maker.assert_not_called()
