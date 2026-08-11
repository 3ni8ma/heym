"""Publishing and claiming Heym platform events.

Every write opens its own session. A publish that shared the caller's session
could poison the caller's transaction on failure, and the whole point of this
module is that recording an event can never break the action that produced it.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HeymEvent, HeymEventClaim
from app.db.session import async_session_maker

logger = logging.getLogger("heym_events")

EVENT_HEYM_STARTED = "heym.started"
EVENT_WORKFLOW_CREATED = "workflow.created"
EVENT_WORKFLOW_UPDATED = "workflow.updated"
EVENT_WORKFLOW_DELETED = "workflow.deleted"

KNOWN_EVENT_NAMES: tuple[str, ...] = (
    EVENT_HEYM_STARTED,
    EVENT_WORKFLOW_CREATED,
    EVENT_WORKFLOW_UPDATED,
    EVENT_WORKFLOW_DELETED,
)

HEYM_EVENT_RETENTION_DAYS = 7

# The deployment runs eight uvicorn workers, and each one reaches startup on its
# own. Without a shared key they would write eight distinct rows, and the claim
# table cannot merge distinct events - a subscriber would run eight times.
STARTED_BUCKET_SECONDS = 300


def started_dedupe_key(now: datetime, *, boot_id: str | None = None) -> str:
    """Return the shared dedupe key for a ``heym.started`` publish at ``now``.

    Keyed on the parent process plus a coarse time bucket. Every worker of one
    boot shares a parent, so they collapse onto a single row. A genuine restart
    gets a new parent and therefore a new event, even seconds later - keying on
    time alone made a quick restart look like the platform never started, which
    is exactly what someone testing the trigger does.

    Under ``--reload`` the reloader parent is stable, so a code reload correctly
    does not count as the platform starting again.
    """
    bucket = int(now.timestamp()) // STARTED_BUCKET_SECONDS
    boot = boot_id if boot_id is not None else str(os.getppid())
    return f"{EVENT_HEYM_STARTED}:{boot}:{bucket}"


def workflow_event_payload(workflow: Any, *, actor_user_id: uuid.UUID | None) -> dict[str, Any]:
    """Build the payload shared by every ``workflow.*`` event."""
    updated_at = getattr(workflow, "updated_at", None)
    return {
        "workflow_id": str(workflow.id),
        "name": workflow.name,
        "owner_id": str(workflow.owner_id) if workflow.owner_id else None,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


async def publish_event(
    *,
    name: str,
    payload: dict[str, Any],
    owner_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Append one event to the log, collapsing duplicates on ``dedupe_key``.

    Never raises. A platform event is a side observation, so a failure to record
    one must not fail the workflow save, deletion, or startup that triggered it.
    """
    stmt = (
        pg_insert(HeymEvent)
        .values(
            id=uuid.uuid4(),
            name=name,
            payload=payload,
            owner_id=owner_id,
            workflow_id=workflow_id,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(constraint="uq_heym_event_dedupe_key")
    )
    try:
        async with async_session_maker() as db:
            await db.execute(stmt)
            await db.commit()
    except Exception as e:
        logger.warning("Failed to publish heym event %s: %s", name, e)


async def claim_heym_event(
    *,
    event_id: uuid.UUID,
    workflow_id: uuid.UUID,
    node_id: str,
    worker_id: str | None = None,
) -> bool:
    """Claim one event for one subscribing node.

    Returns True only for the caller that inserted the row. Every other caller -
    another worker, another container, another machine, or this process after a
    restart - gets False and must not deliver. Fails closed: a database error
    delivers nothing.
    """
    stmt = (
        pg_insert(HeymEventClaim)
        .values(
            id=uuid.uuid4(),
            event_id=event_id,
            workflow_id=workflow_id,
            node_id=node_id,
            claimed_by=worker_id,
        )
        .on_conflict_do_nothing(constraint="uq_heym_event_claim")
        .returning(HeymEventClaim.id)
    )
    try:
        async with async_session_maker() as db:
            result = await db.execute(stmt)
            claimed = result.first() is not None
            await db.commit()
            return claimed
    except Exception as e:
        logger.warning(
            "Failed to claim heym event %s for workflow %s node %s: %s",
            event_id,
            workflow_id,
            node_id,
            e,
        )
        return False


async def release_heym_event_claims(
    *,
    event_ids: list[uuid.UUID],
    workflow_id: uuid.UUID,
    node_id: str,
) -> int:
    """Undo claims whose delivery never completed, so a later tick can retry.

    The claim is taken before the workflow runs, which is what keeps two workers
    from delivering the same event twice. The cost is that an interrupted run -
    a reload, a crash, an unexpected error - would swallow the event for good.
    Releasing the claim turns that permanent loss into a retry, bounded by the
    dispatch lookback window.
    """
    if not event_ids:
        return 0
    try:
        async with async_session_maker() as db:
            result = await db.execute(
                delete(HeymEventClaim).where(
                    HeymEventClaim.event_id.in_(event_ids),
                    HeymEventClaim.workflow_id == workflow_id,
                    HeymEventClaim.node_id == node_id,
                )
            )
            await db.commit()
            return result.rowcount or 0
    except Exception as e:
        logger.warning(
            "Failed to release heym event claims for workflow %s node %s: %s",
            workflow_id,
            node_id,
            e,
        )
        return 0


async def cleanup_heym_events(
    db: AsyncSession, *, retention_days: int = HEYM_EVENT_RETENTION_DAYS
) -> int:
    """Drop events past the retention window; their claims cascade away."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await db.execute(delete(HeymEvent).where(HeymEvent.created_at < cutoff))
    return result.rowcount or 0
