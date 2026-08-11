"""Tests for the heymTrigger node handler."""

import unittest
from unittest.mock import MagicMock

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes.heym_trigger_node import execute


def _ctx(node_data: dict) -> NodeExecutionContext:
    node = {"id": "n1", "type": "heymTrigger", "data": node_data}
    return NodeExecutionContext(
        executor=MagicMock(),
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node=node,
        node_type="heymTrigger",
        node_data=node_data,
        node_label=node_data.get("label", "heymTrigger"),
    )


class HeymTriggerNodeTest(unittest.TestCase):
    def test_returns_the_batched_events(self) -> None:
        result = execute(
            _ctx(
                {
                    "label": "platformEvents",
                    "_initial_inputs": {
                        "triggered_at": "2026-08-11T12:00:00+00:00",
                        "events": [
                            {"id": "e1", "name": "workflow.created"},
                            {"id": "e2", "name": "workflow.updated"},
                        ],
                    },
                }
            )
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["events"][0]["name"], "workflow.created")
        self.assertEqual(result["triggered_at"], "2026-08-11T12:00:00+00:00")

    def test_single_event_is_still_an_array(self) -> None:
        result = execute(
            _ctx({"_initial_inputs": {"events": [{"id": "e1", "name": "heym.started"}]}})
        )

        self.assertIsInstance(result["events"], list)
        self.assertEqual(result["count"], 1)

    def test_missing_initial_inputs_yields_an_empty_batch(self) -> None:
        result = execute(_ctx({"label": "platformEvents"}))

        self.assertEqual(result["events"], [])
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["triggered_at"])
