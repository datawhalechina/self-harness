"""Exercise the Agent's grep tool through real search backends."""

from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.core.service import ToolService


class GrepToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.service = ToolService.bootstrap(str(self.workspace))
        (self.workspace / "notes.txt").write_text(
            "Use --help for options.\nCompiler -DDEBUG is enabled.\nalpha1\nalpha2\n",
            encoding="utf-8",
        )
        (self.workspace / "-notes.txt").write_text("needle\n", encoding="utf-8")
        (self.workspace / "--help").write_text("needle\n", encoding="utf-8")

    def assert_single_match(self, result, filename, text, line_number=1):
        self.assertTrue(result["success"], result)
        self.assertEqual(result["total_matches"], 1, result)
        match = result["matches"][0]
        self.assertEqual(match["file"], filename)
        self.assertEqual(match["matched_text"], text)
        self.assertEqual(match["line_number"], line_number)

    @unittest.skipUnless(shutil.which("rg"), "ripgrep is required for subprocess tests")
    def test_ripgrep_searches_patterns_that_look_like_options(self):
        for pattern, line in [("--help", 1), ("-DDEBUG", 2)]:
            with self.subTest(pattern=pattern):
                result = self.service.execute("grep", {"pattern": pattern, "path": "notes.txt"})
                self.assert_single_match(result, "notes.txt", pattern, line)

    @unittest.skipUnless(shutil.which("rg"), "ripgrep is required for subprocess tests")
    def test_ripgrep_searches_paths_that_look_like_options(self):
        for filename in ["-notes.txt", "--help"]:
            with self.subTest(filename=filename):
                result = self.service.execute("grep", {"pattern": "needle", "path": filename})
                self.assert_single_match(result, filename, "needle")

    @unittest.skipUnless(shutil.which("rg"), "ripgrep is required for subprocess tests")
    def test_ripgrep_keeps_regex_filters_recursion_and_result_limit(self):
        (self.workspace / "nested").mkdir()
        (self.workspace / "nested" / "more.txt").write_text("alpha3\n", encoding="utf-8")
        (self.workspace / "ignored.md").write_text("alpha4\n", encoding="utf-8")
        params = {"pattern": r"^alpha\d\b", "include_pattern": "*.txt", "recursive": False}
        result = self.service.execute("grep", params)
        self.assertTrue(result["success"], result)
        self.assertEqual({m["matched_text"] for m in result["matches"]}, {"alpha1", "alpha2"})
        self.assertTrue(all(m["file"] == "notes.txt" for m in result["matches"]))

        result = self.service.execute("grep", {**params, "recursive": True})
        self.assertTrue(result["success"], result)
        self.assertEqual({m["matched_text"] for m in result["matches"]}, {"alpha1", "alpha2", "alpha3"})
        result = self.service.execute("grep", {**params, "max_results": 1})
        self.assertTrue(result["success"], result)
        self.assertEqual(result["total_matches"], 1)

    @unittest.skipUnless(shutil.which("rg"), "ripgrep is required for subprocess tests")
    def test_ripgrep_distinguishes_invalid_regex_from_no_matches(self):
        invalid = self.service.execute("grep", {"pattern": "(", "path": "notes.txt"})
        self.assertFalse(invalid["success"])
        self.assertTrue(invalid["error"])
        missing = self.service.execute("grep", {"pattern": "--not-in-file", "path": "notes.txt"})
        self.assertTrue(missing["success"], missing)
        self.assertEqual(missing["total_matches"], 0)

    def test_python_fallback_accepts_the_same_option_like_inputs(self):
        # Only binary discovery is replaced; the fallback reads the real files.
        with patch("tools.search_tool.grep_tool.shutil.which", return_value=None):
            result = self.service.execute("grep", {"pattern": "--help", "path": "notes.txt"})
            self.assert_single_match(result, "notes.txt", "--help")
            result = self.service.execute("grep", {"pattern": "needle", "path": "-notes.txt"})
            self.assert_single_match(result, "-notes.txt", "needle")


if __name__ == "__main__":
    unittest.main()
