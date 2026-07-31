"""Unit tests for scripts/verify_docs_consistency.py.

These exercise the checker's own extraction and classification logic against
small synthetic docs/apps trees built in a tmp directory — never the real
docs/ tree, so this test suite does not fail when docs legitimately change.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import verify_docs_consistency as v


class DocsConsistencyTestCase(unittest.TestCase):
    """Base class that points the module's ROOT/DOCS/APPS at a fresh tmp
    tree for each test and restores them afterwards."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "apps" / "api").mkdir(parents=True)
        (self.root / "apps" / "web" / "src").mkdir(parents=True)

        self._orig_root = v.ROOT
        self._orig_docs = v.DOCS
        self._orig_apps = v.APPS
        v.ROOT = self.root
        v.DOCS = self.root / "docs"
        v.APPS = self.root / "apps"
        v.reset_caches()

    def tearDown(self) -> None:
        v.ROOT = self._orig_root
        v.DOCS = self._orig_docs
        v.APPS = self._orig_apps
        v.reset_caches()
        self._tmp.cleanup()

    def write_doc(self, name: str, text: str) -> Path:
        path = self.root / "docs" / name
        path.write_text(text, encoding="utf-8")
        return path

    def write_py(self, name: str, text: str) -> Path:
        path = self.root / "apps" / "api" / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_report(self) -> v.Report:
        report = v.Report()
        v.check_file_references(report)
        v.check_code_symbols(report)
        return report


