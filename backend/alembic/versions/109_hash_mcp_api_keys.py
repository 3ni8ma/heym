"""Hash MCP API keys at rest.

Backfills the global user key and every named server key in place with the same
SHA-256 the application now uses, so already-issued keys keep working: the key a
client presents still hashes to the stored row. No schema change is needed, both
columns are String(64) and a SHA-256 hex digest is exactly 64 characters.

Hashing runs in Python rather than via pgcrypto's digest(), so installs whose
database user cannot CREATE EXTENSION are not broken.

WARNING: downgrade cannot restore the plaintext keys. Hashing is one-way, and
this revision keeps no copy of the original values. Reverting leaves the digests
in place, which no client can authenticate against; affected users must
regenerate their keys from the MCP tab.

Revision ID: 109_hash_mcp_api_keys
Revises: 108_add_alerts
Create Date: 2026-08-15
"""

import hashlib

import sqlalchemy as sa

from alembic import op

revision = "109_hash_mcp_api_keys"
down_revision = "108_add_alerts"
branch_labels = None
depends_on = None


# (table, id column, secret column) triples whose contents become SHA-256 digests.
_HASHED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("users", "id", "mcp_api_key"),
    ("mcp_servers", "id", "api_key"),
)


def upgrade() -> None:
    conn = op.get_bind()

    # Deliberately unguarded: `secrets.token_hex(32)` produces 64 lowercase hex
    # characters, exactly like a SHA-256 digest, so no shape test can tell a
    # hashed key from a plaintext one. Alembic runs a revision once per
    # database, which is the guarantee this relies on.
    for table, id_column, secret_column in _HASHED_COLUMNS:
        rows = conn.execute(
            sa.text(
                f"SELECT {id_column}, {secret_column} FROM {table} "
                f"WHERE {secret_column} IS NOT NULL"
            )
        ).fetchall()
        for row_id, secret in rows:
            digest = hashlib.sha256(str(secret).encode("utf-8")).hexdigest()
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET {secret_column} = :digest WHERE {id_column} = :row_id"
                ),
                {"digest": digest, "row_id": row_id},
            )


def downgrade() -> None:
    # Intentionally a no-op. See the WARNING above: the plaintext keys are gone
    # and cannot be reconstructed, so there is nothing to restore.
    pass
