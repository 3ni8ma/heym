"""Postgres-backed broadcast registry for background dashboard chat streams.

The previous implementation kept conversation streams in a per-process dict,
which broke under `uvicorn --workers N` (the POST that started the task and the
GET that subscribed to it could land on different workers). This implementation
uses a `chat_stream_events` table for durable replay plus Postgres
`LISTEN`/`NOTIFY` to wake up subscribers in any worker.

Wire-format compatibility: events are serialized to SSE-formatted strings at
publish time, so consumers receive `str` payloads (already `data: ...\\n\\n`)
or `None` to signal stream completion.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import sqlalchemy as sa

from app.db.session import async_session_maker, libpq_dsn

ChatEvent = str | dict[str, Any]
logger = logging.getLogger(__name__)


def _channel_name(conv_id: str) -> str:
    """Build a Postgres NOTIFY channel name for a conversation.

    Channel names are limited to NAMEDATALEN (63 chars). `chat_stream_` (12) +
    UUID hex without hyphens (32) = 44 chars, well under the limit.
    """
    return f"chat_stream_{conv_id.replace('-', '_').replace('+', '_')}"


def _serialize_event(event: ChatEvent) -> str:
    if isinstance(event, str):
        return event
    return f"data: {json.dumps(event)}\n\n"


async def create_task(conv_id: str) -> None:
    """Wipe any previous events for this conversation; start a fresh slot.

    Bounds per-conversation storage to at most one stream's worth of events.
    """
    async with async_session_maker() as session:
        await session.execute(
            sa.text("DELETE FROM chat_stream_events WHERE conversation_id = CAST(:cid AS uuid)"),
            {"cid": conv_id},
        )
        await session.commit()


async def has_task(conv_id: str) -> bool:
    """Return True if a chat task is currently active for this conversation.

    "Active" means either:
      - the conversation row's `is_running` flag is true (a task was just
        created and may not have published its first event yet), or
      - there are still events in the stream table that no consumer has
        observed and acknowledged (we don't delete on consume, so this is
        any rows at all).
    """
    async with async_session_maker() as session:
        result = await session.execute(
            sa.text(
                "SELECT "
                "  COALESCE((SELECT is_running FROM dashboard_conversations "
                "            WHERE id = CAST(:cid AS uuid)), FALSE) "
                "  OR EXISTS (SELECT 1 FROM chat_stream_events "
                "             WHERE conversation_id = CAST(:cid AS uuid))"
            ),
            {"cid": conv_id},
        )
        return bool(result.scalar())


async def remove_task(conv_id: str) -> None:
    async with async_session_maker() as session:
        await session.execute(
            sa.text("DELETE FROM chat_stream_events WHERE conversation_id = CAST(:cid AS uuid)"),
            {"cid": conv_id},
        )
        await session.commit()


async def publish(conv_id: str, event: ChatEvent) -> None:
    payload = _serialize_event(event)
    channel = _channel_name(conv_id)
    async with async_session_maker() as session:
        await session.execute(
            sa.text(
                "INSERT INTO chat_stream_events (conversation_id, payload, is_done) "
                "VALUES (CAST(:cid AS uuid), :payload, FALSE)"
            ),
            {"cid": conv_id, "payload": payload},
        )
        # NOTIFY is delivered when the transaction commits.
        await session.execute(sa.text(f'NOTIFY "{channel}"'))
        await session.commit()


async def finish(conv_id: str) -> None:
    channel = _channel_name(conv_id)
    async with async_session_maker() as session:
        await session.execute(
            sa.text(
                "INSERT INTO chat_stream_events (conversation_id, payload, is_done) "
                "VALUES (CAST(:cid AS uuid), '', TRUE)"
            ),
            {"cid": conv_id},
        )
        await session.execute(sa.text(f'NOTIFY "{channel}"'))
        await session.commit()


async def subscriber_count(conv_id: str) -> int:
    """Not tracked across workers under the Postgres-backed registry.

    Callers used this to set `has_unread = (count == 0)`; we now always mark
    such conversations as unread on finish, and rely on the frontend's
    markConversationRead path to clear it when the user views the chat.
    """
    return 0


@asynccontextmanager
async def subscribe(
    conv_id: str,
) -> AsyncGenerator[asyncio.Queue[ChatEvent | None] | None, None]:
    """Subscribe to a conversation stream.

    Yields a `Queue[str | None]` that emits SSE-formatted strings and a final
    `None` to signal completion. Yields `None` (instead of a queue) when no
    task ever existed for this conversation, matching the previous semantics.
    """
    if not await has_task(conv_id):
        yield None
        return

    queue: asyncio.Queue[ChatEvent | None] = asyncio.Queue()
    channel = _channel_name(conv_id)
    listen_conn: asyncpg.Connection | None = None
    listener_task: asyncio.Task[None] | None = None
    last_seq = 0
    notify_wakeup = asyncio.Event()

    async def fetch_new_events() -> bool:
        """Push newly-arrived events to the queue. Return True after `done`."""
        nonlocal last_seq
        async with async_session_maker() as session:
            result = await session.execute(
                sa.text(
                    "SELECT sequence, payload, is_done FROM chat_stream_events "
                    "WHERE conversation_id = CAST(:cid AS uuid) AND sequence > :last "
                    "ORDER BY sequence"
                ),
                {"cid": conv_id, "last": last_seq},
            )
            rows = result.all()
        saw_done = False
        for row in rows:
            last_seq = row.sequence
            if row.is_done:
                await queue.put(None)
                saw_done = True
            else:
                await queue.put(row.payload)
        return saw_done

    async def listener() -> None:
        try:
            while True:
                await notify_wakeup.wait()
                notify_wakeup.clear()
                if await fetch_new_events():
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat stream listener crashed for conv_id=%s", conv_id)
            with contextlib.suppress(Exception):
                await queue.put(None)

    def on_notify(*_args: Any) -> None:
        notify_wakeup.set()

    try:
        listen_conn = await asyncpg.connect(libpq_dsn())
        await listen_conn.add_listener(channel, on_notify)
        # Drain whatever already exists before yielding the queue so the consumer
        # never misses early events that arrived before LISTEN was attached.
        if await fetch_new_events():
            yield queue
            return
        # Schedule another drain in case a NOTIFY fired between the initial
        # fetch and add_listener — set the wakeup so the listener picks it up.
        notify_wakeup.set()
        listener_task = asyncio.create_task(listener())
        yield queue
    finally:
        if listener_task is not None:
            listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener_task
        if listen_conn is not None:
            with contextlib.suppress(Exception):
                await listen_conn.remove_listener(channel, on_notify)
            with contextlib.suppress(Exception):
                await listen_conn.close()
