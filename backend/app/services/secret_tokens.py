"""Shared hashing helper for capability secrets stored at rest.

Capability secrets (API keys, session tokens) are high-entropy random values, so
a plain SHA-256 is enough: there is nothing to brute force and nothing to salt
against. Storing only the digest means a database read or a backup no longer
yields a replayable credential.

There is deliberately no plaintext fallback in the lookup. Accepting the stored
representation as a credential would defeat the entire point of hashing, since
an attacker who reads the digest could present it verbatim and match the row.
Backfilling migrations convert every existing row in place, so the digest is the
only representation the lookup ever needs to match.
"""

import hashlib


def hash_secret(secret: str) -> str:
    """Return the database-safe SHA-256 digest for a capability secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
