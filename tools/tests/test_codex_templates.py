import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CodexAutomationTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Load scheduled templates once for structural portability checks."""
        cls.templates = (
            ROOT / "templates/codex/governed-change.txt",
            ROOT / "templates/codex/project-steward.txt",
        )

    def test_scheduled_templates_remain_portable(self):
        """Keep templates free of repository- and issue-specific identity."""
        for template in self.templates:
            with self.subTest(template=template):
                text = template.read_text(encoding="utf-8")
                self.assertTrue(text.strip())
                normalized = " ".join(text.split()).casefold()

                for repository_identity in (
                    "gm-ai-workflow-template",
                    "magicalfeyfenny/",
                    "github.com/",
                ):
                    with self.subTest(identity=repository_identity):
                        self.assertNotIn(
                            repository_identity.casefold(),
                            normalized,
                        )

                self.assertIsNone(
                    re.search(
                        r"(?i)(?:\b(?:issue|pr)\s*#?\d+\b|#\d+\b)",
                        normalized,
                    )
                )

    def test_scheduled_completion_route_is_not_terminal_at_draft_or_ci(self):
        """Keep the scheduled worker moving through the whole completion route."""
        prompt = " ".join(
            (ROOT / "templates/codex/governed-change.txt")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        ordered_stages = (
            "do not stop after implementation",
            "re-fetch and reconcile the governing issue before stage 2",
            "stage 2 whole-issue local evidence",
            "immediately before the completion transition",
            "exactly one physical-line `closes #<issue>` line",
            "fresh stage 3 exact-head hosted evidence",
            "existing automatic workflow",
        )
        positions = []
        for stage in ordered_stages:
            with self.subTest(stage=stage):
                position = prompt.find(stage)
                self.assertGreaterEqual(position, 0)
                positions.append(position)
        self.assertEqual(positions, sorted(positions))

    def test_early_stop_fixtures_continue_into_whole_issue_evidence(self):
        """Keep both observed early-stop states on the same continuation route."""
        prompt = " ".join(
            (ROOT / "templates/codex/governed-change.txt")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        fixtures = (
            {
                "name": "bug-free-pancake issue 34 and draft PR 39",
                "state": (
                    "milestone commit",
                    "draft pr publication",
                    "hosted checks",
                ),
            },
            {
                "name": "bug-free-pancake issue 35 and draft PR 40",
                "state": (
                    "milestone commit",
                    "draft pr publication",
                    "hosted checks",
                ),
            },
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture["name"]):
                for state in fixture["state"]:
                    self.assertIn(state, prompt)
                self.assertIn(
                    "do not stop after implementation, a milestone commit, "
                    "draft pr publication, or hosted checks",
                    prompt,
                )
                self.assertIn("stage 2 whole-issue local evidence", prompt)

    def test_evidence_and_authority_boundaries_cover_completion_states(self):
        """Keep unavailable evidence, freshness, and actor boundaries explicit."""
        prompt = " ".join(
            (ROOT / "templates/codex/governed-change.txt")
            .read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        fixtures = {
            "stage 2 failure": (
                "missing, failed, stale, or mismatched",
                "blocks completion metadata",
            ),
            "unavailable capability": (
                "run all available evidence",
                "record that limitation accurately",
                "do not create a human-only gate",
            ),
            "stage 3 failure": (
                "stage 3 is not a prerequisite",
                "blocks readiness and auto-merge",
            ),
            "low/medium actor": (
                "existing automatic workflow",
                "mark the pr ready",
                "configure squash auto-merge",
            ),
            "manual actor": (
                "work:review-ready",
                "human review, readiness, and merge",
                "authority actions, not validation blockers",
            ),
            "worker boundary": (
                "do not directly mark ready, merge, bypass rulesets",
                "push protected branches",
                "release, or publish",
            ),
        }
        for name, markers in fixtures.items():
            with self.subTest(fixture=name):
                for marker in markers:
                    self.assertIn(marker, prompt)

    def test_scheduled_checks_use_the_repository_environment_router(self):
        """Keep dependency-sensitive scheduled checks on the bounded route."""
        prompt = (
            (ROOT / "templates/codex/governed-change.txt")
            .read_text(encoding="utf-8")
            .casefold()
        )
        self.assertIn("tools/ci/run_repository_checks.py", prompt)

    def test_scheduled_completion_routes_review_before_metadata(self):
        """Keep the governed review command between Stage 2 and completion."""
        prompt = " ".join(
            (ROOT / "templates/codex/governed-change.txt")
            .read_text(encoding="utf-8").casefold().split()
        )
        ordered_stages = (
            "stage 2 whole-issue local evidence",
            "adversarial_review_session.py run",
            "immediately before the completion transition",
            "fresh stage 3 exact-head hosted evidence",
        )
        positions = []
        for stage in ordered_stages:
            with self.subTest(stage=stage):
                position = prompt.find(stage)
                self.assertGreaterEqual(position, 0)
                positions.append(position)
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            "governance.md#adversarial-review-and-adjudication",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
