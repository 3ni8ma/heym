"""Every fire-and-forget dispatch of the same sub-workflow must get its own history row.

`executeDoNotWait` dispatches a sub-workflow and the parent's run ends without it. The
API layer drains those dispatches afterwards and merges what finished late into the
result it persists. That merge is what decides how many `ExecutionHistory` rows the
sub-workflow gets, so a loop that calls the same workflow N times must produce N rows.
"""

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

TARGET_WF_ID = "33333333-3333-3333-3333-333333333333"

_TARGET_WORKFLOW = {
    "nodes": [
        {
            "id": "t1",
            "type": "textInput",
            "data": {"label": "input", "inputFields": [{"key": "text"}]},
        },
        {"id": "t2", "type": "wait", "data": {"label": "wait", "duration": 400}},
        {"id": "t3", "type": "output", "data": {"label": "output"}},
    ],
    "edges": [
        {"id": "te1", "source": "t1", "target": "t2"},
        {"id": "te2", "source": "t2", "target": "t3"},
    ],
    "name": "Target",
}

# Two dispatches of the SAME target, staggered by a parent-side wait: the first finishes
# while the parent is still running, the second only after it has ended. That is the loop
# case from the report, reduced to fixed timings so the split is not a race.
_PARENT_NODES = [
    {
        "id": "n1",
        "type": "textInput",
        "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
    },
    {
        "id": "n2",
        "type": "execute",
        "data": {
            "label": "callFirst",
            "executeWorkflowId": TARGET_WF_ID,
            "executeInput": "$userInput.body.text",
            "executeDoNotWait": True,
        },
    },
    {"id": "n3", "type": "wait", "data": {"label": "gap", "duration": 1500}},
    {
        "id": "n4",
        "type": "execute",
        "data": {
            "label": "callSecond",
            "executeWorkflowId": TARGET_WF_ID,
            "executeInput": "$userInput.body.text",
            "executeDoNotWait": True,
        },
    },
]
_PARENT_EDGES = [
    {"id": "e1", "source": "n1", "target": "n2"},
    {"id": "e2", "source": "n2", "target": "n3"},
    {"id": "e3", "source": "n3", "target": "n4"},
]


class _FakeSessionContext:
    """Stand in for ``async_session_maker()`` so the persist step runs without a DB."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class DoNotWaitHistoryRowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_dispatch_of_one_workflow_records_every_run(self) -> None:
        from app.api.workflows import execute_workflow_stream

        wf_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=wf_id,
            owner_id=uuid.uuid4(),
            name="Parent",
            nodes=_PARENT_NODES,
            edges=_PARENT_EDGES,
            sse_enabled=True,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            cache_ttl_seconds=None,
            sse_node_config={},
            workflow_timeout_seconds=None,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        request = MagicMock()
        request.method = "POST"
        request.headers = {}
        request.query_params = {}
        request.base_url = "http://localhost/"
        request.is_disconnected = AsyncMock(return_value=False)

        persist_session = AsyncMock()
        persist_session.get = AsyncMock(return_value=workflow)

        persisted: dict = {}

        async def _capture(*_args, **kwargs) -> bool:
            persisted["final_result"] = kwargs.get("final_result")
            return False

        with (
            patch(
                "app.api.workflows.parse_execute_body",
                AsyncMock(return_value=({"text": "hello"}, False, "API", False)),
            ),
            patch("app.api.workflows.validate_workflow_auth", AsyncMock(return_value=None)),
            patch("app.api.workflows.enforce_workflow_http_method", MagicMock()),
            patch(
                "app.api.workflows.collect_referenced_workflows",
                AsyncMock(return_value={TARGET_WF_ID: _TARGET_WORKFLOW}),
            ),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.workflows.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.workflows.build_public_base_url", return_value="http://localhost"),
            patch("app.api.workflows.persist_stream_execution_result", _capture),
            patch(
                "app.api.workflows.async_session_maker",
                lambda: _FakeSessionContext(persist_session),
            ),
        ):
            response = await execute_workflow_stream(
                workflow_id=wf_id,
                request=request,
                current_user=None,
                db=db,
            )
            [chunk async for chunk in response.body_iterator]

            for _ in range(200):
                if "final_result" in persisted:
                    break
                await asyncio.sleep(0.05)

        final_result = persisted.get("final_result")
        self.assertIsNotNone(final_result, "the run was never persisted")
        assert final_result is not None
        subs = final_result.get("sub_workflow_executions") or []
        self.assertEqual(
            len(subs),
            2,
            f"each dispatch of the same sub-workflow needs its own history row, got {len(subs)}",
        )
        self.assertEqual({s["workflow_id"] for s in subs}, {TARGET_WF_ID})
        self.assertEqual([s["status"] for s in subs], ["success", "success"])


if __name__ == "__main__":
    unittest.main()
