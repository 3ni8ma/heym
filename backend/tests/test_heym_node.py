"""Tests for the heym node handler."""

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import heym_node


def _ctx(node_data: dict, workflow_id: uuid.UUID | None = None) -> NodeExecutionContext:
    executor = MagicMock()
    executor.workflow_id = str(workflow_id or uuid.uuid4())
    executor.actor_user_id = uuid.uuid4()
    executor.evaluate_message_template.side_effect = lambda v, *_a, **_kw: str(v) if v else ""
    node = {"id": "n1", "type": "heym", "data": node_data}
    return NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node=node,
        node_type="heym",
        node_data=node_data,
        node_label=node_data.get("label", "heym"),
    )


def _workflow(name: str, owner_id: uuid.UUID, nodes: list | None = None) -> MagicMock:
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.name = name
    workflow.description = "desc"
    workflow.owner_id = owner_id
    workflow.active = True
    workflow.folder_id = None
    workflow.updated_at = datetime(2026, 8, 11, tzinfo=timezone.utc)
    workflow.nodes = nodes if nodes is not None else [{"id": "a", "type": "llm", "data": {}}]
    workflow.edges = []
    return workflow


class HeymNodeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.db = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = self.db
        session_cm.__exit__.return_value = False
        self.session_patcher = patch(
            "app.db.session.SessionLocal", MagicMock(return_value=session_cm)
        )
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

    def _scalars(self, rows: list) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    def _scalar_one(self, row: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        return result


class ListWorkflowsTest(HeymNodeTestBase):
    def test_lists_accessible_workflows_with_node_counts(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        other = _workflow("Other", self.owner_id, nodes=[{"id": "a"}, {"id": "b"}])
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalars([owning, other]),
        ]

        result = heym_node.execute(_ctx({"heymOperation": "listWorkflows"}))

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["workflows"][1]["node_count"], 2)
        self.assertEqual(result["workflows"][0]["name"], "Owning")

    def test_limit_caps_the_returned_rows_but_not_the_total(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        rows = [_workflow(f"W{i}", self.owner_id) for i in range(5)]
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalars(rows)]

        result = heym_node.execute(_ctx({"heymOperation": "listWorkflows", "heymLimit": "2"}))

        self.assertEqual(len(result["workflows"]), 2)
        self.assertEqual(result["total"], 5)

    def test_empty_limit_returns_every_workflow(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        rows = [_workflow(f"W{i}", self.owner_id) for i in range(5)]
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalars(rows)]

        result = heym_node.execute(_ctx({"heymOperation": "listWorkflows", "heymLimit": ""}))

        self.assertEqual(len(result["workflows"]), 5)

    def test_zero_limit_returns_every_workflow(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        rows = [_workflow(f"W{i}", self.owner_id) for i in range(5)]
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalars(rows)]

        result = heym_node.execute(_ctx({"heymOperation": "listWorkflows", "heymLimit": "0"}))

        self.assertEqual(len(result["workflows"]), 5)
        self.assertEqual(result["total"], 5)


