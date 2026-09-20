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
    def test_adjudicator_resolves_findings_before_handoff(self):
        prompt = _session_prompt("adjudicator", {})
        for phrase in (
            "disagree with the reviewer",
            "ordinary uncertainty",
            "multiple defensible options",
            "including reject",
            "material uncertainty remains unresolved",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)
        self.assertNotIn(
            "set human_handoff when disagreement, uncertainty",
            prompt,
        )

    def test_governed_surfaces_preserve_the_same_decision_boundary(self):
        for surface in GOVERNED_SURFACES:
            normalized = " ".join(
                surface.read_text(encoding="utf-8").casefold().split()
            )
            with self.subTest(surface=surface):
                self.assertIn("multiple valid choices do not", normalized)
                self.assertIn(
                    "material uncertainty remains unresolved after adjudication",
                    normalized,
                )


if __name__ == "__main__":
    unittest.main()
