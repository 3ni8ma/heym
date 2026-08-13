"""Terminal persistence for streamed workflow runs.

Starlette cancels the SSE response task as soon as the browser goes away, so the run's
outcome is written by a detached task instead of by the generator feeding the client.
"""

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.workflows import _spawn_detached_task, persist_stream_execution_result


def _workflow(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "name": "Workflow",
        "nodes": [],
        "cache_ttl_seconds": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _session() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


class PersistStreamExecutionResultTests(unittest.IsolatedAsyncioTestCase):
    async def _persist(
        self,
        db: AsyncMock,
        workflow: SimpleNamespace,
        *,
        final_result: dict,
        was_cancelled: bool = False,
        execution_id: uuid.UUID | None = None,
    ) -> bool:
        with (
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()) as analytics,
            patch(
                "app.api.workflows._persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            self.analytics = analytics
            return await persist_stream_execution_result(
                db,
                workflow=workflow,
                execution_id=execution_id or uuid.uuid4(),
                enriched_inputs={"body": {}},
                trigger_source="Canvas",
                raw_body={},
                query_params={},
                workflow_cache={},
                credentials_owner_id=uuid.uuid4(),
                final_result=final_result,
                was_cancelled=was_cancelled,
            )

    async def test_completed_run_is_recorded(self) -> None:
        db = _session()
        workflow = _workflow()
        execution_id = uuid.uuid4()

        written = await self._persist(
            db,
            workflow,
            execution_id=execution_id,
            final_result={
                "type": "execution_complete",
                "status": "success",
                "outputs": {"answer": 42},
                "node_results": [{"node_id": "n1", "status": "success"}],
                "execution_time_ms": 6185,
            },
        )

        self.assertTrue(written)
        db.add.assert_called_once()
        entry = db.add.call_args.args[0]
        self.assertEqual(entry.id, execution_id)
        self.assertEqual(entry.workflow_id, workflow.id)
        self.assertEqual(entry.status, "success")
        self.assertEqual(entry.outputs, {"answer": 42})
        self.assertEqual(entry.trigger_source, "Canvas")
        self.assertEqual(self.analytics.await_args.kwargs["status"], "success")

    async def test_cancelled_run_is_recorded(self) -> None:
        db = _session()
        workflow = _workflow()
        execution_id = uuid.uuid4()

        written = await self._persist(
            db,
            workflow,
            execution_id=execution_id,
            final_result={},
            was_cancelled=True,
        )

        self.assertTrue(written)
        entry = db.add.call_args.args[0]
        self.assertEqual(entry.id, execution_id)
        self.assertEqual(entry.status, "cancelled")
        self.assertEqual(self.analytics.await_args.kwargs["status"], "cancelled")

    async def test_run_that_never_completed_writes_nothing(self) -> None:
        db = _session()

        written = await self._persist(db, _workflow(), final_result={})

        self.assertFalse(written)
        db.add.assert_not_called()

    async def test_pending_run_is_left_to_the_stream(self) -> None:
        db = _session()

        written = await self._persist(
            db,
            _workflow(),
            final_result={"status": "pending", "outputs": {}, "node_results": []},
        )

        self.assertFalse(written)
        db.add.assert_not_called()

    async def test_sub_workflow_runs_are_recorded_too(self) -> None:
        db = _session()
        sub_workflow_id = uuid.uuid4()

        written = await self._persist(
            db,
            _workflow(),
            final_result={
                "status": "success",
                "outputs": {},
                "node_results": [],
                "execution_time_ms": 10,
                "sub_workflow_executions": [
                    {
                        "workflow_id": str(sub_workflow_id),
                        "inputs": {},
                        "outputs": {},
                        "status": "success",
                        "execution_time_ms": 5,
                    }
                ],
            },
        )

        self.assertTrue(written)
        self.assertEqual(db.add.call_count, 2)
        sub_entry = db.add.call_args_list[1].args[0]
        self.assertEqual(sub_entry.workflow_id, sub_workflow_id)
        self.assertEqual(sub_entry.trigger_source, "SUB_WORKFLOW")


class DetachedTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_detached_task_outlives_the_task_that_spawned_it(self) -> None:
        """A disconnect cancels the streaming task; the run's finalizer must survive it."""
        finished = asyncio.Event()

        async def finalize() -> None:
            await asyncio.sleep(0.01)
            finished.set()

        async def stream() -> None:
            _spawn_detached_task(finalize())
            await asyncio.sleep(3600)

        streaming_task = asyncio.create_task(stream())
        await asyncio.sleep(0)
        streaming_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await streaming_task

        await asyncio.wait_for(finished.wait(), timeout=2)
