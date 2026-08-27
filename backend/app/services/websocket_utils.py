"""Shared helpers for outbound WebSocket trigger and sender nodes."""

import asyncio
import base64
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.http_identity import HEYM_USER_AGENT, merge_outbound_headers
from app.services.ssrf_guard import (
    open_guarded_websocket,
    reject_reserved_websocket_headers,
)

_HTTP_TOKEN_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_FORBIDDEN_HEADER_VALUE_CHARACTERS = ("\r", "\n", "\x00")


@dataclass(frozen=True)
class WebSocketSendMetadata:
    """Describes the normalized payload sent to a WebSocket server."""

    message_type: str
    size_bytes: int


def normalize_websocket_headers(headers_value: Any) -> dict[str, str]:
    """Parse node header configuration into a string-only header map."""
    if headers_value is None:
        return {}

    if isinstance(headers_value, str):
        stripped = headers_value.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("WebSocket headers must be a JSON object") from exc
    elif isinstance(headers_value, dict):
        parsed = headers_value
    else:
        raise ValueError("WebSocket headers must be a JSON object")

    if not isinstance(parsed, dict):
        raise ValueError("WebSocket headers must be a JSON object")

    normalized: dict[str, str] = {}
    for key, value in parsed.items():
        if value is None:
            continue
        name = str(key)
        normalized_value = str(value)
        if _HTTP_TOKEN_PATTERN.fullmatch(name) is None:
            raise ValueError(f"WebSocket header name {name!r} is invalid")
        if any(character in normalized_value for character in _FORBIDDEN_HEADER_VALUE_CHARACTERS):
            raise ValueError(f"WebSocket header {name} contains an invalid control character")
        normalized[name] = normalized_value
    return normalized


def normalize_websocket_subprotocols(subprotocols_value: Any) -> list[str]:
    """Parse comma-separated or JSON-array subprotocol configuration."""
    if subprotocols_value is None:
        return []

    items: list[Any]
    if isinstance(subprotocols_value, str):
        stripped = subprotocols_value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "WebSocket subprotocols must be a CSV string or JSON array"
                ) from exc
            if not isinstance(parsed, list):
                raise ValueError("WebSocket subprotocols JSON must be an array")
            items = parsed
        else:
            items = stripped.split(",")
    elif isinstance(subprotocols_value, (list, tuple)):
        items = list(subprotocols_value)
    else:
        raise ValueError("WebSocket subprotocols must be a CSV string or JSON array")

    normalized = [str(item).strip() for item in items if str(item).strip()]
    for subprotocol in normalized:
        if _HTTP_TOKEN_PATTERN.fullmatch(subprotocol) is None:
            raise ValueError(f"WebSocket subprotocol {subprotocol!r} is invalid")
    return normalized


def _pop_single_header(headers: dict[str, str], header_name: str) -> str | None:
    """Remove and return one case-insensitive header, rejecting duplicates."""
    matches = [name for name in headers if name.strip().lower() == header_name]
    if len(matches) > 1:
        raise ValueError(f"WebSocket headers may contain only one {header_name} header")
    if not matches:
        return None
    return headers.pop(matches[0])


def build_websocket_connect_kwargs(
    headers_value: Any,
    subprotocols_value: Any,
) -> dict[str, Any]:
    """Convert node config into ``websockets.connect`` keyword arguments."""
    normalized_headers = normalize_websocket_headers(headers_value)
    origin = _pop_single_header(normalized_headers, "origin")
    configured_user_agent = _pop_single_header(normalized_headers, "user-agent")
    # Checked before the merge so the rejection names the header the operator
    # actually configured, not the merged result.
    reject_reserved_websocket_headers(normalized_headers)
    merged_headers = merge_outbound_headers(normalized_headers)
    user_agent_header = str(
        HEYM_USER_AGENT if configured_user_agent is None else configured_user_agent
    ).strip()
    merged_headers.pop("User-Agent", None)
    subprotocols = normalize_websocket_subprotocols(subprotocols_value)

    kwargs: dict[str, Any] = {
        "open_timeout": 20,
        "close_timeout": 10,
    }
    if merged_headers:
        kwargs["additional_headers"] = merged_headers
    if user_agent_header:
        kwargs["user_agent_header"] = user_agent_header
    if origin is not None:
        kwargs["origin"] = origin
    if subprotocols:
        kwargs["subprotocols"] = subprotocols
    return kwargs


