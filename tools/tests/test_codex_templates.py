import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CodexAutomationTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Load the scheduled governed-change prompt once for focused checks."""
        cls.prompt = (
            ROOT / "templates/codex/governed-change.txt"
        ).read_text(encoding="utf-8")
        cls.prompt_flat = " ".join(cls.prompt.split())
        cls.prompt_casefold = cls.prompt_flat.casefold()

    def test_governed_change_selects_one_live_eligible_issue(self):
        """Keep the scheduled worker's task-specific eligibility contract."""
        required_contract = (
            "Use the governed-change skill for this repository.",
            "live open GitHub issues",
            "at most one eligible issue",
            "direct-request issue-creation permission does not apply",
            "an atomic implementation issue with actionable acceptance criteria and bounded scope",
            "unassigned or assigned to the automation's current user",
            "not labeled `work:blocked`",
            "no unresolved dependency",
            "no existing implementation branch or open pull request",
            "not human-owned",
            "`human/*` branch",
            "`human-created` change",
            "fresh human authority",
        )

        for text in required_contract:
            with self.subTest(text=text):
                self.assertIn(text, self.prompt_flat)

    def test_selection_order_and_no_candidate_stop_are_explicit(self):
        """Keep scheduled ordering, freshness, and no-replacement behavior."""
        required_contract = (
            "Prefer the oldest eligible issue",
            "explicit priority or dependency data",
            "Immediately before starting governed work",
            "recheck every eligibility condition",
            "stop without modifying repository state",
            "do not create a replacement issue",
            "no candidate was available",
            "Do not absorb unrelated fixes",
        )

        for text in required_contract:
            with self.subTest(text=text):
                self.assertIn(text, self.prompt_flat)

    def test_result_contract_and_portability(self):
        """Keep useful output fields without baking in repository identity."""
        for text in (
            "selected issue",
            "branch",
            "draft pull request",
            "validation state",
            "remaining blocker or required human action",
        ):
            with self.subTest(text=text):
                self.assertIn(text, self.prompt_flat)

        for repository_identity in (
            "gm-ai-workflow-template",
            "magicalfeyfenny/",
            "github.com/",
        ):
            with self.subTest(text=repository_identity):
                self.assertNotIn(
                    repository_identity.casefold(),
                    self.prompt_casefold,
                )

        self.assertIsNone(
            re.search(
                r"(?i)(?:\b(?:issue|pr)\s*#?\d+\b|#\d+\b)",
                self.prompt_flat,
            )
        )


if __name__ == "__main__":
    unittest.main()
