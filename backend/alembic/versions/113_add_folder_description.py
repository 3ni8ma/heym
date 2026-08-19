"""add folder description

Revision ID: 113_add_folder_description
Revises: 112_add_folder_icon
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "113_add_folder_description"
down_revision: str | None = "112_add_folder_icon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("folders", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("folders", "description")
