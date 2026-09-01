"""index vector_store_items.metadata for id-field upsert/delete lookups

Revision ID: 122_vsi_metadata_index
Revises: 121_running_node_start_times
Create Date: 2026-09-01 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "122_vsi_metadata_index"
down_revision: Union[str, None] = "121_running_node_start_times"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector is opt-in: the table only exists where 5ba5b9aaf6ba could create it.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.vector_store_items') IS NOT NULL THEN
                CREATE INDEX IF NOT EXISTS ix_vsi_metadata
                ON vector_store_items USING gin (metadata jsonb_path_ops);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_vsi_metadata")
