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

    def test_public_source_rejects_local_network_and_tool_schema_is_present(self) -> None:
        with self.assertRaises(AgentToolError) as error:
            _require_public_url("http://127.0.0.1:80/private")
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(
            {item["name"] for item in tool_definitions()},
            {"search_files", "replace_exact_text", "git_status", "git_diff", "git_commit", "git_push", "fetch_public_source"},
        )


if __name__ == "__main__":
    unittest.main()
