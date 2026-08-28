"""Regression tests for HTTP-node JSON request-body templates."""

import json
import unittest
from unittest.mock import patch

import httpx

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_executor import WorkflowExecutor


class HttpNodeRequestBodyTests(unittest.TestCase):
    """Ensure JSON body expressions are serialized safely."""

    def test_bare_string_expression_is_json_serialized(self) -> None:
        """A bare body expression can safely contain quotes, newlines, and UTF-8."""
        payload = {
            "channel": "C043U7YRLRJ",
            "thread_ts": "1787922196.184389",
            "text": 'Türkçe "MCP timeout" açıklaması\nİkinci satır',
        }
        curl = (
            "curl -X POST https://slack.com/api/chat.postMessage "
            "-H 'Content-Type: application/json; charset=utf-8' "
            '-d \'{"channel":"$source.channel","thread_ts":"$source.thread_ts",'
            '"text":$source.text}\''
        )
        received_requests: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            received_requests.append(request)
            return httpx.Response(200, json={"ok": True}, request=request)

        context = NodeExecutionContext(
            executor=WorkflowExecutor(nodes=[], edges=[]),
            node_id="http1",
            inputs={"source": payload},
            allow_branch_skip=True,
            start_time=0.0,
            node={},
            node_type="http",
            node_data={"curl": curl},
            node_label="Slack message",
        )
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            with (
                patch("app.services.ssrf_guard.guard_http_url"),
                patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
            ):
                http_node.execute(context)

        self.assertEqual(len(received_requests), 1)
        request = received_requests[0]
        self.assertEqual(json.loads(request.content.decode("utf-8")), payload)
        self.assertEqual(request.headers["content-length"], str(len(request.content)))
