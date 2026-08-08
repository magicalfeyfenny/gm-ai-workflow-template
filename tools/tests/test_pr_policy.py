import unittest

from tools.ci.pr_policy import (
    branch_issue,
    forced_high_risk,
)


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

    def test_small_game_change_can_be_low_risk(self):
        high, reasons = forced_high_risk(
            "dev",
            ["game/scripts/player/player.gml"],
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


if __name__ == "__main__":
    unittest.main()