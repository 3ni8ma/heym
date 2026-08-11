# Heym Node + Internal Event Bus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `heym` action node that reads Heym's own workflow and execution data, and a `heymTrigger` node that starts workflows from platform events delivered exactly once per subscriber across every worker, container, and machine.

**Architecture:** An append-only `heym_events` table is written by a publisher that never raises. A background dispatcher polls every 5 seconds, matches events to `heymTrigger` nodes, claims each pair through a unique constraint in `heym_event_claims`, and starts one workflow run per subscriber carrying all claimed events in one array. The `heym` action node reads workflows and execution history through the owning workflow's `owner_id` using a shared access clause.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async engine for services, sync `SessionLocal` for node handlers), Alembic, PostgreSQL 16, pytest; Vue 3 + TypeScript strict on the frontend; Next.js + Bun for heymweb.

**Spec:** `docs/superpowers/specs/2026-08-11-heym-node-and-event-bus-design.md`

**Delivery constraint — read before touching anything:** do **not** commit, do **not** push, do **not** open a PR. Every change in both repositories stays in the working tree as an uncommitted diff until the user decides otherwise. Each task ends in a checkpoint step that only runs `git status` to confirm the expected files changed. If a hook or script would create a commit, skip that step and report it instead.

---

## Conventions used by every task