def serialize_websocket_message(
    message: Any,
) -> tuple[str | bytes, WebSocketSendMetadata]:
    """Normalize sender-node output into a WebSocket text or binary frame."""
    if isinstance(message, bytearray):
        message = bytes(message)

    if isinstance(message, bytes):
        return message, WebSocketSendMetadata(message_type="binary", size_bytes=len(message))

    if isinstance(message, str):
        payload = message
        return payload, WebSocketSendMetadata(
            message_type="text",
            size_bytes=len(payload.encode("utf-8")),
        )

    payload = json.dumps(message, ensure_ascii=False)
    return payload, WebSocketSendMetadata(
        message_type="json",
        size_bytes=len(payload.encode("utf-8")),
    )


def parse_websocket_message(message: str | bytes) -> dict[str, Any]:
    """Convert an incoming frame into a workflow-friendly payload."""
    if isinstance(message, str):
        payload: dict[str, Any] = {
            "type": "text",
            "text": message,
            "sizeBytes": len(message.encode("utf-8")),
            "isBinary": False,
            "isJson": False,
        }
        try:
            payload["data"] = json.loads(message)
            payload["isJson"] = True
        except json.JSONDecodeError:
            payload["data"] = message
        return payload

    decoded_text: str | None = None
    parsed_data: Any = None
    is_json = False
    try:
        decoded_text = message.decode("utf-8")
        try:
            parsed_data = json.loads(decoded_text)
            is_json = True
        except json.JSONDecodeError:
            parsed_data = decoded_text
    except UnicodeDecodeError:
        decoded_text = None
        parsed_data = None

    payload = {
        "type": "binary",
        "text": decoded_text,
        "data": parsed_data,
        "base64": base64.b64encode(message).decode("ascii"),
        "sizeBytes": len(message),
        "isBinary": True,
        "isJson": is_json,
    }
    return payload


async def _wait_for_transport_drain(websocket: Any, timeout_seconds: float = 0.25) -> None:
    """Give the transport a brief chance to flush queued bytes before closing."""
    transport = getattr(websocket, "transport", None)
    if transport is None or transport.is_closing():
        return

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while transport.get_write_buffer_size() > 0:
        if asyncio.get_running_loop().time() >= deadline:
            return
        await asyncio.sleep(0.01)


async def send_websocket_message(
    url: str,
    headers: Any,
    subprotocols: Any,
    message: Any,
) -> dict[str, Any]:
    """Open an outbound WebSocket connection, send one message, and close it."""
    normalized_url = str(url).strip()
    if not normalized_url:
        raise ValueError("WebSocket Send node requires a URL")

    connect_kwargs = build_websocket_connect_kwargs(headers, subprotocols)
    payload, metadata = serialize_websocket_message(message)
    websocket = await open_guarded_websocket(
        normalized_url,
        subject="WebSocket Send node URL",
        **connect_kwargs,
    )

    try:
        await websocket.send(payload)
        await _wait_for_transport_drain(websocket)
        return {
            "status": "sent",
            "url": normalized_url,
            "message_type": metadata.message_type,
            "size_bytes": metadata.size_bytes,
            "subprotocol": websocket.subprotocol,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        with suppress(Exception):
            await websocket.close(code=1000)
        wait_closed = getattr(websocket, "wait_closed", None)
        if callable(wait_closed):
            with suppress(Exception):
                await wait_closed()
