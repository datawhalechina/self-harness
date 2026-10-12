"""Offline task-lifecycle regressions; run with unittest discover -s tests."""

import contextlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bootstrap.runtime import build_runtime
from bootstrap.stage_context import build_stage_context
from domain.types import AgentAction
from engine.runner import run_task
from memory.session import SessionMemoryManager
from tools.core.service import ToolService


def action(tool, **parameters):
    return AgentAction(think="", tool=tool, parameters=parameters)


def conclusion(text="Task completed"):
    return action("update_task_conclusion", conclusion=text)


def verdict(valid):
    return action(
        "validate_tool",
        status="有效" if valid else "无效",
        reason="All checks passed" if valid else "A still needs work",
        covered_requirements=[],
        missing_requirements=[],
    )


class TaskMemoryTests(unittest.TestCase):
    def setUp(self):
        self.context = contextlib.ExitStack()
        self.addCleanup(self.context.close)
        workspace = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        (workspace / "a.txt").write_text("A_EXECUTOR_EVIDENCE", encoding="utf-8")
        (workspace / "validation-a.txt").write_text("A_VALIDATOR_EVIDENCE", encoding="utf-8")
        self.runtime = build_runtime(
            "Complete independent tasks", "offline", 1, None,
            ToolService.bootstrap(str(workspace)),
        )
        self.runtime.max_task_retries = 1
        self.runtime.max_generator_steps = 2
        self.runtime.max_validate_steps = 2
        self.runtime.todo_list.init_tasks(["A", "B"])
        self.stages = build_stage_context(self.runtime.tool_service)
        self.session = SessionMemoryManager(self.runtime)
        self.executor_actions = []
        self.validator_actions = []
        self.executor_prompts = []
        self.context.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.context.enter_context(patch("engine.runner.request_agent_action", side_effect=self.executor))
        self.context.enter_context(patch("engine.validator.request_agent_action", side_effect=self.validator))

    def executor(self, **kwargs):
        self.executor_prompts.append(kwargs["prompt"])
        next_action = self.executor_actions.pop(0)
        if isinstance(next_action, Exception):
            raise next_action
        return next_action

    def validator(self, **kwargs):
        next_action = self.validator_actions.pop(0)
        if isinstance(next_action, Exception):
            raise next_action
        return next_action

    def run_task(self, name):
        run_task(self.runtime, name, self.stages, self.session)

    def assert_empty_stage_memory(self):
        self.assertEqual(self.runtime.generator_memory.get_all_memories(), [])
        self.assertEqual(self.runtime.validation_memory.get_all_memories(), [])

    def complete_b(self):
        self.executor_actions = [conclusion("B completed")]
        self.validator_actions = [verdict(True)]
        self.run_task("B")
        first_prompt = self.executor_prompts[-1]
        self.assertNotIn("A_EXECUTOR_EVIDENCE", first_prompt)
        self.assertNotIn("A_VALIDATOR_EVIDENCE", first_prompt)
        self.assertNotIn("B", self.runtime.retry_archive_by_task)
        self.assertEqual(self.runtime.todo_list.get_task_by_name("B").task_status, "DONE")

    def fail_a_validation(self):
        self.executor_actions = [action("read", file_path="a.txt"), conclusion("A incomplete")]
        self.validator_actions = [action("read", file_path="validation-a.txt"), verdict(False)]
        self.run_task("A")
        self.assertEqual(self.runtime.todo_list.get_task_by_name("A").task_status, "FAILED")

    def test_failed_task_evidence_does_not_enter_next_task_prompt(self):
        self.fail_a_validation()
        self.complete_b()

    def test_final_failed_attempt_is_archived_under_its_own_task(self):
        self.fail_a_validation()
        archive = self.session.get_retry_history_prompt("A")
        self.assertIn("A_EXECUTOR_EVIDENCE", archive)
        self.assertIn("A_VALIDATOR_EVIDENCE", archive)
        self.assertIn("A still needs work", archive)
        self.assert_empty_stage_memory()

    def test_same_task_retry_preserves_evidence_and_clears_previous_validation(self):
        self.runtime.max_task_retries = 2
        self.executor_actions = [
            action("read", file_path="a.txt"), conclusion("A incomplete"),
            action("read", file_path="a.txt"), action("read", file_path="a.txt"),
        ]
        self.validator_actions = [action("read", file_path="validation-a.txt"), verdict(False)]
        self.run_task("A")
        self.assertIn("A_EXECUTOR_EVIDENCE", self.executor_prompts[2])
        self.assertIn("A_VALIDATOR_EVIDENCE", self.executor_prompts[2])
        archives = self.runtime.retry_archive_by_task["A"]
        self.assertEqual(len(archives), 2)
        self.assertNotIn("A_VALIDATOR_EVIDENCE", archives[-1])
        self.assert_empty_stage_memory()

    def test_explicit_retry_after_another_task_retains_own_failure_evidence(self):
        self.fail_a_validation()
        self.complete_b()
        self.assertTrue(self.runtime.todo_list.retry_task("A", "Required input is now available"))
        self.executor_actions = [conclusion("A completed")]
        self.validator_actions = [verdict(True)]
        self.run_task("A")
        self.assertIn("A_EXECUTOR_EVIDENCE", self.executor_prompts[-1])
        self.assertIn("A_VALIDATOR_EVIDENCE", self.executor_prompts[-1])
        self.assertNotIn("B completed", self.executor_prompts[-1])
        self.assert_empty_stage_memory()

    def test_successful_task_does_not_create_retry_archive(self):
        self.executor_actions = [action("read", file_path="a.txt"), conclusion("A completed")]
        self.validator_actions = [verdict(True)]
        self.run_task("A")
        self.assertNotIn("A", self.runtime.retry_archive_by_task)
        self.assert_empty_stage_memory()
        self.complete_b()

    def test_empty_retry_does_not_evict_previous_failure_evidence(self):
        self.fail_a_validation()
        self.assertTrue(self.runtime.todo_list.retry_task("A", "Retry after a transient failure"))
        for _ in range(2):
            self.executor_actions = [RuntimeError("offline model failure")]
            with self.assertRaisesRegex(RuntimeError, "offline model failure"):
                self.run_task("A")
            archive = self.session.get_retry_history_prompt("A")
            self.assertIn("A_EXECUTOR_EVIDENCE", archive)
            self.assertIn("A_VALIDATOR_EVIDENCE", archive)
        self.executor_actions = [conclusion("A completed")]
        self.validator_actions = [verdict(True)]
        self.run_task("A")
        self.assertIn("A_EXECUTOR_EVIDENCE", self.executor_prompts[-1])
        self.assertIn("A_VALIDATOR_EVIDENCE", self.executor_prompts[-1])

    def test_new_conclusion_survives_validator_request_failure(self):
        self.fail_a_validation()
        self.assertTrue(self.runtime.todo_list.retry_task("A", "Ready to revise the conclusion"))
        self.executor_actions = [conclusion("A updated conclusion after retry")]
        self.validator_actions = [RuntimeError("offline validator failure")]
        with self.assertRaisesRegex(RuntimeError, "offline validator failure"):
            self.run_task("A")
        self.assertEqual(
            self.runtime.todo_list.get_task_by_name("A").task_conclusion,
            "A updated conclusion after retry",
        )
        self.executor_actions = [conclusion("A completed")]
        self.validator_actions = [verdict(True)]
        self.run_task("A")
        self.assertIn("A updated conclusion after retry", self.executor_prompts[-1])
        self.assertIn("A_EXECUTOR_EVIDENCE", self.executor_prompts[-1])
        self.assertIn("A_VALIDATOR_EVIDENCE", self.executor_prompts[-1])

    def test_timeout_archives_evidence_and_clears_stage_memory(self):
        self.executor_actions = [action("read", file_path="a.txt")]
        with patch("engine.runner.has_runtime_time_left", side_effect=[True, True, False]):
            self.run_task("A")
        self.assertEqual(self.runtime.todo_list.get_task_by_name("A").task_status, "BLOCKED")
        self.assertIn("A_EXECUTOR_EVIDENCE", self.session.get_retry_history_prompt("A"))
        self.assert_empty_stage_memory()
        self.runtime.started_at_monotonic = time.monotonic()
        self.complete_b()

    def test_model_exception_archives_evidence_without_swallowing_error(self):
        self.executor_actions = [action("read", file_path="a.txt"), RuntimeError("offline model failure")]
        with self.assertRaisesRegex(RuntimeError, "offline model failure"):
            self.run_task("A")
        self.assertIn("A_EXECUTOR_EVIDENCE", self.session.get_retry_history_prompt("A"))
        self.assert_empty_stage_memory()
        self.complete_b()

    def test_interrupted_task_can_resume_with_its_own_evidence(self):
        self.executor_actions = [action("read", file_path="a.txt"), RuntimeError("offline model failure")]
        with self.assertRaisesRegex(RuntimeError, "offline model failure"):
            self.run_task("A")
        self.assertEqual(self.runtime.todo_list.get_task_by_name("A").task_status, "RUNNING")
        self.executor_actions = [conclusion("A completed after interruption")]
        self.validator_actions = [verdict(True)]
        self.run_task("A")
        self.assertIn("A_EXECUTOR_EVIDENCE", self.executor_prompts[-1])
        self.assertEqual(self.runtime.todo_list.get_task_by_name("A").task_status, "DONE")
        self.assert_empty_stage_memory()


if __name__ == "__main__":
    unittest.main()
