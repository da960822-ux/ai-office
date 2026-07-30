import subprocess
import tempfile
import unittest
from pathlib import Path

from apps.api.agent_tools import AgentToolError, WorkspaceAgentTools, _require_public_url, tool_definitions


class WorkspaceAgentToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "private").mkdir()
        (self.root / "private" / "secret.txt").write_text("customer secret\n", encoding="utf-8")
        (self.root / "src" / "app.py").write_text("value = 'old'\nvalue = 'old'\n", encoding="utf-8")
        (self.root / "src" / "syntax.js").write_text("const value = 1;\n", encoding="utf-8")
        (self.root / "notes.txt").write_text("customer research evidence\n", encoding="utf-8")
        self.tools = WorkspaceAgentTools(self.root, ["src", "notes.txt"])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_search_respects_contract_path_and_returns_matches(self) -> None:
        result = self.tools.search_files("customer")
        self.assertEqual(result["results"][0]["path"], "notes.txt")
        self.assertNotIn("src/app.py", {item["path"] for item in result["results"]})
        with self.assertRaises(AgentToolError) as error:
            self.tools.search_files("secret", path="private")
        self.assertEqual(error.exception.status_code, 403)

    def test_exact_replacement_requires_expected_match_count_and_is_atomic_result(self) -> None:
        with self.assertRaises(AgentToolError) as error:
            self.tools.replace_exact_text("src/app.py", "old", "new")
        self.assertEqual(error.exception.status_code, 409)
        result = self.tools.replace_exact_text("src/app.py", "old", "new", expected_count=2)
        self.assertEqual(result["replacements"], 2)
        self.assertEqual((self.root / "src" / "app.py").read_text(encoding="utf-8"), "value = 'new'\nvalue = 'new'\n")

    def test_paths_cannot_escape_workspace_or_ignored_directory(self) -> None:
        with self.assertRaises(AgentToolError) as error:
            self.tools.path("../outside.txt")
        self.assertEqual(error.exception.status_code, 403)
        (self.root / ".git").mkdir()
        with self.assertRaises(AgentToolError) as error:
            self.tools.path(".git/config")
        self.assertEqual(error.exception.status_code, 403)

    def test_git_status_and_diff_are_bounded_read_only_tools(self) -> None:
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True, text=True)
        status = self.tools.git_status()
        self.assertIn("content", status)
        self.assertNotIn("private/secret.txt", status["content"])
        diff = self.tools.git_diff("src/app.py")
        self.assertIn("content", diff)

    def test_git_commit_is_path_scoped_and_push_validates_ref(self) -> None:
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "AI Office Test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "ai-office@example.invalid"], cwd=self.root, check=True)
        result = self.tools.git_commit("test: scoped change", ["src/app.py"])
        self.assertEqual(len(result["commit"]), 40)
        tracked = subprocess.run(
            ["git", "show", "--pretty=", "--name-only", "HEAD"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertEqual(tracked, ["src/app.py"])
        with self.assertRaises(AgentToolError):
            self.tools.git_push("../unsafe")

    def test_symbol_search_patch_and_create_are_surgical(self) -> None:
        (self.root / "src" / "symbol.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True, text=True)
        symbols = self.tools.find_symbols("hello", path="src")
        self.assertEqual(symbols["results"][0]["path"], "src/symbol.py")
        patch = (
            "--- a/src/symbol.py\n"
            "+++ b/src/symbol.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def hello():\n"
            "-    return 'world'\n"
            "+    return 'patched'\n"
        )
        result = self.tools.apply_unified_patch(patch)
        self.assertEqual(result["paths"], ["src/symbol.py"])
        self.assertIn("patched", (self.root / "src/symbol.py").read_text(encoding="utf-8"))
        self.assertEqual(self.tools.create_file("src/new.py", "VALUE = 1\n")["path"], "src/new.py")
        with self.assertRaises(AgentToolError):
            self.tools.create_file("src/new.py", "VALUE = 2\n")

    def test_reference_diagnostics_and_test_discovery_are_bounded(self) -> None:
        (self.root / "src" / "uses.py").write_text("def hello():\n    return hello\n", encoding="utf-8")
        (self.root / "src" / "test_uses.py").write_text("import unittest\n", encoding="utf-8")
        references = self.tools.find_references("hello", path="src")
        self.assertEqual(references["results"][0]["path"], "src/uses.py")
        diagnostics = self.tools.language_diagnostics("src/app.py")
        self.assertTrue(diagnostics["ok"])
        tests = self.tools.discover_tests("src")
        self.assertIn("src/test_uses.py", tests["files"])
        self.assertIn("python -m unittest discover", {item["command"] for item in tests["commands"]})

    def test_public_source_rejects_local_network_and_tool_schema_is_present(self) -> None:
        with self.assertRaises(AgentToolError) as error:
            _require_public_url("http://127.0.0.1:80/private")
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(
            {item["name"] for item in tool_definitions()},
            {
                "list_files", "read_file", "search_files", "find_symbols", "find_references",
                "language_diagnostics", "discover_tests",
                "replace_exact_text", "apply_unified_patch", "create_file",
                "git_status", "git_diff", "git_commit", "git_push", "fetch_public_source", "fetch_public_pdf", "render_public_page",
            },
        )


if __name__ == "__main__":
    unittest.main()
