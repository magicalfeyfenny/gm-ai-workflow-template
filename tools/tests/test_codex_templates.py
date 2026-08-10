import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CodexAutomationTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prompt = (
            ROOT / "templates/codex/governed-change.txt"
        ).read_text(encoding="utf-8")
        cls.setup = (ROOT / "docs/SETUP.md").read_text(encoding="utf-8")
        cls.prompt_flat = " ".join(cls.prompt.split())
        cls.prompt_casefold = cls.prompt_flat.casefold()
        cls.setup_flat = " ".join(cls.setup.split())

    def test_governed_change_selects_one_live_eligible_issue(self):
        required_contract = (
            "Use the governed-change skill for this repository.",
            "live open GitHub issues",
            "at most one eligible issue",
            "actionable acceptance criteria and bounded scope",
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

    def test_selection_order_recheck_and_no_candidate_stop_are_explicit(self):
        required_contract = (
            "Prefer the oldest eligible issue",
            "explicit priority or dependency data",
            "Immediately before starting governed work",
            "recheck every eligibility condition",
            "stop without modifying repository state",
            "do not create a replacement issue",
            "no candidate was available",
            "Work no more than one issue per run",
            "do not absorb unrelated fixes",
        )

        for text in required_contract:
            with self.subTest(text=text):
                self.assertIn(text, self.prompt_flat)

    def test_result_contract_and_portability(self):
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

    def test_setup_distinguishes_the_two_manual_automations(self):
        required_setup = (
            "manually create whichever scheduled automations",
            "Choose each automation's schedule and execution identity",
            "templates/codex/project-steward.txt",
            "templates/codex/governed-change.txt",
            "Project Steward creates and tracks",
            "Governed Change executes one existing agent-workable issue",
        )

        for text in required_setup:
            with self.subTest(text=text):
                self.assertIn(text, self.setup_flat)


if __name__ == "__main__":
    unittest.main()
