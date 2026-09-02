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


if __name__ == "__main__":
    unittest.main()
