"""Regression tests: ``$global.*`` in Playwright step fields must resolve at run time.

Step fields are compiled by ``playwright_code_generator`` into lookups against the flat
``inputs`` dict handed to the Playwright runner, so every expression namespace a user can
reference must be present in that dict. ``vars`` was already injected; ``global`` was not,
so ``$global.secondPage`` silently fell back to the generator's ``https://example.com``
placeholder instead of navigating to the configured URL.
"""

import re
import unittest

from app.services.playwright_code_generator import generate_playwright_code
from app.services.workflow_executor import WorkflowExecutor


def _executor(global_variables_context: dict[str, object] | None = None) -> WorkflowExecutor:
    return WorkflowExecutor(
        nodes=[{"id": "pw1", "type": "playwright", "data": {"label": "playwright"}}],
        edges=[],
        global_variables_context=global_variables_context,
    )


def _resolved_goto_urls(steps: list[dict], inputs: dict) -> list[object]:
    """Evaluate every generated ``page.goto(...)`` argument against the runner inputs."""
    code = generate_playwright_code(steps)
    args = re.findall(r"^\s*page\.goto\((.*)\)$", code, re.MULTILINE)
    return [eval(arg, {"__builtins__": {}}, {"inputs": inputs}) for arg in args]  # noqa: S307


class PlaywrightGlobalNamespaceTests(unittest.TestCase):
    def test_global_namespace_is_injected_into_runner_inputs(self) -> None:
        executor = _executor({"secondPage": "https://heym.run/pricing"})
        runner_inputs = executor._playwright_subprocess_inputs({})
        self.assertEqual(runner_inputs["global"]["secondPage"], "https://heym.run/pricing")

    def test_variable_node_values_are_merged_into_global(self) -> None:
        # `$global` mirrors `_build_context`: global variables first, variable-node values win.
        executor = _executor({"secondPage": "https://heym.run/pricing", "keep": "kept"})
        executor.vars = {"secondPage": "https://heym.run/solutions"}
        executor._mark_vars_context_dirty()
        runner_inputs = executor._playwright_subprocess_inputs({})
        self.assertEqual(runner_inputs["global"]["secondPage"], "https://heym.run/solutions")
        self.assertEqual(runner_inputs["global"]["keep"], "kept")

    def test_navigate_step_uses_global_url_not_placeholder(self) -> None:
        executor = _executor({"secondPage": "https://heym.run/pricing"})
        runner_inputs = executor._playwright_subprocess_inputs({})
        steps = [
            {"action": "navigate", "url": "https://heym.run/solutions"},
            {"action": "navigate", "url": "$global.secondPage"},
        ]
        self.assertEqual(
            _resolved_goto_urls(steps, runner_inputs),
            ["https://heym.run/solutions", "https://heym.run/pricing"],
        )

    def test_upstream_node_named_global_is_not_clobbered(self) -> None:
        executor = _executor({"secondPage": "https://heym.run/pricing"})
        runner_inputs = executor._playwright_subprocess_inputs(
            {"global": {"ownField": "from-upstream"}}
        )
        self.assertEqual(runner_inputs["global"]["ownField"], "from-upstream")
        self.assertEqual(runner_inputs["global"]["secondPage"], "https://heym.run/pricing")

    def test_vars_namespace_still_resolves(self) -> None:
        executor = _executor()
        executor.vars = {"searchUrl": "https://heym.run/docs"}
        executor._mark_vars_context_dirty()
        runner_inputs = executor._playwright_subprocess_inputs({})
        steps = [{"action": "navigate", "url": "$vars.searchUrl"}]
        self.assertEqual(_resolved_goto_urls(steps, runner_inputs), ["https://heym.run/docs"])


if __name__ == "__main__":
    unittest.main()
