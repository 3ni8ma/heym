from app.services.secret_tokens import hash_secret


def hash_oauth_token(token: str) -> str:
    """Return the database-safe hash for an OAuth access or refresh token."""
    return hash_secret(token)
