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
