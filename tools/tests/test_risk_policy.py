import unittest

from tools.ci.pr_policy import (
    AUTOMATIC_RISK_LABELS,
    CORRECTION_RETRY_BUDGETS,
    HIGH_RISK_BASES,
    RISK_LABELS,
    correction_retry_budget,
    evaluate_pull_request,
)


class RiskTierPolicyTests(unittest.TestCase):
    """Exercise the three-tier risk contract through semantic fixtures."""

    def test_risk_label_inventory_has_one_automatic_medium_tier(self) -> None:
        """Keep executable labels aligned with the three-tier contract."""
        self.assertEqual(
            RISK_LABELS,
            {"risk:low", "risk:medium", "risk:high"},
        )
        self.assertEqual(
            AUTOMATIC_RISK_LABELS,
            {"risk:low", "risk:medium"},
        )

    def test_structured_high_risk_bases_and_retry_budgets_are_configured(self) -> None:
        self.assertEqual(
            HIGH_RISK_BASES,
            {
                "governance-authority",
                "ci-merge-release",
                "security-credentials",
                "destructive-operation",
                "compatibility-migration",
                "persistence-data-loss",
                "cross-system-blast-radius",
                "exceptional-uncertainty",
            },
        )
        self.assertEqual(
            CORRECTION_RETRY_BUDGETS,
            {"low": 1, "medium": 2, "high": 2},
        )
        self.assertEqual(correction_retry_budget("low"), 1)
        self.assertEqual(correction_retry_budget("medium"), 2)
        self.assertEqual(correction_retry_budget("high"), 2)

    def test_medium_substantial_ordinary_work_is_automatic(self) -> None:
        """Keep substantial safe product work on the automatic path."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-titan-finale",
            head_repository="owner/game",
            repository="owner/game",
            body=(
                "Closes #12\n"
                "Focused validation: `python3 -m unittest "
                "tools.tests.test_titan_finale`\n"
            ),
            labels={"risk:medium", "work:complete"},
            additions=850,
            deletions=120,
            changed_paths=[
                "project/scripts/titan/state.gml",
                "project/scripts/titan/attacks.gml",
            ],
            changed_file_count=2,
        )

        self.assertEqual(evaluation.errors, ())
        self.assertFalse(evaluation.effective_high)
        self.assertTrue(evaluation.auto_merge_allowed)

    def test_medium_milestone_can_defer_focused_evidence(self) -> None:
        """Require medium evidence at completion, not at every milestone."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-titan-finale",
            head_repository="owner/game",
            repository="owner/game",
            body="Implementation milestone.\n",
            labels={"risk:medium"},
            additions=850,
            deletions=120,
            changed_paths=["project/scripts/titan/state.gml"],
            changed_file_count=1,
        )

        self.assertEqual(evaluation.errors, ())

    def test_medium_completion_requires_focused_evidence(self) -> None:
        """Do not let generic completion metadata satisfy medium validation."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-titan-finale",
            head_repository="owner/game",
            repository="owner/game",
            body="Closes #12\n",
            labels={"risk:medium", "work:complete"},
            additions=100,
            deletions=10,
            changed_paths=["project/scripts/titan/state.gml"],
            changed_file_count=1,
        )

        self.assertTrue(
            any(
                "risk:medium completion requires focused" in error
                for error in evaluation.errors
            )
        )
        self.assertFalse(evaluation.auto_merge_allowed)

    def test_medium_generic_evidence_does_not_satisfy_focus(self) -> None:
        """Repository-wide and formatting checks are not focused evidence."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-titan-finale",
            head_repository="owner/game",
            repository="owner/game",
            body=(
                "Closes #12\n"
                "Focused validation: `python3 tools/ci/run_repository_checks.py "
                "all --baseline-ref origin/dev`\n"
            ),
            labels={"risk:medium", "work:complete"},
            additions=100,
            deletions=10,
            changed_paths=["project/scripts/titan/state.gml"],
            changed_file_count=1,
        )

        self.assertTrue(
            any(
                "risk:medium focused validation must establish" in error
                for error in evaluation.errors
            )
        )

    def test_medium_cannot_override_forced_high(self) -> None:
        """Keep governance and CI paths monotonically high risk."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-titan-finale",
            head_repository="owner/game",
            repository="owner/game",
            body=(
                "Closes #12\n"
                "Focused validation: `python3 -m unittest "
                "tools.tests.test_titan_finale`\n"
            ),
            labels={"risk:medium", "work:complete"},
            additions=100,
            deletions=10,
            changed_paths=["tools/ci/pr_policy.py"],
            changed_file_count=1,
        )

        self.assertIn("policy requires risk:high", evaluation.errors)
        self.assertTrue(evaluation.effective_high)
        self.assertFalse(evaluation.auto_merge_allowed)

    def test_forced_high_accepts_high_without_voluntary_rationale(self) -> None:
        """An automatic-high trigger itself supplies concrete danger evidence."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-governance-change",
            head_repository="owner/game",
            repository="owner/game",
            body="Implementation milestone.\n",
            labels={"risk:high"},
            additions=100,
            deletions=10,
            changed_paths=["tools/ci/pr_policy.py"],
            changed_file_count=1,
        )

        self.assertEqual(evaluation.errors, ())
        self.assertTrue(evaluation.effective_high)

    def test_voluntary_high_requires_structured_basis(self) -> None:
        """Expected importance or difficulty cannot manufacture high risk."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-save-schema",
            head_repository="owner/game",
            repository="owner/game",
            body=(
                "Closes #12\n"
                "High-risk rationale: this is important, broad, and difficult.\n"
            ),
            labels={"risk:high", "work:review-ready"},
            additions=100,
            deletions=10,
            changed_paths=["project/scripts/save/write_save.gml"],
            changed_file_count=1,
        )

        self.assertTrue(
            any(
                "recognized High-risk basis" in error
                for error in evaluation.errors
            )
        )

    def test_voluntary_high_rejects_unrecognized_basis(self) -> None:
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-save-schema",
            head_repository="owner/game",
            repository="owner/game",
            body="High-risk basis: important-feature\n",
            labels={"risk:high"},
            additions=10,
            deletions=2,
            changed_paths=["project/scripts/save/write_save.gml"],
            changed_file_count=1,
        )

        self.assertTrue(
            any("unrecognized High-risk basis" in error for error in evaluation.errors)
        )

    def test_voluntary_high_accepts_multiple_structured_bases(self) -> None:
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-save-schema",
            head_repository="owner/game",
            repository="owner/game",
            body=(
                "High-risk basis: compatibility-migration\n"
                "High-risk basis: persistence-data-loss\n"
            ),
            labels={"risk:high"},
            additions=10,
            deletions=2,
            changed_paths=["project/scripts/save/write_save.gml"],
            changed_file_count=1,
        )

        self.assertEqual(evaluation.errors, ())

    def test_manual_merge_forces_manual_path_for_medium(self) -> None:
        """Keep manual-merge authoritative without promoting medium to high."""
        evaluation = evaluate_pull_request(
            base="dev",
            head="work/12-titan-finale",
            head_repository="owner/game",
            repository="owner/game",
            body=(
                "Closes #12\n"
                "Focused validation: `python3 -m unittest "
                "tools.tests.test_titan_finale`\n"
            ),
            labels={"risk:medium", "work:review-ready", "manual-merge"},
            additions=100,
            deletions=10,
            changed_paths=["project/scripts/titan/state.gml"],
            changed_file_count=1,
        )

        self.assertEqual(evaluation.errors, ())
        self.assertFalse(evaluation.effective_high)
        self.assertFalse(evaluation.auto_merge_allowed)


if __name__ == "__main__":
    unittest.main()
