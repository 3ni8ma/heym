from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the heymTrigger node."""
    node_data = ctx.node_data

    trigger_inputs = node_data.get("_initial_inputs", {})
    events = trigger_inputs.get("events") or []
    return {
        "events": events,
        "count": len(events),
        "triggered_at": trigger_inputs.get("triggered_at"),
    }
