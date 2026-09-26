import unittest
from pathlib import Path

from tools.ci.adversarial_review_session import _session_prompt


ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_ROUTE = "governance.md#adversarial-review-and-adjudication"
GOVERNED_SURFACES = (
    ROOT / ".agents/skills/governed-change/SKILL.md",
    ROOT / ".github/pull_request_template.md",
    ROOT / "templates/codex/governed-change.txt",
)


class AdjudicatorInstructionTests(unittest.TestCase):
    def test_review_roles_name_existing_authority_and_evidence(self):
        reviewer = _session_prompt("reviewer", {}).casefold()
        adjudicator = _session_prompt("adjudicator", {}).casefold()

        self.assertIn("existing issue requirement or governance rule", reviewer)
        self.assertIn("contract_or_governance", reviewer)
        self.assertIn("stable evidence ids", reviewer)
        self.assertIn(
            "named accepted issue requirement or standing governance rule",
            adjudicator,
        )
        self.assertIn("put that authority in basis", adjudicator)
        self.assertIn("repository-owned state machine", adjudicator)
        self.assertIn("do not prescribe the implementation remedy", adjudicator)
        self.assertIn("blocker or patch-now means the current candidate requires correction", adjudicator)

    def test_secondary_surfaces_route_review_policy_to_governance(self):
        governance = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8").casefold()
        self.assertIn("## adversarial review and adjudication", governance)
        for surface in GOVERNED_SURFACES:
            text = surface.read_text(encoding="utf-8").casefold()
            with self.subTest(surface=surface):
                self.assertIn(GOVERNANCE_ROUTE, text)

    def test_governance_owns_persisted_outcome_reporting(self):
        governance = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8").casefold()
        reporting = governance.split("### persisted outcome reporting", 1)[1].split(
            "## milestone commits and draft publication", 1
        )[0]
        for marker in (
            "review_cycles",
            "not-needed",
            "zero-finding review",
            "prior-cycle follow-ups",
            "adjudication_status",
            "unadjudicated observations",
            "session failure",
            "current cycle",
        ):
            with self.subTest(authoritative_rule=marker):
                self.assertIn(marker, reporting)

        reporting_route = "governance.md#persisted-outcome-reporting"
        duplicated_details = (
            "review_cycles",
            "not-needed",
            "unadjudicated observations",
            "prior-cycle follow-ups",
            "only current-cycle",
        )
        for surface in GOVERNED_SURFACES:
            text = surface.read_text(encoding="utf-8").casefold()
            with self.subTest(surface=surface):
                self.assertIn(reporting_route, text)
                for marker in duplicated_details:
                    with self.subTest(duplicate=marker):
                        self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
