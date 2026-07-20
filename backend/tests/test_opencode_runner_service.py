import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import settings
from app.services.coding_agent import pr_publish
from app.services.opencode_runner_service import (
    OpenCodeRunnerService,
    OpenCodeRunRequest,
    OpenCodeRunResult,
)

_WS = Path("/tmp/heym-oc-ws/run1")


def _request(**overrides) -> OpenCodeRunRequest:
    base = dict(
        repository_url="https://github.com/acme/app",
        base_branch="main",
        task_prompt="fix the tests",
        branch_name="opencode/run",
        publish_mode="diff_only",
        timeout_seconds=60.0,
        api_key="sk-secret",
        base_url="",
        github_config={"api_key": "ghp"},
        model="opencode/kimi-k3",
        variant="",
    )
    base.update(overrides)
    return OpenCodeRunRequest(**base)


class TestOpenCodeRunCommand(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(cli_command="opencode", workspace_root="/tmp/heym-oc-ws")

    def test_run_command_shape(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[0], "opencode")
        self.assertEqual(cmd[1], "run")
        self.assertIn("--format", cmd)
        self.assertEqual(cmd[cmd.index("--format") + 1], "json")
        self.assertEqual(cmd[cmd.index("--model") + 1], "opencode/kimi-k3")
        self.assertEqual(cmd[cmd.index("--agent") + 1], "build")
        self.assertNotIn("--variant", cmd)
        self.assertIn("Task:", cmd[-1])
        self.assertIn("Do NOT run git", cmd[-1])
        self.assertIn("bun install", cmd[-1])
        self.assertIn("PR_TITLE:", cmd[-1])
        self.assertNotIn("./check.sh", cmd[-1])
        self.assertNotIn("Do NOT install package managers", cmd[-1])

    def test_run_command_emphasizes_mandatory_pr_title(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        prompt = cmd[-1]
        self.assertIn("PR metadata is MANDATORY", prompt)
        self.assertIn("good PR title is specific", prompt)
        self.assertIn("Bad titles are generic", prompt)
        self.assertIn("## Summary", prompt)

    def test_run_command_includes_screenshot_instructions(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        prompt = cmd[-1]
        self.assertIn("MUST save at least one PNG screenshot", prompt)
        self.assertIn("frontend/.e2e-artifacts/", prompt)
        self.assertIn("Do not commit screenshot binaries", prompt)

    def test_run_command_pins_workspace_dir(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[cmd.index("--dir") + 1], str(_WS))

    def test_run_command_includes_variant(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(variant="high"), _WS)
        self.assertEqual(cmd[cmd.index("--variant") + 1], "high")

    def test_run_command_uses_wrapper_cli(self):
        svc = OpenCodeRunnerService(
            cli_command="/usr/local/bin/heym-opencode-docker", workspace_root="/tmp/x"
        )
        cmd = svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[0], "/usr/local/bin/heym-opencode-docker")


class TestOpenCodeAuthConfig(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_write_config_writes_auth_and_opencode_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.svc._write_opencode_config(
                home,
                api_key="sk-secret",
                base_url="https://opencode.ai/zen/go/v1",
                model="opencode/kimi-k3",
            )
            auth = json.loads((home / ".local" / "share" / "opencode" / "auth.json").read_text())
            self.assertEqual(auth["opencode"], {"type": "api", "key": "sk-secret"})
            cfg = json.loads((home / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(cfg["permission"]["edit"], "allow")
            self.assertEqual(cfg["permission"]["bash"], "allow")
            self.assertEqual(cfg["model"], "opencode/kimi-k3")
            options = cfg["provider"]["opencode"]["options"]
            self.assertEqual(options["baseURL"], "https://opencode.ai/zen/go/v1")
            self.assertEqual(options["apiKey"], "sk-secret")

    def test_default_model_when_empty(self):
        self.assertEqual(self.svc._resolve_model(""), "opencode/kimi-k3")
        self.assertEqual(
            self.svc._resolve_model("opencode/deepseek-v4-pro"), "opencode/deepseek-v4-pro"
        )


class TestOpenCodeParser(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_parse_extracts_last_assistant_text(self):
        stdout = "\n".join(
            [
                json.dumps({"type": "message.updated", "role": "assistant", "text": "thinking"}),
                json.dumps({"role": "assistant", "text": "Implemented the change."}),
            ]
        )
        result = self.svc.parse_events(stdout)
        self.assertEqual(result.summary, "Implemented the change.")
        self.assertEqual(result.status, "completed")

    def test_parse_tolerates_non_json_lines(self):
        stdout = "not json\n" + json.dumps({"role": "assistant", "text": "Done."})
        self.assertEqual(self.svc.parse_events(stdout).summary, "Done.")

    def test_parse_extracts_pr_title_line(self):
        stdout = json.dumps(
            {
                "role": "assistant",
                "text": (
                    "Moved the chat list toggle before History.\n\n"
                    "PR_TITLE: Reorder mobile chat header actions"
                ),
            }
        )
        result = self.svc.parse_events(stdout)
        self.assertEqual(result.pull_request_title, "Reorder mobile chat header actions")
        self.assertEqual(result.summary, "Moved the chat list toggle before History.")
        self.assertNotIn("PR_TITLE:", result.summary)

    def test_parse_ignores_user_role(self):
        stdout = json.dumps({"role": "user", "text": "the task"})
        self.assertNotEqual(self.svc.parse_events(stdout).summary, "the task")

    def test_parse_empty_gives_default_summary(self):
        result = self.svc.parse_events("")
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.summary)

    def test_parse_uses_task_prompt_for_fallback_summary(self):
        result = self.svc.parse_events("", task_prompt="Fix the OpenCode fallback summary logic")
        self.assertIn("OpenCode completed the requested task", result.summary)
        self.assertIn("Fix the OpenCode fallback summary logic", result.summary)

    def test_parse_fallback_summary_avoids_generic_message_when_prompt_present(self):
        result = self.svc.parse_events("", task_prompt="Add case-insensitive screenshot discovery")
        self.assertNotEqual(result.summary, "OpenCode completed without a final assistant message.")
        self.assertIn("Add case-insensitive screenshot discovery", result.summary)

    def test_parse_empty_task_prompt_falls_back_to_generic_message(self):
        result = self.svc.parse_events("", task_prompt="")
        self.assertEqual(result.summary, "OpenCode completed without a final assistant message.")


class TestOpenCodePrMetadataNormalization(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_ensure_meaningful_pr_title_prefers_agent_title(self):
        result = OpenCodeRunResult(
            summary="Did some work.",
            pull_request_title="Fix OpenCode fallback summary logic",
        )
        title = self.svc._ensure_meaningful_pr_title(result, "some task")
        self.assertEqual(title, "Fix OpenCode fallback summary logic")

    def test_ensure_meaningful_pr_title_skips_placeholder(self):
        result = OpenCodeRunResult(summary="Done.", pull_request_title="Done")
        title = self.svc._ensure_meaningful_pr_title(result, "Fix OpenCode fallback summary logic")
        self.assertEqual(title, "Fix OpenCode fallback summary logic")

    def test_ensure_meaningful_pr_title_derives_from_summary(self):
        result = OpenCodeRunResult(
            summary="Implemented the mobile drawer fix.", pull_request_title=""
        )
        title = self.svc._ensure_meaningful_pr_title(result, "fix ui")
        self.assertEqual(title, "Implemented the mobile drawer fix.")

    def test_ensure_meaningful_pr_title_last_resort_fallback(self):
        result = OpenCodeRunResult(summary="Done.", pull_request_title="")
        title = self.svc._ensure_meaningful_pr_title(result, "")
        self.assertEqual(title, "Apply OpenCode changes")

    def test_ensure_pr_body_enhances_short_body_with_task(self):
        result = OpenCodeRunResult(summary="Done.", pull_request_body="")
        body = self.svc._ensure_pr_body(result, "Fix OpenCode fallback summary logic")
        self.assertIn("## Task", body)
        self.assertIn("Fix OpenCode fallback summary logic", body)

    def test_ensure_pr_body_keeps_existing_long_body(self):
        long_body = "This is a sufficiently long PR body with enough context to remain unchanged."
        result = OpenCodeRunResult(
            summary="Summary text.",
            pull_request_body=long_body,
        )
        body = self.svc._ensure_pr_body(result, "task prompt")
        self.assertEqual(body, long_body)

    def test_normalize_pr_metadata_mutates_result(self):
        result = OpenCodeRunResult(summary="Done.", pull_request_title="Update")
        self.svc._normalize_pr_metadata(result, "Fix OpenCode fallback summary logic")
        self.assertEqual(result.pull_request_title, "Fix OpenCode fallback summary logic")
        self.assertIn("## Task", result.pull_request_body)


class TestOpenCodeExecFailureFormatting(unittest.TestCase):
    def test_event_stream_is_not_dumped_as_error(self) -> None:
        stdout = "\n".join(
            [
                json.dumps({"type": "step_start", "sessionID": "ses_1"}),
                json.dumps(
                    {
                        "type": "tool_use",
                        "part": {
                            "tool": "bash",
                            "state": {
                                "status": "completed",
                                "title": "./check.sh",
                                "output": "FATAL ERROR: JavaScript heap out of memory",
                                "metadata": {"exit": 134},
                            },
                        },
                    }
                ),
                json.dumps({"type": "step_start", "sessionID": "ses_1"}),
            ]
        )
        detail = OpenCodeRunnerService._format_exec_failure(137, stdout, "")
        self.assertNotIn('"sessionID"', detail)
        self.assertIn("bash: ./check.sh failed", detail)
        self.assertIn("heap out of memory", detail)
        self.assertIn("exited with code 137", detail)
        self.assertIn("OOM", detail)
        self.assertNotIn("avoid heavy ./check.sh", detail)

    def test_plain_stderr_is_preserved(self) -> None:
        detail = OpenCodeRunnerService._format_exec_failure(1, "", "opencode: command failed")
        self.assertEqual(detail, "opencode: command failed")


class TestOpenCodeCreatePr(unittest.TestCase):
    def setUp(self):
        self.runner = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")
        self.workspace = Path("/tmp/ws")
        self.request = _request(publish_mode="open_pr", branch_name="opencode/run")

    def test_create_pr_enhances_weak_title_and_body(self):
        result = OpenCodeRunResult(
            status="completed",
            summary="Done.",
            pull_request_title="Update",
            pull_request_body="",
            changed_files=["a.vue"],
        )
        self.runner._normalize_pr_metadata(result, self.request.task_prompt)
        gh = MagicMock()
        gh.create_pull_request.return_value = {
            "number": 1,
            "html_url": "https://github.com/acme/app/pull/1",
        }

        with patch("app.services.opencode_runner_service.GitHubService", return_value=gh) as gh_cls:
            url = self.runner._create_pr(
                self.workspace, self.request, result, "opencode/run", draft=False
            )

        self.assertEqual(url, "https://github.com/acme/app/pull/1")
        gh_cls.assert_called()
        title = gh.create_pull_request.call_args.args[2]
        body = gh.create_pull_request.call_args.kwargs["body"]
        self.assertNotEqual(title, "Update")
        self.assertIn("fix the tests", title.lower())
        self.assertIn("## Task", body)
        self.assertIn("fix the tests", body.lower())


class TestOpenCodePushBranch(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")
        self.runner._run_command = MagicMock()  # type: ignore[method-assign]
        self.workspace = Path("/tmp/ws")
        self.request = _request(publish_mode="update_existing_pr", branch_name="opencode/run")

    def test_existing_remote_branch_rebase_includes_git_identity(self) -> None:
        self.runner._git_output = MagicMock(  # type: ignore[method-assign]
            return_value="abc123\trefs/heads/opencode/run\n"
        )

        self.runner._push_branch(self.workspace, self.request, "opencode/run")

        commands = [call.args[0] for call in self.runner._run_command.call_args_list]
        self.assertEqual(
            commands[1],
            [
                "git",
                *pr_publish.git_identity_args(
                    settings.opencode_git_author_name, settings.opencode_git_author_email
                ),
                "pull",
                "--rebase",
                "--strategy-option=theirs",
                "origin",
                "opencode/run",
            ],
        )
        self.assertEqual(commands[2], ["git", "push", "-u", "origin", "opencode/run"])