class FileReferenceTests(DocsConsistencyTestCase):
    def test_valid_backtick_path_reference_is_not_flagged(self):
        self.write_py("main.py", "x = 1\n")
        self.write_doc("GUIDE.md", "See `apps/api/main.py` for details.\n")
        report = self.run_report()
        self.assertEqual([f for f in report.findings if f.category == "check1"], [])

    def test_broken_backtick_path_reference_is_an_error(self):
        self.write_doc("GUIDE.md", "See `apps/api/does_not_exist.py` for details.\n")
        report = self.run_report()
        errors = [f for f in report.findings if f.category == "check1" and f.level == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("does_not_exist.py", errors[0].message)
        self.assertEqual(errors[0].line, 1)

    def test_broken_markdown_link_is_an_error(self):
        self.write_doc("GUIDE.md", "See [other doc](MISSING.md) for details.\n")
        report = self.run_report()
        errors = [f for f in report.findings if f.category == "check1" and f.level == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("MISSING.md", errors[0].message)

    def test_valid_markdown_link_relative_to_doc_dir_is_not_flagged(self):
        self.write_doc("OTHER.md", "# other\n")
        self.write_doc("GUIDE.md", "See [other doc](OTHER.md) for details.\n")
        report = self.run_report()
        self.assertEqual([f for f in report.findings if f.category == "check1"], [])

    def test_allowlisted_path_exception_is_not_flagged(self):
        v.ALLOWLISTED_PATHS["some/made-up-path.md"] = "test allowlist entry"
        try:
            self.write_doc("GUIDE.md", "See `some/made-up-path.md` (allowlisted).\n")
            report = self.run_report()
            self.assertEqual([f for f in report.findings if f.category == "check1"], [])
        finally:
            del v.ALLOWLISTED_PATHS["some/made-up-path.md"]

    def test_fenced_code_block_paths_are_not_checked(self):
        # This is the false-positive category for planned-but-unbuilt file
        # trees: a path inside a ```text fence describing a future layout
        # must not be treated as a broken reference.
        self.write_doc(
            "GUIDE.md",
            "Planned layout:\n\n```text\napps/api/vibeoffice/not_built_yet.py\n```\n",
        )
        report = self.run_report()
        self.assertEqual([f for f in report.findings if f.category == "check1"], [])

    def test_control_flow_token_with_slash_is_not_a_path(self):
        # False-positive category: prose mentioning `try/finally` should
        # never be treated as a path reference just because it has a slash.
        self.write_doc("GUIDE.md", "Wrap the call in `try/finally` to close the handle.\n")
        report = self.run_report()
        self.assertEqual([f for f in report.findings if f.category == "check1"], [])


class CodeSymbolTests(DocsConsistencyTestCase):
    def test_valid_symbol_reference_is_not_flagged(self):
        self.write_py("worker.py", "def store_execution_plan():\n    pass\n")
        self.write_doc("GUIDE.md", "Call `store_execution_plan` after planning.\n")
        report = self.run_report()
        self.assertEqual([f for f in report.findings if f.category == "check2"], [])

    def test_unresolvable_symbol_is_a_warning_not_an_error(self):
        self.write_doc("GUIDE.md", "Call `totally_made_up_function_xyz` after planning.\n")
        report = self.run_report()
        matches = [f for f in report.findings if f.category == "check2"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].level, "WARNING")
        self.assertIn("totally_made_up_function_xyz", matches[0].message)

    def test_broken_file_line_reference_is_an_error(self):
        self.write_doc("GUIDE.md", "See `apps/api/missing.py:42` for the gate.\n")
        report = self.run_report()
        errors = [f for f in report.findings if f.category == "check2" and f.level == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("missing.py", errors[0].message)

    def test_line_number_beyond_eof_is_an_error(self):
        self.write_py("main.py", "line1\nline2\nline3\n")
        self.write_doc("GUIDE.md", "See `apps/api/main.py:99` for the gate.\n")
        report = self.run_report()
        errors = [f for f in report.findings if f.category == "check2" and f.level == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("only has", errors[0].message)

    def test_valid_file_line_reference_is_not_flagged(self):
        self.write_py("main.py", "line1\nline2\nline3\n")
        self.write_doc("GUIDE.md", "See `apps/api/main.py:2` for the gate.\n")
        report = self.run_report()
        self.assertEqual([f for f in report.findings if f.category == "check2"], [])

    def test_allowlisted_symbol_exception_is_not_flagged(self):
        v.ALLOWLISTED_SYMBOLS["MadeUpConceptName"] = "test allowlist entry"
        try:
            self.write_doc("GUIDE.md", "The `MadeUpConceptName` concept is informal.\n")
            report = self.run_report()
            self.assertEqual([f for f in report.findings if f.category == "check2"], [])
        finally:
            del v.ALLOWLISTED_SYMBOLS["MadeUpConceptName"]

    def test_shell_tool_name_is_not_flagged_as_a_symbol(self):
        # False-positive category: bare lowercase tool names with no
        # underscore (pytest, openpyxl, winget, rg, git) must not even be
        # treated as symbol candidates.
        self.write_doc("GUIDE.md", "Run `pytest` after installing `openpyxl`.\n")
        report = self.run_report()
        self.assertEqual([f for f in report.findings if f.category == "check2"], [])

    def test_employee_id_all_caps_is_not_flagged_as_a_symbol(self):
        # False-positive category: short all-caps employee/agent IDs like
        # GUARD/LENS (no underscore, no lowercase) are not Python constants.
        self.write_doc("GUIDE.md", "`GUARD` reviews the artifact before `LENS` does.\n")
        report = self.run_report()
        self.assertEqual([f for f in report.findings if f.category == "check2"], [])


class SymbolCandidateShapeTests(unittest.TestCase):
    """Pure classification logic — no filesystem involved."""

    def test_snake_case_function_shape_is_a_candidate(self):
        self.assertTrue(v.is_symbol_candidate("assert_completion_invariants"))

    def test_all_caps_constant_shape_is_a_candidate(self):
        self.assertTrue(v.is_symbol_candidate("DEFAULT_THRESHOLDS"))

    def test_pascal_case_class_shape_is_a_candidate(self):
        self.assertTrue(v.is_symbol_candidate("TaskContract"))

    def test_bare_lowercase_word_is_not_a_candidate(self):
        self.assertFalse(v.is_symbol_candidate("pytest"))

    def test_all_caps_no_underscore_is_not_a_candidate(self):
        self.assertFalse(v.is_symbol_candidate("GUARD"))


if __name__ == "__main__":
    unittest.main()
