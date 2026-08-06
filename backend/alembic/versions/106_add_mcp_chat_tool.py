"""add mcp chat tool settings and conversation source

Revision ID: 106_add_mcp_chat_tool
Revises: 105_add_rag_credential_type
Create Date: 2026-08-06 00:00:00.000000

Note: alembic_version.version_num is varchar(32), so the revision id must stay
within 32 characters.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "106_add_mcp_chat_tool"
down_revision: Union[str, None] = "105_add_rag_credential_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mcp_chat_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("mcp_chat_credential_id", UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("mcp_chat_model", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_users_mcp_chat_credential_id",
        "users",
        "credentials",
        ["mcp_chat_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "mcp_servers",
        sa.Column("chat_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("mcp_servers", sa.Column("chat_credential_id", UUID(as_uuid=True), nullable=True))
    op.add_column("mcp_servers", sa.Column("chat_model", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_mcp_servers_chat_credential_id",
        "mcp_servers",
        "credentials",
        ["chat_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "dashboard_conversations",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="chat"),
    )


def downgrade() -> None:
    op.drop_column("dashboard_conversations", "source")
    op.drop_constraint("fk_mcp_servers_chat_credential_id", "mcp_servers", type_="foreignkey")
    op.drop_column("mcp_servers", "chat_model")
    op.drop_column("mcp_servers", "chat_credential_id")
    op.drop_column("mcp_servers", "chat_enabled")
    op.drop_constraint("fk_users_mcp_chat_credential_id", "users", type_="foreignkey")
    op.drop_column("users", "mcp_chat_model")
    op.drop_column("users", "mcp_chat_credential_id")
    op.drop_column("users", "mcp_chat_enabled")
