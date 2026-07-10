"""Tests for surfacing skill-generated files on the agent node output.

The execution-log download button and `$agentLabel._generated_files` expressions
both rely on a top-level `_generated_files` array on the agent result, aggregated
from skill tool calls (including nested sub-agent calls and JSON output mode).
"""

from __future__ import annotations

import unittest

from app.services.node_execution.nodes.agent_node import (
    _collect_generated_files_from_output,
)


def _file(name: str, url: str) -> dict:
    return {
        "id": url.rsplit("/", 1)[-1],
        "filename": name,
        "mime_type": "text/plain",
        "size_bytes": 3,
        "download_url": url,
    }


class CollectGeneratedFilesTests(unittest.TestCase):
    def test_collects_from_tool_call_result(self) -> None:
        f = _file("report.txt", "https://x/api/files/dl/aaa")
        output = {
            "text": "done",
            "tool_calls": [{"name": "skill_x", "result": {"_generated_files": [f]}}],
        }
        self.assertEqual(_collect_generated_files_from_output(output), [f])

    def test_collects_from_nested_sub_agent_result(self) -> None:
        f = _file("nested.txt", "https://x/api/files/dl/bbb")
        output = {
            "text": "done",
            "tool_calls": [
                {
                    "name": "call_sub_agent",
                    "result": {
                        "text": "sub",
                        "tool_calls": [{"name": "skill_y", "result": {"_generated_files": [f]}}],
                    },
                }
            ],
        }
        self.assertEqual(_collect_generated_files_from_output(output), [f])

    def test_dedupes_by_download_url(self) -> None:
        f = _file("dup.txt", "https://x/api/files/dl/ccc")
        output = {
            "tool_calls": [
                {"name": "skill_a", "result": {"_generated_files": [f]}},
                {"name": "skill_b", "result": {"_generated_files": [dict(f)]}},
            ],
        }
        collected = _collect_generated_files_from_output(output)
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0]["download_url"], f["download_url"])

    def test_returns_empty_when_no_files(self) -> None:
        self.assertEqual(_collect_generated_files_from_output({"text": "hi"}), [])
        self.assertEqual(_collect_generated_files_from_output(None), [])
        self.assertEqual(_collect_generated_files_from_output("nope"), [])


if __name__ == "__main__":
    unittest.main()
