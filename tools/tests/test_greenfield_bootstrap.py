"""Exercise greenfield bootstrap classification, preservation, and resumption."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.greenfield_bootstrap import (
    ONBOARDING_MARKER,
    bootstrap,
    classify_target,
    framework_paths,
)


ROOT = Path(__file__).resolve().parents[2]


class GreenfieldBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / "game"
        self.target.mkdir()

    def add_project(self, relative="project/game.yyp", value=None):
        path = self.target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value or {"resourceType": "GMProject", "name": "Fixture"}),
            encoding="utf-8",
        )

    def run_bootstrap(self, **kwargs):
        return bootstrap(
            self.target,
            source_root=ROOT,
            no_github=True,
            run_tests=False,
            **kwargs,
        )

    def test_project_only_path_preserves_topology_and_adds_framework(self):
        self.add_project("game/game.yyp")
        game_before = (self.target / "game/game.yyp").read_bytes()
        (self.target / "README.md").write_text(
            "# Fixture game\n\nA project-owned description.\n",
            encoding="utf-8",
        )
        report = self.run_bootstrap()

        self.assertEqual(report["classification"]["classification"], "greenfield")
        self.assertIn("AGENTS.md", report["local"]["writes"])
        self.assertEqual((self.target / "game/game.yyp").read_bytes(), game_before)
        self.assertIn(ONBOARDING_MARKER, (self.target / "README.md").read_text())
        self.assertTrue((self.target / "tools/setup_github.py").is_file())
        self.assertTrue((self.target / "game").is_dir())

    def test_generated_framework_path_is_recognized_without_a_game_project(self):
        for relative in framework_paths(ROOT):
            source = ROOT / relative
            target = self.target / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        report = self.run_bootstrap()

        self.assertEqual(report["classification"]["classification"], "current-framework")
        self.assertEqual(report["local"]["writes"], [])

    def test_rerun_is_idempotent_after_partial_framework_install(self):
        self.add_project()
        first = self.run_bootstrap()
        before = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }
        second = self.run_bootstrap()

        self.assertEqual(first["classification"]["classification"], "greenfield")
        self.assertEqual(second["classification"]["classification"], "current-framework")
        self.assertEqual(second["local"]["writes"], [])
        after = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

    def test_independent_governance_is_preserved_and_blocks_bootstrap(self):
        authority = "# Project authority\n\nThe owner approves releases.\n"
        (self.target / "GOVERNANCE.md").write_text(authority, encoding="utf-8")
        self.add_project()

        report = self.run_bootstrap()

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["classification"]["classification"], "independent")
        self.assertEqual((self.target / "GOVERNANCE.md").read_text(), authority)
        self.assertFalse((self.target / "tools/setup_github.py").exists())
        self.assertTrue(report["manual_actions"])

    def test_partial_framework_conflict_is_ambiguous_not_overwritten(self):
        self.add_project()
        conflicting = self.target / "tools/setup_github.py"
        conflicting.parent.mkdir(parents=True)
        conflicting.write_text("# unrelated setup\n", encoding="utf-8")

        report = self.run_bootstrap()

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["classification"]["classification"], "ambiguous")
        self.assertEqual(conflicting.read_text(), "# unrelated setup\n")
        self.assertFalse((self.target / "AGENTS.md").exists())

    def test_invalid_game_project_is_ambiguous(self):
        self.add_project(value={"resourceType": "not-a-project"})

        classification = classify_target(self.target, ROOT)

        self.assertEqual(classification["classification"], "ambiguous")
        self.assertEqual(classification["invalid_projects"], ["project/game.yyp"])

    def test_deleted_framework_history_is_prior_lineage_evidence(self):
        self.add_project()
        subprocess.run(
            ["git", "-C", str(self.target), "init", "--quiet", "-b", "dev"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.target), "config", "user.email", "fixture@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.target), "config", "user.name", "Fixture"],
            check=True,
        )
        shutil.copy2(ROOT / "AGENTS.md", self.target / "AGENTS.md")
        subprocess.run(
            ["git", "-C", str(self.target), "add", "AGENTS.md"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.target), "commit", "--quiet", "-m", "Framework history"],
            check=True,
        )
        (self.target / "AGENTS.md").unlink()

        classification = classify_target(self.target, ROOT)

        self.assertEqual(classification["classification"], "ambiguous")
        self.assertEqual(classification["historical_framework_files"], ["AGENTS.md"])

    def test_missing_github_identity_reports_incomplete_after_local_setup(self):
        self.add_project()
        with patch(
            "tools.greenfield_bootstrap._local_validation",
            return_value={"status": "complete"},
        ):
            report = bootstrap(
                self.target,
                source_root=ROOT,
                run_tests=True,
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["github"]["status"], "incomplete")
        self.assertTrue(any("GitHub" in action for action in report["manual_actions"]))

    def test_dry_run_does_not_initialize_or_write(self):
        self.add_project()
        before = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }

        report = bootstrap(
            self.target,
            source_root=ROOT,
            no_github=True,
            dry_run=True,
        )

        self.assertEqual(report["status"], "dry-run")
        self.assertFalse((self.target / ".git").exists())
        after = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
