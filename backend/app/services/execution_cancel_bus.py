"""Cross-worker execution cancel signalling over Postgres LISTEN/NOTIFY.

A cancel used to reach the worker running an execution only through
`active_workflow_executions.cancel_requested_at`, which the owning worker polls
every registry tick. That has two problems under `uvicorn --workers N`: the HTTP
request almost never lands on the worker that owns the execution, and the poll
reads the busiest table in the schema, so when that table is unreadable the stop
never arrives and the run keeps going.

`NOTIFY` does not touch the table, so it delivers the stop independently. The
database poll stays in place as the fallback for a worker that was reconnecting
when the signal fired. This mirrors `chat_task_registry`, which already solves
the same cross-worker delivery problem the same way.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

import asyncpg
import sqlalchemy as sa

from app.db.session import libpq_dsn
from app.services.execution_cancellation import cancel_execution

logger = logging.getLogger(__name__)

CANCEL_CHANNEL = "heym_execution_cancel"
# The listener holds one long-lived connection, and this deployment's database
# restarts on its own, so a dropped socket has to be re-established rather than
# silently ending the loop.
_RECONNECT_DELAY_SECONDS = 2.0
# asyncpg surfaces a dead connection only on use; poke it so a socket that died
# quietly is noticed instead of leaving the worker deaf to cancels.
_CONNECTION_PROBE_SECONDS = 15.0


def encode_cancel_payload(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> str:
    return f"{workflow_id}:{execution_id}"


def decode_cancel_payload(payload: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    workflow_raw, _, execution_raw = str(payload).partition(":")
    try:
        return uuid.UUID(workflow_raw), uuid.UUID(execution_raw)
    except (AttributeError, TypeError, ValueError):
        return None


async def publish_execution_cancel(
    session: Any,
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
) -> None:
    """Broadcast a cancel to every worker. Delivered when the transaction commits.

    Uses ``pg_notify`` rather than the ``NOTIFY`` statement because only the
    function form accepts bind parameters.
    """
    await session.execute(
        sa.text("SELECT pg_notify(:channel, :payload)"),
        {
            "channel": CANCEL_CHANNEL,
            "payload": encode_cancel_payload(workflow_id, execution_id),
        },
    )


class ExecutionCancelListener:
    """Applies cancel broadcasts to whichever worker actually owns the execution."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Execution cancel listener started (channel=%s)", CANCEL_CHANNEL)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._connected = False
        logger.info("Execution cancel listener stopped")

    def handle_payload(self, payload: str) -> bool:
        """Apply one broadcast locally. Returns True when this worker owned the run."""
        decoded = decode_cancel_payload(payload)
        if decoded is None:
            logger.warning("Ignoring malformed execution cancel payload %r", payload)
            return False
        workflow_id, execution_id = decoded
        cancelled = cancel_execution(workflow_id=workflow_id, execution_id=execution_id)
        if cancelled:
            logger.info("Cancelled execution %s from cancel broadcast", execution_id)
        return cancelled

    def _on_notify(self, _connection: Any, _pid: int, _channel: str, payload: str) -> None:
        # asyncpg runs this on the event loop; cancel_execution only sets a
        # threading.Event, so it never blocks here.
        try:
            self.handle_payload(payload)
        except Exception:
            logger.exception("Execution cancel broadcast handling failed")

    async def _run_loop(self) -> None:
        while self._running:
            connection: asyncpg.Connection | None = None
            try:
                connection = await asyncpg.connect(libpq_dsn())
                await connection.add_listener(CANCEL_CHANNEL, self._on_notify)
                self._connected = True
                logger.info("Execution cancel listener connected")
                while self._running:
                    await asyncio.sleep(_CONNECTION_PROBE_SECONDS)
                    await connection.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Execution cancel listener disconnected (%s); retrying in %.0fs",
                    exc,
                    _RECONNECT_DELAY_SECONDS,
                )
            finally:
                self._connected = False
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
            if self._running:
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


execution_cancel_listener = ExecutionCancelListener()
