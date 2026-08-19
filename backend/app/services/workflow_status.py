"""Derive a workflow's trigger status from its stored nodes.

The dashboard listing shows one status chip per workflow. Live run state ("running") comes
from the execution registry and deletion state from ``scheduled_for_deletion``; everything
else is a pure function of the node graph, so it is computed here and returned by every
endpoint that emits a ``WorkflowListResponse``.
"""

from __future__ import annotations

from typing import Any, Literal

TriggerStatus = Literal["scheduled", "listening", "paused", "manual"]

#: Nodes that start a workflow on their own, without a caller.
TRIGGER_NODE_TYPES: frozenset[str] = frozenset(
    {
        "cron",
        "telegramTrigger",
        "slackTrigger",
        "discordTrigger",
        "imapTrigger",
        "websocketTrigger",
        "fileUploadTrigger",
        "heymTrigger",
        "pluginTrigger",
        "rabbitmq",
    }
)


def _is_active(node: dict[str, Any]) -> bool:
    data = node.get("data")
    if not isinstance(data, dict):
        return True
    return data.get("active") is not False


def compute_trigger_status(nodes: list[Any] | None) -> TriggerStatus:
    """Classify how a workflow starts.

    ``scheduled`` an active cron node exists, ``listening`` an active event trigger exists,
    ``paused`` trigger nodes exist but every one is deactivated, ``manual`` no trigger nodes.
    """
    trigger_nodes = [
        node
        for node in nodes or []
        if isinstance(node, dict) and node.get("type") in TRIGGER_NODE_TYPES
    ]
    if not trigger_nodes:
        return "manual"

    active_nodes = [node for node in trigger_nodes if _is_active(node)]
    if not active_nodes:
        return "paused"

    if any(node.get("type") == "cron" for node in active_nodes):
        return "scheduled"

    return "listening"