Run backend tests from the repo root unless a step says otherwise:

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/<file> -v
```

`HEYM_OTEL_ENABLED=false` is mandatory. The local `.env` turns OpenTelemetry on with no collector listening, and the suite hangs forever without this override.

Never run `./check.sh` and `./run_tests.sh` at the same time — each spawns 189 parallel pytest workers.

## File Structure

**Created (backend)**

| File | Responsibility |
| --- | --- |
| `backend/app/services/workflow_access.py` | The single `workflow_access_clause(user_id)` expression shared by the API and the node |
| `backend/app/services/heym_event_service.py` | Event names, retention constants, `publish_event`, `claim_heym_event`, `cleanup_heym_events` |
| `backend/app/services/heym_event_dispatcher.py` | Pure matching helpers plus the `HeymEventDispatcher` poll loop and workflow execution |
| `backend/app/services/node_execution/nodes/heym_node.py` | `heym` handler: `listWorkflows`, `getWorkflow`, `countExecutions` |
| `backend/app/services/node_execution/nodes/heym_trigger_node.py` | `heymTrigger` handler: reads `_initial_inputs`, returns the events array |
| `backend/alembic/versions/107_add_heym_events.py` | `heym_events` + `heym_event_claims` |
| `backend/tests/test_workflow_access.py` | Access clause shape |
| `backend/tests/test_heym_event_service.py` | Publish, dedupe, claim, cleanup |
| `backend/tests/test_heym_event_dispatcher.py` | Matching, batching, lookback, visibility |
| `backend/tests/test_heym_node.py` | Three operations and access scoping |
| `backend/tests/test_heym_trigger_node.py` | Trigger output shape |

**Created (frontend)**

| File | Responsibility |
| --- | --- |
| `frontend/src/components/Panels/propertiesPanel/nodes/HeymNodeProperties.vue` | `heym` node form |
| `frontend/src/components/Panels/propertiesPanel/nodes/HeymTriggerNodeProperties.vue` | `heymTrigger` node form |
| `frontend/src/docs/content/nodes/heym-node.md` | Node docs page |
| `frontend/src/docs/content/nodes/heym-trigger-node.md` | Trigger docs page |

**Modified:** `backend/app/db/models.py`, `backend/app/api/workflows.py`, `backend/app/main.py`, `backend/app/services/workflow_executor.py`, `backend/app/services/node_execution/registry.py`, `backend/app/services/workflow_dsl_prompt.py`, twelve frontend registration files, `frontend/src/docs/manifest.ts`, three heymrun reference docs, and seven heymweb files.

---

### Task 1: Database models and migration

**Files:**
- Modify: `backend/app/db/models.py` (append after `CronSlotClaim`, which ends at line 1698)
- Create: `backend/alembic/versions/107_add_heym_events.py`

- [ ] **Step 1: Add both models**

Append to `backend/app/db/models.py` immediately after the `CronSlotClaim` class (before `class AgentMemoryNode`):

```python
class HeymEvent(Base):
    """Append-only log of platform events that workflows can subscribe to.

    ``workflow_id`` deliberately carries no foreign key: a ``workflow.deleted``
    event names a row that no longer exists, and a cascade would delete the very
    event that reports the deletion.
    """

    __tablename__ = "heym_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_heym_event_dedupe_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class HeymEventClaim(Base):
    """One row per (event, subscribing node) pair that has already been delivered.

    Same contract as ``CronSlotClaim``: in-memory state is per worker, so the only
    place that can answer "has anyone delivered this yet?" is Postgres. The unique
    constraint makes the first inserter the sole deliverer, across workers,
    containers, and machines.
    """

    __tablename__ = "heym_event_claims"
    __table_args__ = (
        UniqueConstraint("event_id", "workflow_id", "node_id", name="uq_heym_event_claim"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("heym_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
```

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/107_add_heym_events.py`:

```python
"""add heym events and delivery claims

Revision ID: 107_add_heym_events
Revises: 106_add_mcp_chat_tool
Create Date: 2026-08-11 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "107_add_heym_events"
down_revision: Union[str, None] = "106_add_mcp_chat_tool"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "heym_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("payload", JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_id", UUID(as_uuid=True), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_heym_event_dedupe_key"),
    )
    op.create_index("ix_heym_events_name", "heym_events", ["name"])
    op.create_index("ix_heym_events_owner_id", "heym_events", ["owner_id"])
    op.create_index("ix_heym_events_workflow_id", "heym_events", ["workflow_id"])
    op.create_index("ix_heym_events_created_at", "heym_events", ["created_at"])

    op.create_table(
        "heym_event_claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("heym_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_id", UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", "workflow_id", "node_id", name="uq_heym_event_claim"),
    )
    op.create_index("ix_heym_event_claims_event_id", "heym_event_claims", ["event_id"])
    op.create_index("ix_heym_event_claims_workflow_id", "heym_event_claims", ["workflow_id"])
    op.create_index("ix_heym_event_claims_claimed_at", "heym_event_claims", ["claimed_at"])


def downgrade() -> None:
    op.drop_index("ix_heym_event_claims_claimed_at", table_name="heym_event_claims")
    op.drop_index("ix_heym_event_claims_workflow_id", table_name="heym_event_claims")
    op.drop_index("ix_heym_event_claims_event_id", table_name="heym_event_claims")
    op.drop_table("heym_event_claims")
    op.drop_index("ix_heym_events_created_at", table_name="heym_events")
    op.drop_index("ix_heym_events_workflow_id", table_name="heym_events")
    op.drop_index("ix_heym_events_owner_id", table_name="heym_events")
    op.drop_index("ix_heym_events_name", table_name="heym_events")
    op.drop_table("heym_events")
```

- [ ] **Step 3: Apply and verify the migration**

```bash
cd backend && uv run alembic upgrade head && uv run alembic current
```

Expected: `107_add_heym_events (head)`.

- [ ] **Step 4: Verify the downgrade path, then re-upgrade**

```bash
cd backend && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: both commands exit 0. A failure here means an index or constraint name is wrong.

- [ ] **Step 5: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 2: Shared workflow access clause

The subquery that answers "which workflows can this user reach?" is inlined three times in `backend/app/api/workflows.py` (lines 348-360, 568-581, and 627-640). The `heym` node needs the same answer from a synchronous session, so it moves into a session-agnostic module and the three call sites start using it.

**Files:**
- Create: `backend/app/services/workflow_access.py`
- Create: `backend/tests/test_workflow_access.py`
- Modify: `backend/app/api/workflows.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflow_access.py`:

```python
"""Tests for the shared workflow access clause."""

import unittest
import uuid

from sqlalchemy import select

from app.db.models import Workflow
from app.services.workflow_access import workflow_access_clause


class WorkflowAccessClauseTest(unittest.TestCase):
    def test_clause_covers_owner_user_share_and_team_share(self) -> None:
        user_id = uuid.uuid4()
        sql = str(select(Workflow.id).where(workflow_access_clause(user_id)))

        self.assertIn("workflows.owner_id", sql)
        self.assertIn("workflow_shares", sql)
        self.assertIn("workflow_team_shares", sql)
        self.assertIn("team_members", sql)

    def test_clause_is_an_or_of_three_branches(self) -> None:
        user_id = uuid.uuid4()
        clause = workflow_access_clause(user_id)

        self.assertEqual(len(clause.clauses), 3)
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_workflow_access.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.workflow_access'`.

- [ ] **Step 3: Write the module**

Create `backend/app/services/workflow_access.py`:

```python
"""The single definition of which workflows a user can reach.

Both the async API layer and the synchronous node handlers need this answer, so
it is expressed as a SQLAlchemy clause rather than an executed query — the
caller supplies the session and the engine.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import TeamMember, Workflow, WorkflowShare, WorkflowTeamShare


def workflow_access_clause(user_id: uuid.UUID) -> ColumnElement[bool]:
    """Return the WHERE clause matching every workflow ``user_id`` can reach.

    A user reaches a workflow by owning it, by holding a direct share, or by
    belonging to a team the workflow is shared with.
    """
    return or_(
        Workflow.owner_id == user_id,
        Workflow.id.in_(select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)),
        Workflow.id.in_(
            select(WorkflowTeamShare.workflow_id).where(
                WorkflowTeamShare.team_id.in_(
                    select(TeamMember.team_id).where(TeamMember.user_id == user_id)
                )
            )
        ),
    )
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_workflow_access.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Point the three existing call sites at the helper**

In `backend/app/api/workflows.py`, add the import next to the other service imports:

```python
from app.services.workflow_access import workflow_access_clause
```

Replace the body of `get_workflow_for_user` (around line 344):

```python
async def get_workflow_for_user(
    db: AsyncSession, workflow_id: uuid.UUID, user_id: uuid.UUID
) -> Workflow | None:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            workflow_access_clause(user_id),
        )
    )
    return result.scalar_one_or_none()
```

In `list_workflows` (around line 566) and `list_workflows_with_inputs` (around line 625), replace each inlined `or_(...)` block with:

```python
        .where(workflow_access_clause(current_user.id))
```

Leave every other line of those two functions untouched, including the `.where(Workflow.kind == "workflow")` and `.order_by(...)` calls that follow.

- [ ] **Step 6: Run the workflow API tests to confirm nothing regressed**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/ -k "workflow" -q
```

Expected: all pass, no new failures.

- [ ] **Step 7: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 3: Event service — publish, claim, cleanup

**Files:**
- Create: `backend/app/services/heym_event_service.py`
- Create: `backend/tests/test_heym_event_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_heym_event_service.py`:

```python
"""Tests for the Heym platform event publisher and delivery claims."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import heym_event_service


class StartedDedupeKeyTest(unittest.TestCase):
    def test_workers_inside_one_bucket_share_a_key(self) -> None:
        base = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
        keys = {
            heym_event_service.started_dedupe_key(base + timedelta(seconds=offset))
            for offset in (0, 7, 61, 299)
        }

        self.assertEqual(len(keys), 1)

    def test_next_bucket_gets_a_different_key(self) -> None:
        base = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)

        self.assertNotEqual(
            heym_event_service.started_dedupe_key(base),
            heym_event_service.started_dedupe_key(base + timedelta(seconds=300)),
        )


class PublishEventTest(unittest.IsolatedAsyncioTestCase):
    def _session(self) -> tuple[MagicMock, AsyncMock]:
        db = AsyncMock()
        maker = MagicMock()
        maker.return_value.__aenter__.return_value = db
        maker.return_value.__aexit__.return_value = False
        return maker, db

    async def test_publish_inserts_and_commits(self) -> None:
        maker, db = self._session()
        with patch.object(heym_event_service, "async_session_maker", maker):
            await heym_event_service.publish_event(
                name=heym_event_service.EVENT_WORKFLOW_CREATED,
                payload={"workflow_id": "w1"},
                owner_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                dedupe_key="workflow.created:w1",
            )

        db.execute.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_publish_swallows_database_errors(self) -> None:
        maker, db = self._session()
        db.execute.side_effect = RuntimeError("connection reset")

        with patch.object(heym_event_service, "async_session_maker", maker):
            await heym_event_service.publish_event(
                name=heym_event_service.EVENT_HEYM_STARTED,
                payload={},
            )

        # No exception escaped: a failed publish must never break the caller.


class ClaimHeymEventTest(unittest.IsolatedAsyncioTestCase):
    def _session(self, first_row: object) -> tuple[MagicMock, AsyncMock]:
        db = AsyncMock()
        result = MagicMock()
        result.first.return_value = first_row
        db.execute.return_value = result
        maker = MagicMock()
        maker.return_value.__aenter__.return_value = db
        maker.return_value.__aexit__.return_value = False
        return maker, db

    async def test_first_claim_wins(self) -> None:
        maker, db = self._session(first_row=(uuid.uuid4(),))

        with patch.object(heym_event_service, "async_session_maker", maker):
            claimed = await heym_event_service.claim_heym_event(
                event_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                node_id="n1",
            )

        self.assertTrue(claimed)
        db.commit.assert_awaited_once()

    async def test_second_claim_loses(self) -> None:
        maker, _db = self._session(first_row=None)

        with patch.object(heym_event_service, "async_session_maker", maker):
            claimed = await heym_event_service.claim_heym_event(
                event_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                node_id="n1",
            )

        self.assertFalse(claimed)

    async def test_claim_fails_closed_on_error(self) -> None:
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("deadlock")
        maker = MagicMock()
        maker.return_value.__aenter__.return_value = db
        maker.return_value.__aexit__.return_value = False

        with patch.object(heym_event_service, "async_session_maker", maker):
            claimed = await heym_event_service.claim_heym_event(
                event_id=uuid.uuid4(),
                workflow_id=uuid.uuid4(),
                node_id="n1",
            )

        self.assertFalse(claimed)


class CleanupTest(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_deletes_past_the_retention_window(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 3
        db.execute.return_value = result

        deleted = await heym_event_service.cleanup_heym_events(db)

        self.assertEqual(deleted, 3)
        db.execute.assert_awaited_once()
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_event_service.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.heym_event_service'`.

- [ ] **Step 3: Write the service**

Create `backend/app/services/heym_event_service.py`:

```python
"""Publishing and claiming Heym platform events.

Every write opens its own session. A publish that shares the caller's session
could poison the caller's transaction on failure, and the whole point of this
module is that recording an event can never break the action that produced it.
"""

from __future__ import annotations

import logging
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
# table cannot merge distinct events - a subscriber would run eight times. Every
# worker inside the same five-minute bucket collapses onto one row instead.
STARTED_BUCKET_SECONDS = 300


def started_dedupe_key(now: datetime) -> str:
    """Return the shared dedupe key for a ``heym.started`` publish at ``now``."""
    bucket = int(now.timestamp()) // STARTED_BUCKET_SECONDS
    return f"{EVENT_HEYM_STARTED}:{bucket}"


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


async def cleanup_heym_events(
    db: AsyncSession, *, retention_days: int = HEYM_EVENT_RETENTION_DAYS
) -> int:
    """Drop events past the retention window; their claims cascade away."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await db.execute(delete(HeymEvent).where(HeymEvent.created_at < cutoff))
    return result.rowcount or 0
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_event_service.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 4: Publish the four events

**Files:**
- Modify: `backend/app/main.py` (lifespan, around line 193)
- Modify: `backend/app/api/workflows.py` (`create_workflow` ~1233, `update_workflow` ~1476, `delete_workflow` ~1504)
- Modify: `backend/tests/test_heym_event_service.py` (add the payload-shape test)

- [ ] **Step 1: Write the failing test for workflow event payloads**

Append to `backend/tests/test_heym_event_service.py`:

```python
class WorkflowEventPayloadTest(unittest.TestCase):
    def test_payload_carries_identity_and_actor(self) -> None:
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.name = "Nightly report"
        workflow.owner_id = uuid.uuid4()
        workflow.updated_at = datetime(2026, 8, 11, 9, 30, tzinfo=timezone.utc)
        actor_id = uuid.uuid4()

        payload = heym_event_service.workflow_event_payload(workflow, actor_user_id=actor_id)

        self.assertEqual(payload["workflow_id"], str(workflow.id))
        self.assertEqual(payload["name"], "Nightly report")
        self.assertEqual(payload["owner_id"], str(workflow.owner_id))
        self.assertEqual(payload["actor_user_id"], str(actor_id))
        self.assertEqual(payload["updated_at"], "2026-08-11T09:30:00+00:00")

    def test_payload_tolerates_a_missing_updated_at(self) -> None:
        workflow = MagicMock()
        workflow.id = uuid.uuid4()
        workflow.name = "Draft"
        workflow.owner_id = uuid.uuid4()
        workflow.updated_at = None

        payload = heym_event_service.workflow_event_payload(workflow, actor_user_id=None)

        self.assertIsNone(payload["updated_at"])
        self.assertIsNone(payload["actor_user_id"])
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_event_service.py::WorkflowEventPayloadTest -v
```

Expected: FAIL, `AttributeError: module 'app.services.heym_event_service' has no attribute 'workflow_event_payload'`.

- [ ] **Step 3: Add the payload helper**

Append to `backend/app/services/heym_event_service.py`:

```python
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
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_event_service.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Publish `heym.started` from the lifespan**

In `backend/app/main.py`, add to the import block:

```python
from app.services.heym_event_service import (
    EVENT_HEYM_STARTED,
    publish_event,
    started_dedupe_key,
)
```

In `lifespan`, immediately after `await cron_scheduler.start()` (line 193):

```python
    _started_at = datetime.now(timezone.utc)
    await publish_event(
        name=EVENT_HEYM_STARTED,
        payload={
            "version": settings.resolved_version,
            "started_at": _started_at.isoformat(),
        },
        dedupe_key=started_dedupe_key(_started_at),
    )
```

If `datetime` and `timezone` are not already imported in `main.py`, add `from datetime import datetime, timezone` to the standard-library import block.

- [ ] **Step 6: Publish the three workflow events**

In `backend/app/api/workflows.py`, extend the service import block:

```python
from app.services.heym_event_service import (
    EVENT_WORKFLOW_CREATED,
    EVENT_WORKFLOW_DELETED,
    EVENT_WORKFLOW_UPDATED,
    publish_event,
    workflow_event_payload,
)
```

In `create_workflow`, after `await db.refresh(workflow)` and before the return:

```python
    await publish_event(
        name=EVENT_WORKFLOW_CREATED,
        payload=workflow_event_payload(workflow, actor_user_id=current_user.id),
        owner_id=workflow.owner_id,
        workflow_id=workflow.id,
        dedupe_key=f"{EVENT_WORKFLOW_CREATED}:{workflow.id}",
    )
```

In `update_workflow`, after `websocket_trigger_manager.request_sync()` and before the return:

```python
    # Dashboard widgets are Workflow rows too, but they are not workflows a user
    # subscribes to - only real workflows produce platform events.
    if getattr(workflow, "kind", "workflow") == "workflow":
        await publish_event(
            name=EVENT_WORKFLOW_UPDATED,
            payload=workflow_event_payload(workflow, actor_user_id=current_user.id),
            owner_id=workflow.owner_id,
            workflow_id=workflow.id,
            dedupe_key=f"{EVENT_WORKFLOW_UPDATED}:{workflow.id}:{workflow.updated_at}",
        )
```

In `delete_workflow`, capture the payload before the row goes away, then publish after `await db.delete(workflow)`:

```python
    deleted_payload = workflow_event_payload(workflow, actor_user_id=current_user.id)
    deleted_owner_id = workflow.owner_id
    deleted_workflow_id = workflow.id
    deleted_kind = getattr(workflow, "kind", "workflow")

    await db.delete(workflow)

    # The event is written from its own session, so it lands before this
    # request's transaction commits at teardown. A rollback after this point
    # would leave an event for a workflow that still exists - a narrow window we
    # accept, because the alternative is letting a failed publish roll back a
    # successful delete.
    if deleted_kind == "workflow":
        await publish_event(
            name=EVENT_WORKFLOW_DELETED,
            payload=deleted_payload,
            owner_id=deleted_owner_id,
            workflow_id=deleted_workflow_id,
            dedupe_key=f"{EVENT_WORKFLOW_DELETED}:{deleted_workflow_id}",
        )
```

Place the `deleted_payload` capture right after the ownership check that raises 403, before the analytics-snapshot `db.execute(text(...))` call.

- [ ] **Step 7: Verify nothing regressed**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/ -k "workflow or main" -q
```

Expected: all pass.

- [ ] **Step 8: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 5: Dispatcher matching helpers

These are pure functions with no database and no event loop, so they carry the interesting logic and get the sharpest tests.

**Files:**
- Create: `backend/app/services/heym_event_dispatcher.py`
- Create: `backend/tests/test_heym_event_dispatcher.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_heym_event_dispatcher.py`:

```python
"""Tests for Heym platform event dispatch."""

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.services import heym_event_dispatcher as dispatcher


def _event(name: str, owner_id: uuid.UUID | None = None, minute: int = 0) -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.name = name
    event.payload = {"workflow_id": "w1"}
    event.owner_id = owner_id
    event.workflow_id = uuid.uuid4()
    event.created_at = datetime(2026, 8, 11, 12, minute, tzinfo=timezone.utc)
    return event


class FindTriggerNodesTest(unittest.TestCase):
    def test_finds_active_heym_trigger_nodes(self) -> None:
        nodes = [
            {"id": "n1", "type": "heymTrigger", "data": {}},
            {"id": "n2", "type": "llm", "data": {}},
            {"id": "n3", "type": "heymTrigger", "data": {"active": False}},
        ]

        found = dispatcher.find_heym_trigger_nodes(nodes)

        self.assertEqual([node["id"] for node in found], ["n1"])

    def test_missing_active_flag_counts_as_active(self) -> None:
        nodes = [{"id": "n1", "type": "heymTrigger", "data": {"active": True}}]

        self.assertEqual(len(dispatcher.find_heym_trigger_nodes(nodes)), 1)


class NodeAcceptsEventTest(unittest.TestCase):
    def test_empty_filter_accepts_every_event(self) -> None:
        node = {"id": "n1", "type": "heymTrigger", "data": {"eventNames": []}}

        self.assertTrue(dispatcher.node_accepts_event(node, "workflow.created"))
        self.assertTrue(dispatcher.node_accepts_event(node, "heym.started"))

    def test_missing_filter_accepts_every_event(self) -> None:
        node = {"id": "n1", "type": "heymTrigger", "data": {}}

        self.assertTrue(dispatcher.node_accepts_event(node, "workflow.deleted"))

    def test_filter_rejects_unlisted_names(self) -> None:
        node = {"id": "n1", "type": "heymTrigger", "data": {"eventNames": ["workflow.updated"]}}

        self.assertTrue(dispatcher.node_accepts_event(node, "workflow.updated"))
        self.assertFalse(dispatcher.node_accepts_event(node, "workflow.created"))


class EventVisibilityTest(unittest.TestCase):
    def test_instance_wide_events_reach_every_owner(self) -> None:
        self.assertTrue(dispatcher.event_visible_to_owner(None, uuid.uuid4()))

    def test_owned_events_reach_only_their_owner(self) -> None:
        owner_id = uuid.uuid4()

        self.assertTrue(dispatcher.event_visible_to_owner(owner_id, owner_id))
        self.assertFalse(dispatcher.event_visible_to_owner(owner_id, uuid.uuid4()))


class BuildTriggerInputsTest(unittest.TestCase):
    def test_events_are_batched_in_created_at_order(self) -> None:
        second = _event("workflow.created", minute=2)
        first = _event("workflow.created", minute=1)

        inputs = dispatcher.build_trigger_inputs("n1", [second, first])

        self.assertEqual(inputs["triggered_by"], "heym_event")
        self.assertEqual(inputs["trigger_node_id"], "n1")
        self.assertEqual(len(inputs["events"]), 2)
        self.assertEqual(inputs["events"][0]["created_at"], "2026-08-11T12:01:00+00:00")
        self.assertEqual(inputs["events"][1]["created_at"], "2026-08-11T12:02:00+00:00")

    def test_single_event_still_arrives_as_an_array(self) -> None:
        inputs = dispatcher.build_trigger_inputs("n1", [_event("heym.started")])

        self.assertIsInstance(inputs["events"], list)
        self.assertEqual(len(inputs["events"]), 1)

    def test_event_entry_shape(self) -> None:
        event = _event("workflow.updated")

        entry = dispatcher.build_trigger_inputs("n1", [event])["events"][0]

        self.assertEqual(
            set(entry.keys()), {"id", "name", "payload", "workflow_id", "created_at"}
        )
        self.assertEqual(entry["name"], "workflow.updated")
        self.assertEqual(entry["payload"], {"workflow_id": "w1"})
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_event_dispatcher.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.heym_event_dispatcher'`.

- [ ] **Step 3: Write the helpers**

Create `backend/app/services/heym_event_dispatcher.py`:

```python
"""Delivering Heym platform events to subscribing workflows.

The dispatcher polls rather than listening. Polling costs at most five seconds of
latency and survives a worker that was down when the event was published, which a
NOTIFY-only design would not - and ``heym.started`` is published at exactly the
moment workers are coming up.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("heym_event_dispatcher")

DISPATCH_INTERVAL_SECONDS = 5
# Bounds backlog replay after downtime, the same role the cron scheduler's
# misfire grace plays: an event older than this is kept for inspection but is
# never delivered.
DISPATCH_LOOKBACK_MINUTES = 5
CLEANUP_INTERVAL_MINUTES = 60


def find_heym_trigger_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the active ``heymTrigger`` nodes in a workflow."""
    return [
        node
        for node in nodes or []
        if node.get("type") == "heymTrigger" and node.get("data", {}).get("active", True) is not False
    ]


def node_accepts_event(node: dict[str, Any], event_name: str) -> bool:
    """Return whether the node subscribes to this event name.

    An empty or absent ``eventNames`` list means every event.
    """
    selected = node.get("data", {}).get("eventNames")
    if not selected:
        return True
    return event_name in selected


def event_visible_to_owner(
    event_owner_id: uuid.UUID | None, workflow_owner_id: uuid.UUID | None
) -> bool:
    """Return whether a workflow's owner may receive this event.

    Events with no owner are instance-wide and reach everyone; owned events stay
    with their owner.
    """
    if event_owner_id is None:
        return True
    return event_owner_id == workflow_owner_id


def build_trigger_inputs(node_id: str, events: list[Any]) -> dict[str, Any]:
    """Build the workflow inputs for one batched delivery.

    Delivery is always a list. A burst inside one poll window becomes one run,
    and a lone event still arrives as a one-element array so downstream
    expressions never have to branch on shape.
    """
    ordered = sorted(events, key=lambda event: event.created_at)
    return {
        "triggered_by": "heym_event",
        "trigger_node_id": node_id,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "events": [
            {
                "id": str(event.id),
                "name": event.name,
                "payload": event.payload or {},
                "workflow_id": str(event.workflow_id) if event.workflow_id else None,
                "created_at": event.created_at.isoformat(),
            }
            for event in ordered
        ],
    }
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_event_dispatcher.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 6: Dispatcher loop and workflow execution

**Files:**
- Modify: `backend/app/services/heym_event_dispatcher.py`
- Modify: `backend/tests/test_heym_event_dispatcher.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the failing tests for the dispatch pass**

Append to `backend/tests/test_heym_event_dispatcher.py`:

```python
from unittest.mock import AsyncMock, patch


class DispatchWorkflowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.workflow = MagicMock()
        self.workflow.id = uuid.uuid4()
        self.workflow.owner_id = self.owner_id
        self.workflow.nodes = [{"id": "n1", "type": "heymTrigger", "data": {"eventNames": []}}]

    async def test_two_events_in_one_pass_produce_one_run(self) -> None:
        events = [
            _event("workflow.created", owner_id=self.owner_id, minute=1),
            _event("workflow.created", owner_id=self.owner_id, minute=2),
        ]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ),
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        run.assert_awaited_once()
        _workflow_arg, node_id, inputs = run.await_args.args
        self.assertEqual(node_id, "n1")
        self.assertEqual(len(inputs["events"]), 2)

    async def test_a_lost_claim_drops_only_that_event(self) -> None:
        events = [
            _event("workflow.created", owner_id=self.owner_id, minute=1),
            _event("workflow.created", owner_id=self.owner_id, minute=2),
        ]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service,
                "claim_heym_event",
                AsyncMock(side_effect=[True, False]),
            ),
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        _workflow_arg, _node_id, inputs = run.await_args.args
        self.assertEqual(len(inputs["events"]), 1)

    async def test_no_claims_means_no_run(self) -> None:
        events = [_event("workflow.created", owner_id=self.owner_id)]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=False)
            ),
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        run.assert_not_awaited()

    async def test_another_owners_event_is_not_delivered(self) -> None:
        events = [_event("workflow.created", owner_id=uuid.uuid4())]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ) as claim,
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        claim.assert_not_awaited()
        run.assert_not_awaited()

    async def test_filtered_out_events_are_never_claimed(self) -> None:
        self.workflow.nodes = [
            {"id": "n1", "type": "heymTrigger", "data": {"eventNames": ["workflow.deleted"]}}
        ]
        events = [_event("workflow.created", owner_id=self.owner_id)]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ) as claim,
            patch.object(manager, "_run_workflow", AsyncMock()),
        ):
            await manager._dispatch_workflow(self.workflow, events)

        claim.assert_not_awaited()

    async def test_each_subscribing_node_gets_its_own_run(self) -> None:
        self.workflow.nodes = [
            {"id": "n1", "type": "heymTrigger", "data": {}},
            {"id": "n2", "type": "heymTrigger", "data": {}},
        ]
        events = [_event("heym.started")]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ),
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        self.assertEqual(run.await_count, 2)
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_event_dispatcher.py -k Dispatch -v
```

Expected: FAIL, `AttributeError: module 'app.services.heym_event_dispatcher' has no attribute 'HeymEventDispatcher'`.

- [ ] **Step 3: Write the dispatcher class**

Append to `backend/app/services/heym_event_dispatcher.py`. Add these imports at the top of the file, below the existing ones:

```python
import asyncio
import os
from datetime import timedelta

from sqlalchemy import select

from app.db.models import HeymEvent, Workflow
from app.db.session import async_session_maker
from app.services import heym_event_service
```

Then append the class:

```python
class HeymEventDispatcher:
    """Polls the event log and starts a run for every subscribing trigger node."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._worker_id = f"{os.getpid()}"
        self._last_cleanup_at: datetime | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Heym event dispatcher started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Heym event dispatcher stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Heym event dispatch tick failed: %s", e)
            await asyncio.sleep(DISPATCH_INTERVAL_SECONDS)

    async def _tick(self) -> None:
        workflows = await self._get_subscribing_workflows()
        if workflows:
            events = await self._get_recent_events()
            if events:
                for workflow in workflows:
                    await self._dispatch_workflow(workflow, events)
        await self._maybe_cleanup()

    async def _get_subscribing_workflows(self) -> list[Workflow]:
        async with async_session_maker() as db:
            result = await db.execute(select(Workflow))
            all_workflows = result.scalars().all()
        return [
            workflow for workflow in all_workflows if find_heym_trigger_nodes(workflow.nodes or [])
        ]

    async def _get_recent_events(self) -> list[HeymEvent]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=DISPATCH_LOOKBACK_MINUTES)
        async with async_session_maker() as db:
            result = await db.execute(
                select(HeymEvent)
                .where(HeymEvent.created_at >= cutoff)
                .order_by(HeymEvent.created_at.asc())
            )
            return list(result.scalars().all())

    async def _dispatch_workflow(self, workflow: Workflow, events: list[HeymEvent]) -> None:
        """Claim and deliver every matching event to each subscribing node."""
        for node in find_heym_trigger_nodes(workflow.nodes or []):
            node_id = str(node.get("id", "")).strip()
            if not node_id:
                continue

            claimed: list[HeymEvent] = []
            for event in events:
                if not event_visible_to_owner(event.owner_id, workflow.owner_id):
                    continue
                if not node_accepts_event(node, event.name):
                    continue
                if await heym_event_service.claim_heym_event(
                    event_id=event.id,
                    workflow_id=workflow.id,
                    node_id=node_id,
                    worker_id=self._worker_id,
                ):
                    claimed.append(event)

            if not claimed:
                continue

            logger.info(
                "Delivering %d heym event(s) to workflow %s node %s",
                len(claimed),
                workflow.id,
                node_id,
            )
            await self._run_workflow(workflow, node_id, build_trigger_inputs(node_id, claimed))

    async def _run_workflow(
        self, workflow: Workflow, node_id: str, inputs: dict[str, Any]
    ) -> None:
        """Execute the workflow and persist the run, mirroring the IMAP trigger."""
        from app.api.analytics import upsert_workflow_analytics_snapshot
        from app.api.workflows import (
            _persist_global_variables_from_execution,
            collect_referenced_workflows,
            get_credentials_context,
        )
        from app.db.models import ExecutionHistory
        from app.services.execution_cancellation import clear_execution, register_execution
        from app.services.global_variables_service import get_global_variables_context
        from app.services.workflow_executor import execute_workflow

        async with async_session_maker() as db:
            workflow_result = await db.execute(select(Workflow).where(Workflow.id == workflow.id))
            fresh_workflow = workflow_result.scalar_one_or_none()
            if not fresh_workflow:
                logger.warning("Workflow %s disappeared before heym event execution", workflow.id)
                return

            workflow_cache = await collect_referenced_workflows(
                db, fresh_workflow.nodes, actor_user_id=fresh_workflow.owner_id
            )
            credentials_context = await get_credentials_context(db, fresh_workflow.owner_id)
            global_variables_context = await get_global_variables_context(
                db, fresh_workflow.owner_id
            )

            execution_id = uuid.uuid4()
            cancel_event = register_execution(
                workflow_id=fresh_workflow.id,
                execution_id=execution_id,
                inputs=inputs,
                trigger_source="heym_event",
                actor_user_id=fresh_workflow.owner_id,
            )
            try:
                result = execute_workflow(
                    workflow_id=fresh_workflow.id,
                    nodes=fresh_workflow.nodes,
                    edges=fresh_workflow.edges,
                    inputs=inputs,
                    workflow_cache=workflow_cache,
                    credentials_context=credentials_context,
                    global_variables_context=global_variables_context,
                    trace_user_id=fresh_workflow.owner_id,
                    actor_user_id=fresh_workflow.owner_id,
                    cancel_event=cancel_event,
                    execution_id=str(execution_id),
                )
            finally:
                clear_execution(execution_id)

            db.add(
                ExecutionHistory(
                    id=execution_id,
                    workflow_id=fresh_workflow.id,
                    inputs=inputs,
                    outputs=result.outputs,
                    node_results=result.node_results,
                    status=result.status,
                    execution_time_ms=result.execution_time_ms,
                    trigger_source="heym_event",
                )
            )
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=fresh_workflow.id,
                owner_id=fresh_workflow.owner_id,
                workflow_name_snapshot=fresh_workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
            )

            for sub_exec in result.sub_workflow_executions:
                db.add(
                    ExecutionHistory(
                        workflow_id=uuid.UUID(sub_exec.workflow_id),
                        inputs=sub_exec.inputs,
                        outputs=sub_exec.outputs,
                        node_results=sub_exec.node_results,
                        status=sub_exec.status,
                        execution_time_ms=sub_exec.execution_time_ms,
                        trigger_source=sub_exec.trigger_source,
                    )
                )
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                )

            await _persist_global_variables_from_execution(
                db,
                fresh_workflow.owner_id,
                fresh_workflow.nodes,
                workflow_cache,
                result.node_results,
                result.sub_workflow_executions,
            )

            await db.commit()

    async def _maybe_cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_cleanup_at is not None and now - self._last_cleanup_at < timedelta(
            minutes=CLEANUP_INTERVAL_MINUTES
        ):
            return
        self._last_cleanup_at = now
        try:
            async with async_session_maker() as db:
                deleted = await heym_event_service.cleanup_heym_events(db)
                await db.commit()
            if deleted:
                logger.info("Cleaned up %d expired heym event(s)", deleted)
        except Exception as e:
            logger.warning("Heym event cleanup failed: %s", e)


heym_event_dispatcher = HeymEventDispatcher()
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_event_dispatcher.py -v
```

Expected: 17 passed.

- [ ] **Step 5: Wire the dispatcher into the lifespan**

In `backend/app/main.py`, add the import:

```python
from app.services.heym_event_dispatcher import heym_event_dispatcher
```

Start it after `await websocket_trigger_manager.start()` (line 200):

```python
    await heym_event_dispatcher.start()
```

Stop it as the first shutdown step, immediately after `shutdown_tracing()` (line 202):

```python
    await heym_event_dispatcher.stop()
```

The `heym.started` publish added in Task 4 sits before the dispatcher starts, and the five-minute lookback is what lets the dispatcher pick it up on its first tick.

- [ ] **Step 6: Confirm the app still boots**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run python -c "from app.main import app; print(len(app.routes))"
```

Expected: a route count printed with no import error.

- [ ] **Step 7: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 7: `heymTrigger` node handler

**Files:**
- Create: `backend/app/services/node_execution/nodes/heym_trigger_node.py`
- Create: `backend/tests/test_heym_trigger_node.py`
- Modify: `backend/app/services/node_execution/registry.py`
- Modify: `backend/app/services/workflow_executor.py` (two initial-input blocks)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_heym_trigger_node.py`:

```python
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
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_trigger_node.py -v
```

Expected: FAIL, `ModuleNotFoundError: ... heym_trigger_node`.

- [ ] **Step 3: Write the handler**

Create `backend/app/services/node_execution/nodes/heym_trigger_node.py`:

```python
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
```

- [ ] **Step 4: Register the handler**

In `backend/app/services/node_execution/registry.py`, add to `_HANDLER_MODULES` in alphabetical position (between `"grist"` and `"http"`):

```python
    "heym": "heym_node",
    "heymTrigger": "heym_trigger_node",
```

The `heym` entry points at a module written in Task 8. Registration is lazy — `import_module` runs only when a `heym` node executes — so committing both keys here is safe.

- [ ] **Step 5: Seed the trigger inputs in the executor**

`backend/app/services/workflow_executor.py` has two identical elif ladders that hand a trigger node its initial inputs. Add a branch to both, matching the surrounding style.

In the first ladder, after the `telegramTrigger` branch (around line 7794):

```python
            elif node.get("type") == "heymTrigger":
                node["data"] = node.get("data", {})
                node["data"]["_initial_inputs"] = initial_inputs
```

In the second ladder, after the `telegramTrigger` branch (around line 9540):

```python
        elif node.get("type") == "heymTrigger":
            node["data"] = node.get("data", {})
            node["data"]["_initial_inputs"] = inputs
```

This is trigger-input plumbing, not node business logic, so it does not violate the rule against node-type branches in `_execute_node_logic`. Every other trigger node is wired here.

- [ ] **Step 6: Run the tests to confirm they pass**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_trigger_node.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 8: `heym` action node handler

**Files:**
- Create: `backend/app/services/node_execution/nodes/heym_node.py`
- Create: `backend/tests/test_heym_node.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_heym_node.py`:

```python
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

        result = heym_node.execute(
            _ctx({"heymOperation": "listWorkflows", "heymLimit": "2"})
        )

        self.assertEqual(len(result["workflows"]), 2)
        self.assertEqual(result["total"], 5)


class GetWorkflowTest(HeymNodeTestBase):
    def test_returns_node_identity_without_node_data(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow(
            "Target",
            self.owner_id,
            nodes=[{"id": "a", "type": "llm", "data": {"credentialId": "secret"}}],
        )
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(target)]

        result = heym_node.execute(
            _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(target.id)})
        )

        self.assertEqual(result["nodes"], [{"id": "a", "type": "llm", "label": ""}])
        self.assertNotIn("data", result["nodes"][0])

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


class CountExecutionsTest(HeymNodeTestBase):
    def test_groups_counts_by_status(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        rows = MagicMock()
        rows.all.return_value = [("success", 7), ("error", 2)]
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalar_one(target),
            rows,
        ]

        result = heym_node.execute(
            _ctx({"heymOperation": "countExecutions", "heymWorkflowId": str(target.id)})
        )

        self.assertEqual(result["total"], 9)
        self.assertEqual(result["by_status"], {"success": 7, "error": 2})
        self.assertIsNone(result["since"])

    def test_since_days_sets_the_window(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        rows = MagicMock()
        rows.all.return_value = [("success", 1)]
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalar_one(target),
            rows,
        ]

        result = heym_node.execute(
            _ctx(
                {
                    "heymOperation": "countExecutions",
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
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_node.py -v
```

Expected: FAIL, `ModuleNotFoundError: ... heym_node`.

- [ ] **Step 3: Write the handler**

Create `backend/app/services/node_execution/nodes/heym_node.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.node_execution.base import NodeExecutionContext

DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500


def _resolve(ctx: NodeExecutionContext, key: str) -> str:
    """Resolve one node field through the executor's expression engine."""
    raw = ctx.node_data.get(key)
    if raw in (None, ""):
        return ""
    return str(ctx.executor.evaluate_message_template(raw, ctx.inputs)).strip()


def _parse_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the heym node."""
    from sqlalchemy import func, select

    from app.db.models import ExecutionHistory, Workflow
    from app.db.session import SessionLocal
    from app.services.workflow_access import workflow_access_clause

    operation = str(ctx.node_data.get("heymOperation", "")).strip()
    if not operation:
        raise ValueError("Heym node requires an operation")

    with SessionLocal() as db:
        # Scope every read to the owner of the workflow this node lives in, not the
        # actor who started the run. Cron, portal, and event triggered runs have no
        # actor, and owner scoping keeps one workflow's results identical however it
        # was started - the same rule credentials and global variables already follow.
        owning = db.execute(
            select(Workflow).where(Workflow.id == uuid.UUID(str(ctx.executor.workflow_id)))
        ).scalar_one_or_none()
        owner_id = owning.owner_id if owning is not None else ctx.executor.actor_user_id
        access = workflow_access_clause(owner_id)

        if operation == "listWorkflows":
            rows = (
                db.execute(
                    select(Workflow)
                    .where(access)
                    .where(Workflow.kind == "workflow")
                    .order_by(Workflow.updated_at.desc())
                )
                .scalars()
                .all()
            )
            limit = min(
                max(_parse_int(_resolve(ctx, "heymLimit"), DEFAULT_LIST_LIMIT), 1), MAX_LIST_LIMIT
            )
            return {
                "workflows": [_workflow_summary(row) for row in rows[:limit]],
                "total": len(rows),
            }

        if operation in ("getWorkflow", "countExecutions"):
            workflow = _require_workflow(ctx, db, select, Workflow, access)

            if operation == "getWorkflow":
                return _workflow_detail(workflow)

            since_days = _parse_int(_resolve(ctx, "heymSinceDays"), 0)
            since = (
                datetime.now(timezone.utc) - timedelta(days=since_days) if since_days > 0 else None
            )
            status_filter = _resolve(ctx, "heymStatus")

            query = select(ExecutionHistory.status, func.count()).where(
                ExecutionHistory.workflow_id == workflow.id
            )
            if since is not None:
                query = query.where(ExecutionHistory.started_at >= since)
            if status_filter:
                query = query.where(ExecutionHistory.status == status_filter)
            query = query.group_by(ExecutionHistory.status)

            by_status = {status: int(count) for status, count in db.execute(query).all()}
            return {
                "workflow_id": str(workflow.id),
                "total": sum(by_status.values()),
                "by_status": by_status,
                "since": since.isoformat() if since else None,
            }

    raise ValueError(f"Unknown Heym operation: {operation}")


def _require_workflow(
    ctx: NodeExecutionContext, db: Any, select: Any, Workflow: Any, access: Any
) -> Any:
    """Load the selected workflow or refuse in a way that leaks nothing.

    A workflow that does not exist and a workflow the owner cannot reach produce
    the same message, so the node cannot be used to probe for workflow ids.
    """
    raw_id = _resolve(ctx, "heymWorkflowId")
    if not raw_id:
        raise ValueError("Heym node requires a target workflow")
    try:
        workflow_uuid = uuid.UUID(raw_id)
    except ValueError:
        raise ValueError(f"Workflow not found or not accessible: {raw_id}") from None

    workflow = db.execute(
        select(Workflow).where(Workflow.id == workflow_uuid).where(access)
    ).scalar_one_or_none()
    if workflow is None:
        raise ValueError(f"Workflow not found or not accessible: {raw_id}")
    return workflow


def _workflow_summary(workflow: Any) -> dict[str, Any]:
    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "description": workflow.description,
        "active": bool(getattr(workflow, "active", True)),
        "folder_id": str(workflow.folder_id) if workflow.folder_id else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        "node_count": len(workflow.nodes or []),
    }


def _workflow_detail(workflow: Any) -> dict[str, Any]:
    """Return identity only: node ``data`` holds credential ids and prompt text."""
    detail = _workflow_summary(workflow)
    detail["nodes"] = [
        {
            "id": node.get("id"),
            "type": node.get("type"),
            "label": node.get("data", {}).get("label", ""),
        }
        for node in workflow.nodes or []
    ]
    detail["edges"] = [
        {"id": edge.get("id"), "source": edge.get("source"), "target": edge.get("target")}
        for edge in workflow.edges or []
    ]
    return detail
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/test_heym_node.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Confirm the registry resolves both handlers**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run python -c "
from app.services.node_execution.registry import get_node_handler
print(get_node_handler('heym'), get_node_handler('heymTrigger'))
"
```

Expected: two function objects, no `None`.

- [ ] **Step 6: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 9: Frontend node registration

No frontend tests are written for this repo. Verification is lint plus typecheck plus a manual canvas check.

**Files:**
- Modify: `frontend/src/types/workflow.ts` (~line 176)
- Modify: `frontend/src/types/node.ts` (~line 459)
- Modify: `frontend/src/lib/nodeIcons.ts` (~lines 98, 159)
- Modify: `frontend/src/lib/canvasConnectionRules.ts` (~lines 26, 41)
- Modify: `frontend/src/components/Panels/NodePanel.vue` (~lines 241, 288)
- Modify: `frontend/src/components/Nodes/BaseNode.vue` (~lines 53, 113, 167)
- Modify: `frontend/src/components/Canvas/WorkflowCanvas.vue` (~line 1114)
- Modify: `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts` (~lines 123, 183, 243)

- [ ] **Step 1: Extend the node type union**

In `frontend/src/types/workflow.ts`, after `| "imapTrigger"`:

```typescript
  | "heym"
  | "heymTrigger"
```

- [ ] **Step 2: Add both node definitions**

In `frontend/src/types/node.ts`, after the `imapTrigger` entry (which ends at line 472):

```typescript
  heymTrigger: {
    type: "heymTrigger",
    label: "Heym Trigger",
    description: "Start the workflow when a Heym platform event is published",
    color: "node-execute",
    icon: "Workflow",
    inputs: 0,
    outputs: 1,
    defaultData: {
      label: "heymTrigger",
      eventNames: [],
    },
  },
  heym: {
    type: "heym",
    label: "Heym",
    description: "Read Heym workflows and execution history",
    color: "node-execute",
    icon: "Workflow",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "heym",
      heymOperation: "listWorkflows",
      heymWorkflowId: "",
      heymLimit: "100",
      heymStatus: "",
      heymSinceDays: "",
    },
  },
```

Both reuse the `execute` node's colour token and the `Workflow` lucide icon. heymrun already reuses icons across nodes, and these two are about Heym's own workflows.

- [ ] **Step 3: Register icons and colours**

In `frontend/src/lib/nodeIcons.ts`, add `Workflow` to the lucide import list if it is not already imported, then after `imapTrigger: Inbox,` (line 98):

```typescript
  heym: Workflow,
  heymTrigger: Workflow,
```

After `imapTrigger: "text-node-email",` (line 159):

```typescript
  heym: "text-node-execute",
  heymTrigger: "text-node-execute",
```

- [ ] **Step 4: Register canvas connection rules**

In `frontend/src/lib/canvasConnectionRules.ts`, add `"heymTrigger"` to both sets, after `"imapTrigger"` in each. `heym` goes into neither set: it takes a normal input and is useful as an agent tool.

```typescript
  "heymTrigger",
```

- [ ] **Step 5: Register the palette entries**

In `frontend/src/components/Panels/NodePanel.vue`, after `imapTrigger: Inbox,` (line 241):

```typescript
  heym: Workflow,
  heymTrigger: Workflow,
```

Add `Workflow` to that file's lucide import if missing. Then add `"heymTrigger"` to `DASHBOARD_HIDDEN_NODE_TYPES` after `"imapTrigger"` (line 288) — dashboard widgets have no trigger. Leave `heym` visible there; a widget reading workflow counts is legitimate.

- [ ] **Step 6: Register the canvas node rendering**

In `frontend/src/components/Nodes/BaseNode.vue`, after `imapTrigger: Inbox,` (line 53):

```typescript
  heym: Workflow,
  heymTrigger: Workflow,
```

After `imapTrigger: "node-email",` (line 113):

```typescript
  heym: "node-execute",
  heymTrigger: "node-execute",
```

In the `hasInput` computed, after `&& props.type !== "imapTrigger"` (line 167):

```typescript
    && props.type !== "heymTrigger"
```

Add `Workflow` to the file's lucide import if missing.

- [ ] **Step 7: Register the default node data**

In `frontend/src/components/Canvas/WorkflowCanvas.vue`, after the `imapTrigger` entry (line 1114):

```typescript
    heymTrigger: { label: "heymTrigger", eventNames: [] },
    heym: { label: "heym", heymOperation: "listWorkflows", heymWorkflowId: "", heymLimit: "100", heymStatus: "", heymSinceDays: "" },
```

- [ ] **Step 8: Register the properties panel maps**

In `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`, after `imapTrigger: Inbox,` (line 123):

```typescript
    heym: Workflow,
    heymTrigger: Workflow,
```

After `imapTrigger: "node-email",` (line 183):

```typescript
    heym: "node-execute",
    heymTrigger: "node-execute",
```

After `imapTrigger: "imap-trigger-node",` (line 243):

```typescript
    heym: "heym-node",
    heymTrigger: "heym-trigger-node",
```

Add `Workflow` to that file's lucide import if missing.

- [ ] **Step 9: Verify lint and types**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: both exit 0. A `NodeType` union error here means a map is missing one of the two keys — every map in these files is exhaustive over `NodeType`.

- [ ] **Step 10: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 10: Properties panel forms

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/HeymNodeProperties.vue`
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/HeymTriggerNodeProperties.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/operationOptions.ts`
- Modify: `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`
- Modify: `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`
- Modify: `frontend/src/stores/workflow.ts` (~line 2293)

- [ ] **Step 1: Add the operation options**

Append to `frontend/src/components/Panels/propertiesPanel/operationOptions.ts`:

```typescript
export const heymOperationOptions: OperationOption[] = [
  { value: "listWorkflows", label: "List Workflows" },
  { value: "getWorkflow", label: "Get Workflow" },
  { value: "countExecutions", label: "Count Executions" },
];

export const heymEventNameOptions: OperationOption[] = [
  { value: "heym.started", label: "Heym Started" },
  { value: "workflow.created", label: "Workflow Created" },
  { value: "workflow.updated", label: "Workflow Updated" },
  { value: "workflow.deleted", label: "Workflow Deleted" },
];
```

- [ ] **Step 2: Add the expression field machinery to the controller**

The `heym` node has three expression-capable fields, so it needs the indexed navigation the converter node uses — that is what makes the expression dialog show `1/n` and step through every eligible field.

In `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`, next to the `ConverterExpressionFieldKey` declarations (line 667):

```typescript
  type HeymExpressionFieldKey = "heymWorkflowId" | "heymLimit" | "heymStatus" | "heymSinceDays";

  interface HeymExpressionField {
    key: HeymExpressionFieldKey;
    label: string;
  }

  const heymExpressionInputRefs = ref<Map<HeymExpressionFieldKey, ExpandableFieldRef>>(new Map());
  const currentHeymExpressionFieldIndex = ref(0);
```

Next to `converterExpressionFields` (line 5780):

```typescript
  const heymExpressionFields = computed<HeymExpressionField[]>(() => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "heym") {
      return [];
    }
    const operation = n.data.heymOperation || "listWorkflows";
    if (operation === "listWorkflows") {
      return [{ key: "heymLimit", label: "Limit" }];
    }
    if (operation === "getWorkflow") {
      return [{ key: "heymWorkflowId", label: "Workflow" }];
    }
    return [
      { key: "heymWorkflowId", label: "Workflow" },
      { key: "heymStatus", label: "Status" },
      { key: "heymSinceDays", label: "Since (days)" },
    ];
  });

  const heymExpressionFieldCount = computed((): number => heymExpressionFields.value.length);

  function heymExpressionFieldIndex(key: HeymExpressionFieldKey): number {
    const index = heymExpressionFields.value.findIndex((field) => field.key === key);
    return index >= 0 ? index : 0;
  }

  function setHeymExpressionInputRef(key: HeymExpressionFieldKey, el: unknown): void {
    if (el) {
      heymExpressionInputRefs.value.set(key, el as ExpandableFieldRef);
    } else {
      heymExpressionInputRefs.value.delete(key);
    }
  }

  function openHeymExpressionFieldAtIndex(index: number): void {
    const n = selectedNode.value;
    if (!n || n.type !== "heym") {
      return;
    }
    const field = heymExpressionFields.value[index];
    if (!field) {
      return;
    }
    currentHeymExpressionFieldIndex.value = index;
    heymExpressionInputRefs.value.get(field.key)?.openExpandDialog();
  }

  function closeHeymExpressionDialogs(): void {
    for (const input of heymExpressionInputRefs.value.values()) {
      input.closeExpandDialog();
    }
  }

  function handleHeymExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = heymExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentHeymExpressionFieldIndex.value - 1
        : currentHeymExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    closeHeymExpressionDialogs();
    currentHeymExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openHeymExpressionFieldAtIndex(newIndex);
    });
  }

  function onHeymRegisterExpressionFieldIndex(index: number): void {
    currentHeymExpressionFieldIndex.value = index;
  }
```

Add `closeHeymExpressionDialogs();` next to `closeConverterExpressionDialogs();` in the close-all block (line 2236).

In the double-click dialog opener, next to the `converter` branch (line 2242):

```typescript
    } else if (nodeType === "heym") {
      currentHeymExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) return;
        const firstField = heymExpressionFields.value[0];
        if (firstField && heymExpressionInputRefs.value.get(firstField.key)) {
          nextTick(() => openHeymExpressionFieldAtIndex(0));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
```

Export all of these from the controller's return object, next to the converter exports (around line 9011):

```typescript
    heymExpressionFields,
    heymExpressionFieldCount,
    heymExpressionFieldIndex,
    setHeymExpressionInputRef,
    handleHeymExpressionFieldNavigate,
    onHeymRegisterExpressionFieldIndex,
```

- [ ] **Step 3: Write the `heym` node form**

Create `frontend/src/components/Panels/propertiesPanel/nodes/HeymNodeProperties.vue`:

```vue
<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import { heymOperationOptions } from "../operationOptions";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  workflowOptions,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
  heymExpressionFieldCount,
  heymExpressionFieldIndex,
  setHeymExpressionInputRef,
  handleHeymExpressionFieldNavigate,
  onHeymRegisterExpressionFieldIndex,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Operation</Label>
      <Select
        :model-value="selectedNode.data.heymOperation || 'listWorkflows'"
        :options="heymOperationOptions"
        @update:model-value="updateNodeData('heymOperation', $event)"
      />
    </div>

    <div v-if="selectedNode.data.heymOperation === 'listWorkflows'" class="space-y-2">
      <Label>Limit</Label>
      <ExpressionInput
        :ref="(el) => setHeymExpressionInputRef('heymLimit', el)"
        :model-value="selectedNode.data.heymLimit || ''"
        placeholder="100"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Limit"
        field-key="heymLimit"
        :field-index="heymExpressionFieldIndex('heymLimit')"
        :field-count="heymExpressionFieldCount"
        @navigate="handleHeymExpressionFieldNavigate"
        @register-field-index="onHeymRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('heymLimit', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Maximum workflows to return. Capped at 500.
      </p>
    </div>

    <div v-if="selectedNode.data.heymOperation !== 'listWorkflows'" class="space-y-2">
      <Label>Workflow</Label>
      <SearchableSelect
        :model-value="selectedNode.data.heymWorkflowId || ''"
        :options="[{ value: '', label: 'Select a workflow...' }, ...workflowOptions]"
        placeholder="Select a workflow..."
        search-placeholder="Search workflows..."
        @update:model-value="updateNodeData('heymWorkflowId', $event)"
      />
    </div>

    <template v-if="selectedNode.data.heymOperation === 'countExecutions'">
      <div class="space-y-2">
        <Label>Status filter</Label>
        <ExpressionInput
          :ref="(el) => setHeymExpressionInputRef('heymStatus', el)"
          :model-value="selectedNode.data.heymStatus || ''"
          placeholder="success"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Status filter"
          field-key="heymStatus"
          :field-index="heymExpressionFieldIndex('heymStatus')"
          :field-count="heymExpressionFieldCount"
          @navigate="handleHeymExpressionFieldNavigate"
          @register-field-index="onHeymRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('heymStatus', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Leave empty to count every status.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Since (days)</Label>
        <ExpressionInput
          :ref="(el) => setHeymExpressionInputRef('heymSinceDays', el)"
          :model-value="selectedNode.data.heymSinceDays || ''"
          placeholder="7"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Since (days)"
          field-key="heymSinceDays"
          :field-index="heymExpressionFieldIndex('heymSinceDays')"
          :field-count="heymExpressionFieldCount"
          @navigate="handleHeymExpressionFieldNavigate"
          @register-field-index="onHeymRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('heymSinceDays', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Leave empty to count the full history.
        </p>
      </div>
    </template>
  </template>
</template>
```

If `Select.vue` does not exist under `@/components/ui/`, use the same select component `RagNodeProperties.vue` uses for its operation dropdown and keep the `:options` binding shape identical to that file.

- [ ] **Step 4: Write the `heymTrigger` node form**

Create `frontend/src/components/Panels/propertiesPanel/nodes/HeymTriggerNodeProperties.vue`:

```vue
<script setup lang="ts">
import Label from "@/components/ui/Label.vue";
import { heymEventNameOptions } from "../operationOptions";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, updateNodeData } = usePropertiesPanelContext();

function isSelected(value: string): boolean {
  const selected = selectedNode.value?.data.eventNames;
  return Array.isArray(selected) && selected.includes(value);
}

function toggleEvent(value: string): void {
  const current = selectedNode.value?.data.eventNames;
  const selected = Array.isArray(current) ? [...current] : [];
  const index = selected.indexOf(value);
  if (index >= 0) {
    selected.splice(index, 1);
  } else {
    selected.push(value);
  }
  updateNodeData("eventNames", selected);
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Events</Label>
      <div class="space-y-1">
        <label
          v-for="option in heymEventNameOptions"
          :key="option.value"
          class="flex items-center gap-2 text-sm"
        >
          <input
            type="checkbox"
            :checked="isSelected(option.value)"
            @change="toggleEvent(option.value)"
          >
          {{ option.label }}
        </label>
      </div>
      <p class="text-xs text-muted-foreground">
        Select none to receive every event. Events published within the same five second
        window arrive together in one run as an array.
      </p>
    </div>
  </template>
</template>
```

- [ ] **Step 5: Route both components in the form switch**

In `frontend/src/components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue`, add the imports next to the other node property imports:

```typescript
import HeymNodeProperties from "./HeymNodeProperties.vue";
import HeymTriggerNodeProperties from "./HeymTriggerNodeProperties.vue";
```

In the template, after the `ImapTriggerNodeProperties` line:

```vue
  <HeymTriggerNodeProperties v-else-if="selectedNode?.type === 'heymTrigger'" />
```

And next to the other action nodes, after the `ExecuteNodeProperties` line:

```vue
  <HeymNodeProperties v-else-if="selectedNode?.type === 'heym'" />
```

- [ ] **Step 6: Add store validation for the missing workflow selection**

In `frontend/src/stores/workflow.ts`, after the `imapTrigger` validation block (which ends around line 2301):

```typescript
      if (node.type === "heym") {
        const operation = node.data.heymOperation || "listWorkflows";
        if (operation !== "listWorkflows" && !node.data.heymWorkflowId) {
          errors.push({
            nodeId: node.id,
            nodeLabel: node.data.label,
            nodeType: "Heym",
            message: "Workflow is not selected",
          });
        }
      }
```

- [ ] **Step 7: Verify lint and types**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: both exit 0.

- [ ] **Step 8: Manual canvas check**

```bash
./run.sh
```

Open `http://localhost:4017`, add a `Heym Trigger` node and a `Heym` node, confirm: the trigger has no input handle, the `Heym` node's operation dropdown switches the visible fields, the workflow dropdown searches, and double-clicking the `Heym` node opens the expression dialog showing `1/3` on `countExecutions`.

- [ ] **Step 9: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 11: DSL prompt

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

- [ ] **Step 1: Add the `heymTrigger` section**

Insert after the `### 3d. websocketSend` section ends and before `### 4. llm (Language Model)` (line 426):

```markdown
### 3f. heymTrigger (Heym Platform Event Trigger)
- **Purpose**: Start the workflow when Heym itself publishes a platform event
- **Inputs**: 0 | **Outputs**: 1
- **WHEN TO USE**: When the workflow should react to Heym lifecycle activity — the platform starting, or a workflow being created, updated, or deleted
- **DO NOT use** `cron` polling as a workaround for reacting to workflow changes
- **Data fields**:
  - `label`: Node identifier (e.g., "platformEvents")
  - `eventNames`: Array of event names to subscribe to. Valid values: `heym.started`, `workflow.created`, `workflow.updated`, `workflow.deleted`. An empty array subscribes to every event.
- **Delivery**: Events are **batched**. Every event published inside the same five-second dispatch window arrives in ONE run as an array. A single event still arrives as a one-element array.
- **Output fields available downstream**:
  - `$<label>.events` — array of event objects (always an array)
  - `$<label>.events[0].id` — event UUID
  - `$<label>.events[0].name` — event name
  - `$<label>.events[0].payload` — event body (`workflow_id`, `name`, `owner_id`, `actor_user_id`, `updated_at` for `workflow.*`; `version`, `started_at` for `heym.started`)
  - `$<label>.events[0].workflow_id` — subject workflow id, or null
  - `$<label>.events[0].created_at` — ISO timestamp
  - `$<label>.count` — number of events in this batch
  - `$<label>.triggered_at` — ISO timestamp for the workflow run
- **Use a `loop` node over `$<label>.events` when the workflow must act once per event.**

**Example node JSON:**
```json
{"id": "n1", "type": "heymTrigger", "position": {"x": 100, "y": 100}, "data": {"label": "platformEvents", "eventNames": ["workflow.created", "workflow.deleted"]}}
```
```

- [ ] **Step 2: Add the `heym` section**

Insert after the `### 42. googleDrive (Google Drive Operations)` section ends and before `### Simple Connections (most cases)` (line 4590):

```markdown
### 43. heym (Heym Platform Data)
- **Purpose**: Read Heym's own data — the workflows the owner can reach, one workflow's structure, and execution-history counts
- **Inputs**: 1 | **Outputs**: 1
- **WHEN TO USE**: Meta-workflows that report on the Heym instance itself — inventories, health digests, execution summaries
- **No credential required.** Results are scoped to the owner of the workflow this node lives in: workflows they own plus workflows shared with them directly or through a team.
- **Data fields**:
  - `label`: Node identifier (e.g., "heymData")
  - `heymOperation`: One of `listWorkflows`, `getWorkflow`, `countExecutions`
  - `heymWorkflowId`: Target workflow UUID. Required for `getWorkflow` and `countExecutions`. Expression-capable.
  - `heymLimit`: Maximum rows for `listWorkflows`. Defaults to `100`, capped at `500`. Expression-capable.
  - `heymStatus`: Optional status filter for `countExecutions` (e.g. `success`, `error`). Expression-capable.
  - `heymSinceDays`: Optional lookback in days for `countExecutions`. Empty counts the full history. Expression-capable.
- **Output fields available downstream**:
  - `listWorkflows` → `$<label>.workflows` (array of `id`, `name`, `description`, `active`, `folder_id`, `updated_at`, `node_count`), `$<label>.total`
  - `getWorkflow` → `$<label>.id`, `$<label>.name`, `$<label>.nodes` (array of `id`, `type`, `label` only — node configuration is never returned), `$<label>.edges`, `$<label>.updated_at`
  - `countExecutions` → `$<label>.workflow_id`, `$<label>.total`, `$<label>.by_status`, `$<label>.since`

**Example node JSON:**
```json
{"id": "n2", "type": "heym", "position": {"x": 400, "y": 100}, "data": {"label": "heymData", "heymOperation": "countExecutions", "heymWorkflowId": "$platformEvents.events[0].workflow_id", "heymSinceDays": "7"}}
```
```

- [ ] **Step 3: Verify the prompt still imports**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run python -c "
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
assert 'heymTrigger' in WORKFLOW_DSL_SYSTEM_PROMPT
assert 'heymOperation' in WORKFLOW_DSL_SYSTEM_PROMPT
print('ok', len(WORKFLOW_DSL_SYSTEM_PROMPT))
"
```

Expected: `ok <length>`. If the constant has a different name, read the module's `__all__` or its final assignment and use that name.

- [ ] **Step 4: Run the DSL and assistant tests**

```bash
cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false uv run pytest tests/ -k "dsl or assistant" -q
```

Expected: all pass.

- [ ] **Step 5: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 12: heymrun documentation

Use the `heym-documentation` skill for this task — this is a medium feature with new node types, which the feature documentation policy covers.

**Files:**
- Create: `frontend/src/docs/content/nodes/heym-node.md`
- Create: `frontend/src/docs/content/nodes/heym-trigger-node.md`
- Modify: `frontend/src/docs/manifest.ts`
- Modify: `frontend/src/docs/content/reference/features.md`
- Modify: `frontend/src/docs/content/reference/node-types.md`
- Modify: `frontend/src/docs/content/reference/triggers.md`

- [ ] **Step 1: Invoke the documentation skill**

```
Skill(skill="heym-documentation", args="Document the new heym and heymTrigger nodes")
```

- [ ] **Step 2: Write the two node pages**

`heym-trigger-node.md` must cover: the four event names; that delivery is batched into an array; that a burst inside one five-second window is one run; the `events` / `count` / `triggered_at` output shape; the loop-over-`events` pattern; that `heym.started` fires once per platform start across all workers; and that events older than five minutes at dispatch time are not delivered, so a long outage does not replay a backlog.

`heym-node.md` must cover: the three operations with their fields and outputs; that no credential is needed; that results are scoped to the workflow owner's reach, not the person who started the run; that `getWorkflow` returns node identity without node configuration; and the 500-row cap on `listWorkflows`.

Match the structure of `frontend/src/docs/content/nodes/imap-trigger-node.md` and `google-drive-node.md`.

- [ ] **Step 3: Register both pages in the manifest**

In `frontend/src/docs/manifest.ts`, add to the nodes category items list, keeping the surrounding ordering:

```typescript
      { slug: "heym-node", title: "Heym" },
      { slug: "heym-trigger-node", title: "Heym Trigger" },
```

- [ ] **Step 4: Update the reference docs**

- `reference/features.md`: add a per-node section for each, and add both to the node-types summary list.
- `reference/node-types.md`: add both entries.
- `reference/triggers.md`: add `heymTrigger` alongside the other trigger nodes.

No credential is involved, so `integrations.md`, `credentials.md`, and `credentials-sharing.md` need no change.

- [ ] **Step 5: Verify docs count and types**

```bash
cd frontend && bun run typecheck && ls src/docs/content/nodes | wc -l
```

Expected: typecheck exits 0, and the node page count is 59.

- [ ] **Step 6: Checkpoint — do NOT commit**

Leave the work in the heymrun working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 13: heymweb node registration

**Files (all under `/Users/ckagun/Projects/heym/heymweb`):**
- Modify: `src/lib/marketingNodeCatalog.ts`
- Modify: `src/lib/node-doc-links.ts`
- Modify: `src/components/sections/NodesSection.tsx`
- Modify: `src/components/templates/nodePreviewTokens.ts`
- Modify: `src/components/templates/TemplateCanvasNode.tsx`
- Modify: `src/components/sections/DocumentationSection.tsx`
- Modify: `tests/seo/invariants.test.ts`

- [ ] **Step 1: Add both catalog entries**

In `src/lib/marketingNodeCatalog.ts`, append to `MARKETING_NODE_CATALOG`:

```typescript
  { id: 'heymTrigger', name: 'Heym Trigger' },
  { id: 'heym', name: 'Heym' },
```

- [ ] **Step 2: Add the doc links**

In `src/lib/node-doc-links.ts`, add to `NODE_DOC_PATHS`:

```typescript
  heymTrigger: 'nodes/heym-trigger-node.md',
  heym: 'nodes/heym-node.md',
```

- [ ] **Step 3: Add the marketing cards**

In `src/components/sections/NodesSection.tsx`, add `Workflow` to the lucide import, then add two entries next to the other triggers and action nodes:

```tsx
  {
    id: 'heymTrigger',
    icon: Workflow,
    name: 'Heym Trigger',
    description:
      'Start a workflow when Heym publishes a platform event — the instance starting, or a workflow being created, updated, or deleted. Events published in the same window arrive together as one batch.',
    categories: ['triggers'],
  },
  {
    id: 'heym',
    icon: Workflow,
    name: 'Heym',
    description:
      'Read Heym itself: list the workflows you can reach, inspect one workflow structure, and count execution history by status and time window.',
    categories: ['core'],
  },
```

If `'core'` is not a valid category id in that file, use the category the `execute` node card uses.

- [ ] **Step 4: Add the preview tokens and canvas icons**

In `src/components/templates/nodePreviewTokens.ts`, add to `NODE_CSS_VAR`:

```typescript
  heym: '--node-execute',
  heymTrigger: '--node-execute',
```

In `src/components/templates/TemplateCanvasNode.tsx`, add `Workflow` to the lucide import and map both node ids to it, matching the surrounding entries.

- [ ] **Step 5: Add the curated documentation links**

In `src/components/sections/DocumentationSection.tsx`, add entries for `nodes/heym-node.md` and `nodes/heym-trigger-node.md`, following the shape of the neighbouring node entries.

- [ ] **Step 6: Bump the two hardcoded node counts**

In `tests/seo/invariants.test.ts`, line 89 and line 93:

```typescript
  test('matches all 59 heymrun node definitions with unique marketing cards and docs links', () => {
```

```typescript
    expect(MARKETING_NODE_COUNT).toBe(59)
```

Both are required. Bun's `toBe` narrows to a literal overload, so a stale count fails `bunx tsc --noEmit`, not just the test run. The sibling `countFiles(docsRoot/nodes)` assertion self-corrects once the docs sync in Task 14 copies the two new pages.

- [ ] **Step 7: Verify**

```bash
cd /Users/ckagun/Projects/heym/heymweb && bunx tsc --noEmit && bun test tests/seo/invariants.test.ts
```

Expected: typecheck clean. The `countFiles` assertion may still fail here because the docs have not been synced yet — that is fixed in Task 14. Every other assertion must pass.

- [ ] **Step 8: Checkpoint — do NOT commit**

Leave the work in the heymweb working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymweb && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 14: heymweb template and content sync

**Files (all under `/Users/ckagun/Projects/heym/heymweb`):**
- Modify: `src/lib/operationsTemplates.ts`
- Synced: `src/docs/**`, DSL prompt mirror

- [ ] **Step 1: Add the template**

Append to the template array in `src/lib/operationsTemplates.ts`, following the `StaticTemplate` interface in `src/lib/templates.ts`:

```typescript
  {
    slug: 'workflow-change-audit-log',
    name: 'Workflow Change Audit Log',
    description: 'Capture every workflow create, update, and delete on your Heym instance and post a batched summary to Slack.',
    longDescription: `## Workflow Change Audit Log

This template turns Heym's own platform events into an audit trail. A **Heym Trigger** subscribes to workflow lifecycle events, a **Heym** node pulls the current structure of the changed workflow, and a Slack message reports the batch.

### What this workflow does

1. **PlatformEvents** wakes up when a workflow is created, updated, or deleted
2. **ChangedWorkflow** reads the affected workflow's current node list
3. **AuditMessage** posts a single Slack summary covering every event in the batch

### Use cases

- Audit trails for teams sharing one Heym instance
- Noticing an unexpected workflow deletion the moment it happens
- A daily record of what changed and who changed it

### Setup

Add a Slack credential to **AuditMessage**. No credential is needed for the Heym nodes — they read only what the workflow owner can already reach.

### Notes

Events are delivered in batches: everything published inside the same five-second window arrives in one run as \`$PlatformEvents.events\`. Add a Loop node over that array if you want one message per event instead of one per batch.`,
    tags: ['Audit', 'Platform Events', 'Slack', 'Governance'],
    category: 'operations',
    nodes: [
      {
        id: 'n1',
        type: 'heymTrigger',
        position: { x: 100, y: 200 },
        data: {
          label: 'PlatformEvents',
          eventNames: ['workflow.created', 'workflow.updated', 'workflow.deleted'],
        },
      },
      {
        id: 'n2',
        type: 'heym',
        position: { x: 400, y: 200 },
        data: {
          label: 'ChangedWorkflow',
          heymOperation: 'getWorkflow',
          heymWorkflowId: '$PlatformEvents.events[0].workflow_id',
        },
      },
      {
        id: 'n3',
        type: 'slack',
        position: { x: 700, y: 200 },
        data: {
          label: 'AuditMessage',
          credentialId: 'YOUR_CREDENTIAL_ID',
          slackOperation: 'sendMessage',
          slackChannel: '#heym-audit',
          slackMessage:
            '$PlatformEvents.count workflow change(s). Latest: $PlatformEvents.events[0].name on $ChangedWorkflow.name ($ChangedWorkflow.nodes.length nodes)',
        },
      },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2' },
      { id: 'e2', source: 'n2', target: 'n3' },
    ],
    featured: false,
  },
```

If `'operations'` is not a valid `TemplateCategory`, read `src/lib/templateCategories.ts` and pick the closest existing category. Match the `slackOperation` and `slackChannel` field names against an existing Slack template in the same file before committing — copy that template's field names exactly rather than trusting the ones above.

- [ ] **Step 2: Sync docs and the DSL prompt from heymrun**

```bash
cd /Users/ckagun/Projects/heym/heymweb && bun run sync-docs && bun run sync-dsl-prompt
```

Expected: the two new node pages appear under the synced docs directory.

- [ ] **Step 3: Verify the full heymweb build**

```bash
cd /Users/ckagun/Projects/heym/heymweb && bunx tsc --noEmit && bun test tests/seo/invariants.test.ts && bun run build
```

Expected: all three clean, including the `countFiles(docsRoot/nodes)` assertion that failed in Task 13.

- [ ] **Step 4: Checkpoint — do NOT commit**

Leave the work in the heymweb working tree. This project keeps every change uncommitted and unpushed; there is no commit for this task.

```bash
cd /Users/ckagun/Projects/heym/heymweb && git status --short
```

Expected: the files this task touched appear as modified or untracked. Nothing is staged, nothing is committed.

---

### Task 15: Full verification

- [ ] **Step 1: Run the whole heymrun check**

```bash
cd /Users/ckagun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh
```

Expected: Ruff format applied, Ruff lint clean, frontend lint and typecheck clean, and the backend suite green. Do not run this while `run_tests.sh` is running.

- [ ] **Step 2: Review the formatting-only diffs**

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status --short && git diff --stat
```

`ruff format` may have rewritten files. Leave those changes in the working tree with everything else — do not commit them.

- [ ] **Step 3: Confirm the migration is applied**

```bash
cd backend && uv run alembic current
```

Expected: `107_add_heym_events (head)`.

- [ ] **Step 4: End-to-end manual check**

```bash
cd /Users/ckagun/Projects/heym/heymrun && ./run.sh
```

Then:

1. Build a workflow with a `Heym Trigger` node subscribed to `workflow.created`, wired to a `Console Log` node logging `$PlatformEvents.events`.
2. Save and activate it.
3. Create two new workflows within five seconds of each other.
4. Within ten seconds, open the trigger workflow's execution history.

Expected: exactly **one** run, whose `events` array holds **two** entries. Two runs means claims are not deduplicating; one run with one event means the batch window is not collecting both.

5. Restart the stack and confirm exactly one `heym.started` row:

```bash
docker-compose exec postgres psql -U postgres -d heym -c \
  "SELECT name, count(*) FROM heym_events GROUP BY name;"
```

Expected: `heym.started` count of 1 per restart, not 8. If the database name or user differs, read them from `docker-compose.yml`.

- [ ] **Step 5: Confirm nothing was committed or pushed**

```bash
cd /Users/ckagun/Projects/heym/heymrun && git status -sb && git log --oneline -1
cd /Users/ckagun/Projects/heym/heymweb && git status -sb && git log --oneline -1
```

Expected: both repositories show the full feature as uncommitted working-tree changes, and `git log` still points at the same commit it did before this plan started. Nothing committed, nothing pushed.

---

## Self-review notes

**Spec coverage:** data model → Task 1; access scope → Tasks 2 and 8; publisher and dedupe → Tasks 3 and 4; dispatcher, lookback, batching, retention → Tasks 5 and 6; both node handlers → Tasks 7 and 8; frontend surface → Tasks 9 and 10; DSL → Task 11; heymrun docs → Task 12; heymweb rollout and template → Tasks 13 and 14; verification → Task 15.

**Naming consistency across tasks:** `workflow_access_clause`, `publish_event`, `started_dedupe_key`, `workflow_event_payload`, `claim_heym_event`, `cleanup_heym_events`, `find_heym_trigger_nodes`, `node_accepts_event`, `event_visible_to_owner`, `build_trigger_inputs`, `HeymEventDispatcher._dispatch_workflow`, `_run_workflow`. Node data keys: `eventNames`, `heymOperation`, `heymWorkflowId`, `heymLimit`, `heymStatus`, `heymSinceDays`. These names are used identically wherever they appear.

**Two things to confirm against the code while implementing**, both flagged inline where they matter: the exact name of the DSL prompt constant in Task 11 Step 3, and the Slack node's field names in Task 14 Step 1. Both are verifiable in seconds and neither changes the plan's shape.