class GetWorkflowTest(HeymNodeTestBase):
    def test_returns_full_node_configuration(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow(
            "Target",
            self.owner_id,
            nodes=[
                {
                    "id": "a",
                    "type": "llm",
                    "position": {"x": 10, "y": 20},
                    "data": {"label": "ask", "credentialId": "cred-1", "userMessage": "hi"},
                }
            ],
        )
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(target)]

        node = heym_node.execute(
            _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(target.id)})
        )["nodes"][0]

        self.assertEqual(node["id"], "a")
        self.assertEqual(node["type"], "llm")
        self.assertEqual(node["label"], "ask")
        self.assertEqual(node["position"], {"x": 10, "y": 20})
        self.assertEqual(node["data"]["credentialId"], "cred-1")
        self.assertEqual(node["data"]["userMessage"], "hi")

    def test_node_data_exposes_hardcoded_secrets_for_scanning(self) -> None:
        """The DLP case: a token pasted into a field has to be visible to be found."""
        owning = _workflow("Owning", self.owner_id)
        target = _workflow(
            "Target",
            self.owner_id,
            nodes=[{"id": "a", "type": "http", "data": {"curl": "curl -H 'key: sk-live-123'"}}],
        )
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(target)]

        result = heym_node.execute(
            _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(target.id)})
        )

        self.assertIn("sk-live-123", result["nodes"][0]["data"]["curl"])

    def test_edges_carry_their_handles(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        target.edges = [
            {"id": "e1", "source": "a", "target": "b", "sourceHandle": "true", "targetHandle": None}
        ]
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(target)]

        edge = heym_node.execute(
            _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(target.id)})
        )["edges"][0]

        self.assertEqual(edge["sourceHandle"], "true")
        self.assertIsNone(edge["targetHandle"])

    def test_inaccessible_workflow_raises(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(None)]

        with self.assertRaises(ValueError) as caught:
            heym_node.execute(
                _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(uuid.uuid4())})
            )

        self.assertIn("not found", str(caught.exception).lower())

    def test_missing_workflow_id_raises(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        self.db.execute.side_effect = [self._scalar_one(owning)]

        with self.assertRaises(ValueError):
            heym_node.execute(_ctx({"heymOperation": "getWorkflow"}))


class GetExecutionHistoryTest(HeymNodeTestBase):
    def _entries(self, rows: list) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    def _entry(self, status: str, minute: int = 0) -> MagicMock:
        entry = MagicMock()
        entry.id = uuid.uuid4()
        entry.status = status
        entry.started_at = datetime(2026, 8, 11, 12, minute, tzinfo=timezone.utc)
        entry.execution_time_ms = 1234.0
        entry.trigger_source = "manual"
        entry.recovered = False
        entry.inputs = {"text": "go"}
        entry.outputs = {"text": "done"}
        entry.node_results = [{"huge": "trace"}]
        return entry

    def test_returns_history_entries_with_a_status_breakdown(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        entries = [self._entry("success", 3), self._entry("error", 2), self._entry("success", 1)]
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalar_one(target),
            self._entries(entries),
        ]

        result = heym_node.execute(
            _ctx({"heymOperation": "getExecutionHistory", "heymWorkflowId": str(target.id)})
        )

        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["executions"]), 3)
        self.assertEqual(result["by_status"], {"success": 2, "error": 1})
        self.assertEqual(result["workflow_name"], "Target")
        self.assertIsNone(result["since"])

    def test_entry_carries_outputs_but_never_node_results(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalar_one(target),
            self._entries([self._entry("success")]),
        ]

        entry = heym_node.execute(
            _ctx({"heymOperation": "getExecutionHistory", "heymWorkflowId": str(target.id)})
        )["executions"][0]

        self.assertEqual(
            set(entry.keys()),
            {
                "id",
                "status",
                "started_at",
                "execution_time_ms",
                "trigger_source",
                "recovered",
                "inputs",
                "outputs",
            },
        )
        self.assertEqual(entry["inputs"], {"text": "go"})
        self.assertEqual(entry["outputs"], {"text": "done"})
        self.assertNotIn("node_results", entry)

    def test_limit_caps_entries_but_the_breakdown_covers_everything(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        entries = [self._entry("success", i) for i in range(5)]
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalar_one(target),
            self._entries(entries),
        ]

        result = heym_node.execute(
            _ctx(
                {
                    "heymOperation": "getExecutionHistory",
                    "heymWorkflowId": str(target.id),
                    "heymLimit": "2",
                }
            )
        )

        self.assertEqual(len(result["executions"]), 2)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["by_status"], {"success": 5})

    def test_empty_limit_returns_every_entry(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        entries = [self._entry("success", i) for i in range(5)]
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalar_one(target),
            self._entries(entries),
        ]

        result = heym_node.execute(
            _ctx({"heymOperation": "getExecutionHistory", "heymWorkflowId": str(target.id)})
        )

        self.assertEqual(len(result["executions"]), 5)

    def test_since_days_sets_the_window(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalar_one(target),
            self._entries([self._entry("success")]),
        ]

        result = heym_node.execute(
            _ctx(
                {
                    "heymOperation": "getExecutionHistory",
                    "heymWorkflowId": str(target.id),
                    "heymSinceDays": "7",
                }
            )
        )

        self.assertIsNotNone(result["since"])


class OperationValidationTest(HeymNodeTestBase):
    def test_missing_operation_raises(self) -> None:
        with self.assertRaises(ValueError) as caught:
            heym_node.execute(_ctx({"label": "heym"}))

        self.assertIn("operation", str(caught.exception).lower())

    def test_unknown_operation_raises(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        self.db.execute.side_effect = [self._scalar_one(owning)]

        with self.assertRaises(ValueError):
            heym_node.execute(_ctx({"heymOperation": "deleteEverything"}))


class OwnerResolutionTest(HeymNodeTestBase):
    def test_unsaved_workflow_id_falls_back_to_the_actor(self) -> None:
        rows = [_workflow("Mine", self.owner_id)]
        self.db.execute.side_effect = [self._scalars(rows)]
        ctx = _ctx({"heymOperation": "listWorkflows"})
        ctx.executor.workflow_id = None

        result = heym_node.execute(ctx)

        self.assertEqual(result["total"], 1)

    def test_no_resolvable_owner_raises_a_clear_error(self) -> None:
        ctx = _ctx({"heymOperation": "listWorkflows"})
        ctx.executor.workflow_id = None
        ctx.executor.actor_user_id = None

        with self.assertRaises(ValueError) as caught:
            heym_node.execute(ctx)

        self.assertIn("save the workflow", str(caught.exception).lower())
