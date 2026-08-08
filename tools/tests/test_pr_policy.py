import unittest
from pathlib import Path

from tools.ci.pr_policy import (
    branch_issue,
    changed_file_paths,
    forced_high_risk,
)

ROOT = Path(__file__).resolve().parents[2]


class PrPolicyTests(unittest.TestCase):
    def test_work_branch(self):
        issue, errors = branch_issue(
            "dev",
            "work/12-stage-editor",
        )

        self.assertEqual(issue, 12)
        self.assertEqual(errors, [])

    def test_invalid_work_branch(self):
        issue, errors = branch_issue(
            "dev",
            "feature/stage-editor",
        )

        self.assertIsNone(issue)
        self.assertTrue(errors)

    def test_release_branch(self):
        issue, errors = branch_issue(
            "main",
            "release/27-v1.0.0",
        )

        self.assertEqual(issue, 27)
        self.assertEqual(errors, [])

    def test_sensitive_path_is_high_risk(self):
        high, reasons = forced_high_risk(
            "dev",
            [".github/workflows/ci.yml"],
            1,
            1,
        )

        self.assertTrue(high)
        self.assertTrue(reasons)

    def test_project_sensitive_paths_are_high_risk(self):
        paths = [
            "project/game.yyp",
            "project/options/main/options_main.yy",
            "project/extensions/store/store.yy",
            "project/scripts/core/state.gml",
            "project/scripts/save/write_save.gml",
            "project/scripts/persistence/profile.gml",
            "project/scripts/migrations/save_v2.gml",
        ]

        for path in paths:
            with self.subTest(path=path):
                high, reasons = forced_high_risk(
                    "dev",
                    [path],
                    1,
                    0,
                )

                self.assertTrue(high)
                self.assertTrue(reasons)

    def test_small_game_change_can_be_low_risk(self):
        high, reasons = forced_high_risk(
            "dev",
            ["project/scripts/player/player.gml"],
            20,
            10,
        )

        self.assertFalse(high)
        self.assertEqual(reasons, [])

    def test_main_is_high_risk(self):
        high, reasons = forced_high_risk(
            "main",
            ["README.md"],
            1,
            1,
        )

        self.assertTrue(high)
        self.assertIn(
            "PR targets main",
            reasons,
        )

    def test_rename_preserves_sensitive_source_path(self):
        paths, count = changed_file_paths(
            [[
                {
                    "filename": (
                        "project/scripts/player/state.gml"
                    ),
                    "previous_filename": (
                        "project/scripts/core/state.gml"
                    ),
                }
            ]]
        )

        high, reasons = forced_high_risk(
            "dev",
            paths,
            0,
            0,
            count,
        )

        self.assertEqual(count, 1)
        self.assertTrue(high)
        self.assertTrue(reasons)

    def test_renames_do_not_inflate_changed_file_count(self):
        entries = [
            {
                "filename": (
                    f"project/scripts/player/new_{index}.gml"
                ),
                "previous_filename": (
                    f"project/scripts/archive/old_{index}.gml"
                ),
            }
            for index in range(20)
        ]

        paths, count = changed_file_paths([entries])
        high, reasons = forced_high_risk(
            "dev",
            paths,
            20,
            20,
            count,
        )

        self.assertEqual(count, 20)
        self.assertEqual(len(paths), 40)
        self.assertFalse(high)
        self.assertEqual(reasons, [])


class WorkflowPolicyTests(unittest.TestCase):
    def test_collectors_preserve_complete_file_records(self):
        workflows = [
            ROOT / ".github/workflows/ci.yml",
            ROOT / ".github/workflows/low-risk-auto-merge.yml",
        ]

        for workflow in workflows:
            with self.subTest(workflow=workflow.name):
                text = workflow.read_text(encoding="utf-8")

                self.assertIn("--slurp", text)
                self.assertNotIn("--jq '.[].filename'", text)

    def test_auto_merge_is_revocable_and_head_bound(self):
        path = ROOT / ".github/workflows/low-risk-auto-merge.yml"
        text = path.read_text(encoding="utf-8")

        self.assertIn("pull_request_target:", text)
        self.assertIn("--disable-auto", text)
        self.assertIn(
            "stale auto-merge request remains",
            (ROOT / ".github/workflows/ci.yml").read_text(
                encoding="utf-8"
            ),
        )
        self.assertIn(
            '--match-head-commit "$CI_HEAD"',
            text,
        )

if __name__ == "__main__":
    unittest.main()
