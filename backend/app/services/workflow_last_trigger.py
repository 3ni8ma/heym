"""Look up how each workflow was last started.

A workflow without trigger nodes gets the plain "manual" chip in the listing, which is wrong for
workflows that are actually driven by an HTTP call or by a parent workflow. The most recent
``execution_history`` row says which, so the endpoints that emit a ``WorkflowListResponse``
resolve it here and hand it to ``refine_manual_status``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionHistory


async def fetch_last_trigger_sources(
    db: AsyncSession, workflow_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """Latest ``trigger_source`` per workflow, resolved in a single DISTINCT ON query."""
    ids = list({workflow_id for workflow_id in workflow_ids if workflow_id is not None})
    if not ids:
        return {}

    result = await db.execute(
        select(ExecutionHistory.workflow_id, ExecutionHistory.trigger_source)
        .where(ExecutionHistory.workflow_id.in_(ids))
        .distinct(ExecutionHistory.workflow_id)
        .order_by(ExecutionHistory.workflow_id, ExecutionHistory.started_at.desc())
    )
    return {row.workflow_id: row.trigger_source for row in result.all()}


async def fetch_last_trigger_source(db: AsyncSession, workflow_id: uuid.UUID) -> str | None:
    """Latest ``trigger_source`` for one workflow."""
    sources = await fetch_last_trigger_sources(db, [workflow_id])
    return sources.get(workflow_id)
