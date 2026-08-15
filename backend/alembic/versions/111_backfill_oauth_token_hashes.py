"""Backfill legacy plaintext OAuth tokens so the lookup fallback can be removed.

`hash_oauth_token` has been applied at write time for a while, but no revision
ever converted the rows written before that. The lookup papered over this by
also trying the presented value verbatim, which meant anyone who could read
`oauth_access_tokens` could present a stored digest and have it match the row.
That made the digest itself a working credential.

This revision converts the remaining plaintext rows so the fallback can go.

Unlike the MCP key backfill, the guard here is sound: OAuth tokens are
`secrets.token_urlsafe(40)`, roughly 54 characters of base64url, which a
64-character lowercase hex digest can never be confused with. Rows that already
look like a digest are skipped rather than double-hashed.

Revision ID: 111_backfill_oauth_token_hashes
Revises: 110_hash_portal_sessions
Create Date: 2026-08-15
"""

import hashlib

import sqlalchemy as sa

from alembic import op

revision = "111_backfill_oauth_token_hashes"
down_revision = "110_hash_portal_sessions"
branch_labels = None
depends_on = None

_DIGEST_SHAPE = "^[0-9a-f]{64}$"


def upgrade() -> None:
    conn = op.get_bind()

    for column in ("access_token", "refresh_token"):
        rows = conn.execute(
            sa.text(
                f"SELECT id, {column} FROM oauth_access_tokens "
                f"WHERE {column} IS NOT NULL AND {column} !~ :shape"
            ),
            {"shape": _DIGEST_SHAPE},
        ).fetchall()
        for row_id, token in rows:
            digest = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
            conn.execute(
                sa.text(f"UPDATE oauth_access_tokens SET {column} = :digest WHERE id = :row_id"),
                {"digest": digest, "row_id": row_id},
            )


def downgrade() -> None:
    # Intentionally a no-op; the plaintext tokens cannot be reconstructed.
    # OAuth tokens expire on their own, so affected clients re-authenticate.
    pass
