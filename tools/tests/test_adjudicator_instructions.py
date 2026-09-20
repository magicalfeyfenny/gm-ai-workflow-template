import unittest
from pathlib import Path

from tools.ci.adversarial_review_session import _session_prompt


ROOT = Path(__file__).resolve().parents[2]
GOVERNED_SURFACES = (
    ROOT / "GOVERNANCE.md",
    ROOT / ".agents/skills/governed-change/SKILL.md",
    ROOT / "templates/codex/governed-change.txt",
)


class AdjudicatorInstructionTests(unittest.TestCase):
    def test_adjudicator_applies_governance_without_inferring_lifecycle_state(self):
        prompt = _session_prompt("adjudicator", {}).casefold()
        for phrase in (
            "apply the supplied governance and review doctrine",
            "supported disposition whenever reasonably possible",
            "do not infer lifecycle hard stops",
            "repository-owned lifecycle state machine",
            "set human_handoff only when",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)
        for lifecycle_term in ("oscillation", "correction cap", "stage 2 freshness"):
            with self.subTest(lifecycle_term=lifecycle_term):
                self.assertNotIn(lifecycle_term, prompt)

    def test_governance_owns_the_complete_decision_boundary(self):
        normalized = " ".join(
            (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8").casefold().split()
        )
        for phrase in (
            "authority-exceeding reviewer findings normally",
            "outside the current scope normally",
            "weak, contradictory, or non-supporting evidence normally",
            "structurally invalid, missing, or unusable required evidence",
            "scope or authority ambiguity",
            "lifecycle state machine enforces those hard stops mechanically",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_secondary_surfaces_reference_governance_rule(self):
        for surface in GOVERNED_SURFACES[1:]:
            normalized = " ".join(
                surface.read_text(encoding="utf-8").casefold().split()
            )
            with self.subTest(surface=surface):
                self.assertIn(
                    "complete adjudication and handoff rule in governance",
                    normalized,
                )
                self.assertIn("mechanical state-machine decisions", normalized)


if __name__ == "__main__":
    unittest.main()
