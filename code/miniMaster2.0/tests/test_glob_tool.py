import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.core.service import ToolService


class GlobWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def workspace(self, location):
        workspace = self.root / location
        workspace.mkdir(parents=True, exist_ok=True)
        for relative in (
            "app.py", "src/main.py", "src/nested/worker.py",
            ".config.py", ".github/check.py", "src/.private.py",
        ):
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# fixture\n", encoding="utf-8")
        return workspace, ToolService.bootstrap(str(workspace))

    def glob(self, service, pattern, **options):
        result = service.execute("glob", {"pattern": pattern, **options})
        self.assertTrue(result["success"], result)
        self.assertEqual(result["total_files"], len(result["files"]))
        self.assertEqual(result["total_directories"], len(result["directories"]))
        return result

    def test_visible_files_survive_hidden_workspace_names_and_ancestors(self):
        expected = ["app.py", os.path.join("src", "main.py"),
                    os.path.join("src", "nested", "worker.py")]
        for location in ("project", ".project", ".worktrees/project"):
            with self.subTest(location=location):
                _, service = self.workspace(location)
                self.assertTrue(service.execute("read", {"file_path": "app.py"})["success"])
                self.assertEqual(self.glob(service, "**/*.py")["files"], expected)
                self.assertEqual(self.glob(service, "*.py")["files"], ["app.py"])

    def test_absolute_pattern_within_workspace_returns_relative_files(self):
        workspace, service = self.workspace(".worktrees/absolute")
        result = self.glob(service, str(workspace / "src" / "*.py"))
        self.assertEqual(result["files"], [os.path.join("src", "main.py")])

    def test_hidden_descendants_remain_excluded_by_default(self):
        for location in ("visible", ".worktrees/hidden"):
            with self.subTest(location=location):
                _, service = self.workspace(location)
                for pattern in (".config.py", ".github/*.py", "src/.*"):
                    with self.subTest(pattern=pattern):
                        result = self.glob(service, pattern)
                        self.assertEqual(result["files"], [])
                        self.assertEqual(result["directories"], [])
                result = self.glob(service, ".github/*.py", include_hidden=True)
                self.assertEqual(result["files"], [os.path.join(".github", "check.py")])

    def test_nonrecursive_search_directories_limits_and_empty_results(self):
        _, service = self.workspace(".worktrees/controls")
        result = self.glob(service, "**/*.py", recursive=False)
        self.assertEqual(result["files"], [os.path.join("src", "main.py")])
        result = self.glob(service, "*")
        self.assertEqual(result["files"], ["app.py"])
        self.assertEqual(result["directories"], ["src"])
        result = self.glob(service, "*", max_results=1)
        self.assertEqual(result["files"], ["app.py"])
        self.assertEqual(result["directories"], [])
        result = self.glob(service, "*", max_results=0)
        self.assertEqual(result["files"] + result["directories"], [])
        result = self.glob(service, "missing/**/*.py")
        self.assertEqual(result["files"] + result["directories"], [])

    def test_explicit_paths_outside_workspace_keep_existing_behavior(self):
        _, service = self.workspace(".worktrees/inside")
        public = self.root / "outside.py"
        private = self.root / ".outside.py"
        public.write_text("# outside\n", encoding="utf-8")
        private.write_text("# outside\n", encoding="utf-8")
        self.assertEqual(self.glob(service, str(public))["files"], [str(public)])
        self.assertEqual(self.glob(service, str(private))["files"], [])
        result = self.glob(service, str(private), include_hidden=True)
        self.assertEqual(result["files"], [str(private)])


if __name__ == "__main__":
    unittest.main()
