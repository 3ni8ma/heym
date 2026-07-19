from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the http node."""
    ssrf_guard = import_module("app.services.ssrf_guard")
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    curl_command = node_data.get("curl", "")
    curl_command = self.evaluate_message_template(curl_command, inputs, node_id)
    method, url, headers, body, follow_redirects = self.parse_curl(curl_command)
    if not url:
        raise ValueError("HTTP node requires a URL")
    # Refuse targets that resolve to internal/metadata addresses before dialing
    # (SSRF, GHSA-8wj7-v2w6-wfcx). The guarded client additionally pins the
    # resolved IP so redirects and DNS rebinding cannot reach internal hosts.
    ssrf_guard.guard_http_url(url)
    if body:
        body = self.evaluate_message_template(body, inputs, node_id)
    http_client = ssrf_guard.get_guarded_http_client()
    response = http_client.request(
        method,
        url,
        headers=headers,
        content=body,
        follow_redirects=follow_redirects,
    )
    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text
    output = {
        "status": response.status_code,
        "headers": dict(response.headers),
        "body": response_body,
        "request": {
            "method": method,
            "url": str(response.request.url),
            "headers": dict(response.request.headers),
        },
    }
    return output
