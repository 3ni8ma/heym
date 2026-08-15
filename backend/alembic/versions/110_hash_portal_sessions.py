"""Hash portal session tokens at rest.

Backfills active sessions in place so nobody is logged out: the token a browser
already holds still hashes to the stored row. No schema change is needed, the
column is String(255) and a SHA-256 hex digest is 64 characters.

WARNING: downgrade cannot restore the plaintext tokens. Hashing is one-way and
this revision keeps no copy of the original values.

Revision ID: 110_hash_portal_sessions
Revises: 109_hash_mcp_api_keys
Create Date: 2026-08-15
"""

import hashlib

import sqlalchemy as sa

from alembic import op

revision = "110_hash_portal_sessions"
down_revision = "109_hash_mcp_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text("SELECT id, token FROM portal_sessions WHERE token IS NOT NULL")
    ).fetchall()
    for row_id, token in rows:
        digest = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
        conn.execute(
            sa.text("UPDATE portal_sessions SET token = :digest WHERE id = :row_id"),
            {"digest": digest, "row_id": row_id},
        )


def downgrade() -> None:
    # Intentionally a no-op. See the WARNING above: the plaintext session tokens
    # are gone and cannot be reconstructed. Portal users simply log in again.
    pass
