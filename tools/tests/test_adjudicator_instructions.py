import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE_ROUTE = "governance.md#adversarial-review-and-adjudication"
GOVERNED_SURFACES = (
    ROOT / ".agents/skills/governed-change/SKILL.md",
    ROOT / ".github/pull_request_template.md",
    ROOT / "templates/codex/governed-change.txt",
)


class AdjudicatorInstructionTests(unittest.TestCase):
    def test_secondary_surfaces_route_review_policy_to_governance(self):
        for surface in GOVERNED_SURFACES:
            text = surface.read_text(encoding="utf-8").casefold()
            with self.subTest(surface=surface):
                self.assertIn(GOVERNANCE_ROUTE, text)

if __name__ == "__main__":
    unittest.main()
