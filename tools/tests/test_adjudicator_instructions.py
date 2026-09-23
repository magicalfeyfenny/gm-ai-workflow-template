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

    def test_secondary_surfaces_route_review_policy_to_governance(self):
        governance = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8").casefold()
        self.assertIn("## adversarial review and adjudication", governance)
        for surface in GOVERNED_SURFACES:
            text = surface.read_text(encoding="utf-8").casefold()
            with self.subTest(surface=surface):
                self.assertIn(GOVERNANCE_ROUTE, text)


if __name__ == "__main__":
    unittest.main()
