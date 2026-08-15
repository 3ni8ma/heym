"""GHSA-6x65-w7q7-wg93 finding 1: webhook header_auth secret exposure."""

import datetime
import unittest
import uuid
from types import SimpleNamespace

from app.api.workflows import (
    _build_workflow_response,
    _build_workflow_version_response,
    _sanitize_headers,
    _webhook_secret_names,
)


def _workflow(*, owner_id: uuid.UUID, header_key: str | None, header_value: str | None):
    now = datetime.datetime.now(datetime.timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="wf",
        description=None,
        kind="workflow",
        nodes=[],
        edges=[],
        auth_type="header_auth",
        auth_header_key=header_key,
        auth_header_value=header_value,
        webhook_body_mode="legacy",
        allow_anonymous=False,
        owner_id=owner_id,
        folder_id=None,
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        sse_node_config=None,
        auto_recover_runs=True,
        error_workflow_id=None,
        minutes_saved_per_run=None,
        workflow_timeout_seconds=None,
        created_at=now,
        updated_at=now,
    )


class PersistedHeaderDenylistTests(unittest.TestCase):
    """The fixed denylist cannot know a workflow's own auth header name."""

    def test_configured_auth_header_is_stripped(self) -> None:
        workflow = _workflow(
            owner_id=uuid.uuid4(), header_key="X-Webhook-Secret", header_value="s3cr3t"
        )

        result = _sanitize_headers(
            {"X-Webhook-Secret": "s3cr3t", "Content-Type": "application/json"},
            _webhook_secret_names(workflow),
        )

        self.assertNotIn("x-webhook-secret", result)
        self.assertIn("content-type", result)

    def test_match_is_case_insensitive(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Webhook-Secret", header_value="s")

        result = _sanitize_headers({"x-WEBHOOK-secret": "s"}, _webhook_secret_names(workflow))

        self.assertEqual(result, {})

    def test_fixed_denylist_still_applies(self) -> None:
        result = _sanitize_headers({"Authorization": "Bearer x", "Accept": "*/*"})

        self.assertNotIn("authorization", result)
        self.assertIn("accept", result)

    def test_workflow_without_header_auth_adds_no_names(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key=None, header_value=None)

        self.assertEqual(_webhook_secret_names(workflow), ())

    def test_unrelated_query_style_headers_are_preserved(self) -> None:
        """Only the configured name is stripped; generic names stay usable."""
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Webhook-Secret", header_value="s")

        result = _sanitize_headers(
            {"X-Request-Id": "abc", "X-Token-Hint": "keep"}, _webhook_secret_names(workflow)
        )

        self.assertEqual(result, {"x-request-id": "abc", "x-token-hint": "keep"})


class WorkflowResponseMaskingTests(unittest.TestCase):
    def test_owner_still_reads_the_secret(self) -> None:
        owner_id = uuid.uuid4()
        workflow = _workflow(owner_id=owner_id, header_key="X-Key", header_value="s3cr3t")

        response = _build_workflow_response(workflow, owner_id)

        self.assertEqual(response.auth_header_value, "s3cr3t")
        self.assertTrue(response.auth_header_value_set)

    def test_collaborator_gets_null(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Key", header_value="s3cr3t")

        response = _build_workflow_response(workflow, uuid.uuid4())

        self.assertIsNone(response.auth_header_value)
        # Still told a secret exists so the editor can render it read-only.
        self.assertTrue(response.auth_header_value_set)

    def test_unset_secret_reports_not_set(self) -> None:
        owner_id = uuid.uuid4()
        workflow = _workflow(owner_id=owner_id, header_key=None, header_value=None)

        self.assertFalse(_build_workflow_response(workflow, owner_id).auth_header_value_set)


class WorkflowVersionMaskingTests(unittest.TestCase):
    def _version(self):
        return SimpleNamespace(
            id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            version_number=3,
            name="wf",
            description=None,
            nodes=[],
            edges=[],
            auth_type="header_auth",
            auth_header_key="X-Key",
            auth_header_value="s3cr3t",
            webhook_body_mode="legacy",
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            created_by_id=uuid.uuid4(),
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )

    def test_version_masks_for_collaborator(self) -> None:
        masked = _build_workflow_version_response(self._version(), is_owner=False)

        self.assertIsNone(masked.auth_header_value)
        self.assertTrue(masked.auth_header_value_set)

    def test_version_visible_to_owner(self) -> None:
        visible = _build_workflow_version_response(self._version(), is_owner=True)

        self.assertEqual(visible.auth_header_value, "s3cr3t")


if __name__ == "__main__":
    unittest.main()
