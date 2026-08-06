"""Unit tests for permission_tool_scope -- the permission-to-tool gate.

No model/network calls: permission_tool_scope is a pure function over a
PERMISSIONS.yaml permissions list. A second guard here reads all 24 employee
files directly so a SHIP-style gap (git-capable but nothing to commit) fails
CI instead of waiting for the next manual PM audit.
"""

import unittest
from pathlib import Path

import yaml

from apps.api import main

EMPLOYEES_ROOT = Path("employees")


def all_permission_files():
    return sorted(EMPLOYEES_ROOT.glob("*/*/PERMISSIONS.yaml"))


class PermissionToolScopeTests(unittest.TestCase):
    def test_read_only_grants_no_write_tools(self):
        scope = main.permission_tool_scope(["P0_READ"])
        self.assertIn("read_file", scope)
        self.assertNotIn("create_file", scope)
        self.assertNotIn("git_commit", scope)

    def test_write_content_tier_collapses_all_p2_variants(self):
        for code in ["P2_ARCH_WRITE", "P2_MARKETING_DOC_WRITE", "P2_DOC_WRITE", "P2_STATE_WRITE"]:
            with self.subTest(code=code):
                scope = main.permission_tool_scope([code])
                self.assertEqual(scope, {"create_file", "replace_exact_text", "apply_unified_patch"})

    def test_git_safe_and_staging_are_independent(self):
        self.assertEqual(main.permission_tool_scope(["P4_GIT_SAFE"]), {"git_commit"})
        self.assertEqual(main.permission_tool_scope(["P5_STAGING_WITH_APPROVAL"]), {"git_push"})

    def test_unmapped_codes_grant_nothing(self):
        scope = main.permission_tool_scope(["P3_PROCESS_CONTROL", "P4_EVIDENCE_READ", "P4_REVIEW"])
        self.assertEqual(scope, set())

    def test_unknown_code_is_ignored_not_an_error(self):
        self.assertEqual(main.permission_tool_scope(["NOT_A_REAL_CODE"]), set())

    def test_scopes_union_across_codes(self):
        scope = main.permission_tool_scope(["P0_READ", "P4_GIT_SAFE"])
        self.assertIn("read_file", scope)
        self.assertIn("git_commit", scope)


class EmployeePermissionCoverageTests(unittest.TestCase):
    """Regression guard for the SHIP gap found in the 2026-08-06 audit:
    git_safe/staging without write_content means nothing can ever be committed.
    """

    def test_every_employee_with_git_capability_can_also_write(self):
        gaps = []
        for path in all_permission_files():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            codes = data.get("permissions", [])
            tiers = {main.PERMISSION_TIER.get(code) for code in codes}
            if ("git_safe" in tiers or "staging" in tiers) and "write_content" not in tiers:
                gaps.append(data.get("employee", path.parent.name))
        self.assertEqual(gaps, [], f"employees with git access but no write_content tier: {gaps}")

    def test_all_permission_codes_are_known(self):
        unknown = set()
        for path in all_permission_files():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for code in data.get("permissions", []):
                if code not in main.PERMISSION_TIER:
                    unknown.add(code)
        self.assertEqual(unknown, set(), f"PERMISSIONS.yaml codes with no tier mapping: {unknown}")


if __name__ == "__main__":
    unittest.main()
