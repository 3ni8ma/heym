"""Fetch OpenCode Go subscription usage from the gateway's authenticated usage route.

``GET <base>/v1/usage`` with the credential's API key returns the rolling 5-hour, weekly and
monthly windows as ``{"usage": {"rolling": {"percent": 0-100, "status": "ok" | "rate-limited",
"resetsAt": "<iso8601>"}}}``. The route is first-party but undocumented and has already changed
shape once, so the payload is decoded defensively and malformed windows are skipped rather than
failing the whole report. Results are cached for 60s per credential id.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from app.http_identity import merge_outbound_headers
from app.models.schemas import OpenCodeUsageResponse, OpenCodeUsageWindow
from app.services.opencode_catalog import OPENCODE_ZEN_BASE_URL

_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, OpenCodeUsageResponse]] = {}

# Ordered as the gateway documents its limits: $12 per 5 hours, $30 weekly, $60 monthly.
_WINDOWS: tuple[tuple[str, str], ...] = (
    ("rolling", "5 hours"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
)


def usage_url(base_url: str) -> str:
    """Build the usage URL for a gateway base that may or may not already end in ``/v1``."""
    base = (base_url or "").strip().rstrip("/") or OPENCODE_ZEN_BASE_URL
    if base.lower().endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/v1/usage"


def _reset_after_seconds(resets_at: str | None) -> int | None:
    if not resets_at:
        return None
    try:
        parsed = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((parsed - datetime.now(timezone.utc)).total_seconds()))


def parse_opencode_usage(payload: object) -> OpenCodeUsageResponse:
    """Parse a ``/usage`` payload, tolerating both the wrapped and bare window shapes."""
    if not isinstance(payload, dict):
        return OpenCodeUsageResponse(available=False, error="unexpected usage payload")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = payload

    windows: list[OpenCodeUsageWindow] = []
    for key, label in _WINDOWS:
        entry = usage.get(key)
        if not isinstance(entry, dict):
            continue
        percent = entry.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)):
            continue
        if not 0 <= float(percent) <= 100:
            continue
        raw_reset = entry.get("resetsAt") or entry.get("resets_at")
        resets_at = raw_reset if isinstance(raw_reset, str) else None
        windows.append(
            OpenCodeUsageWindow(
                key=key,
                label=label,
                used_percent=float(percent),
                status=str(entry.get("status") or "ok"),
                resets_at=resets_at,
                reset_after_seconds=_reset_after_seconds(resets_at),
            )
        )

    if not windows:
        return OpenCodeUsageResponse(available=False, error="no usage windows returned")
    return OpenCodeUsageResponse(available=True, windows=windows)


async def fetch_opencode_usage(
    *, credential_id: str, api_key: str, base_url: str = ""
) -> OpenCodeUsageResponse:
    """Return parsed OpenCode Go usage for a credential. Never raises."""
    if not api_key:
        return OpenCodeUsageResponse(available=False, error="no api key")
    cached = _cache.get(credential_id)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]
    result = await _probe(api_key, base_url)
    _cache[credential_id] = (time.time(), result)
    return result


async def _probe(api_key: str, base_url: str) -> OpenCodeUsageResponse:
    headers = merge_outbound_headers(
        {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(usage_url(base_url), headers=headers)
    except Exception as exc:  # noqa: BLE001 - usage must never break the request
        return OpenCodeUsageResponse(available=False, error=f"{type(exc).__name__}: {exc}")

    if response.status_code == 401:
        return OpenCodeUsageResponse(available=False, error="Invalid or missing API key")
    if response.status_code == 403:
        return OpenCodeUsageResponse(available=False, error="No OpenCode Go subscription")
    if response.status_code != 200:
        return OpenCodeUsageResponse(available=False, error=f"HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        return OpenCodeUsageResponse(available=False, error="usage response was not JSON")
    return parse_opencode_usage(payload)
