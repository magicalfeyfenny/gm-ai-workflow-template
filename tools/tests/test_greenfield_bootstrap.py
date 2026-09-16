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

    def init_git(self, branch="dev", commit=False):
        subprocess.run(
            ["git", "-C", str(self.target), "init", "--quiet", "-b", branch],
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
        if commit:
            subprocess.run(
                ["git", "-C", str(self.target), "add", "--all"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(self.target), "commit", "--quiet", "-m", "Fixture"],
                check=True,
            )

    def run_bootstrap(self, **kwargs):
        return bootstrap(
            self.target,
            source_root=ROOT,
            no_github=True,
            run_tests=False,
            **kwargs,
        )

    def candidate_visibility_source(self):
        source = Path(self.temp.name) / "template"
        shutil.copytree(
            ROOT,
            source,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", ".venv", ".pytest_cache",
            ),
        )
        shutil.rmtree(source / "tools/tests")
        tests = source / "tools/tests"
        tests.mkdir(parents=True)
        (tests / "test_candidate_visibility.py").write_text(
            "import subprocess\n"
            "import unittest\n"
            "from pathlib import Path\n\n"
            "ROOT = Path(__file__).resolve().parents[2]\n\n"
            "class CandidateVisibilityTests(unittest.TestCase):\n"
            "    def test_framework_bundle_is_in_candidate_index(self):\n"
            "        self.assertTrue((ROOT / 'AGENTS.md').is_file())\n"
            "        result = subprocess.run(\n"
            "            ['git', 'ls-files', '--error-unmatch', 'AGENTS.md'],\n"
            "            cwd=ROOT, capture_output=True, text=True,\n"
            "        )\n"
            "        self.assertEqual(result.returncode, 0, result.stderr)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        return source

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

    def test_historical_partial_framework_routes_to_adoption(self):
        self.add_project()
        self.init_git()
        shutil.copy2(ROOT / "AGENTS.md", self.target / "AGENTS.md")
        subprocess.run(
            ["git", "-C", str(self.target), "add", "AGENTS.md"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.target), "commit", "--quiet", "-m", "Framework history"],
            check=True,
        )

        report = self.run_bootstrap()

        self.assertEqual(report["classification"]["classification"], "ambiguous")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["local"]["writes"], [])
        self.assertFalse((self.target / "tools/setup_github.py").exists())

    def test_historical_non_core_framework_artifact_routes_to_adoption(self):
        self.add_project()
        self.init_git()
        relative = "templates/codex/governed-change.txt"
        target = self.target / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
        subprocess.run(
            ["git", "-C", str(self.target), "add", relative],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.target), "commit", "--quiet", "-m", "Framework history"],
            check=True,
        )

        report = self.run_bootstrap()

        self.assertEqual(report["classification"]["classification"], "ambiguous")
        self.assertIn(relative, report["classification"]["historical_framework_files"])
        self.assertEqual(report["local"]["writes"], [])

    def test_historical_complete_current_framework_remains_resumable(self):
        for relative in framework_paths(ROOT):
            source = ROOT / relative
            target = self.target / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.init_git(commit=True)

        classification = classify_target(self.target, ROOT)

        self.assertEqual(classification["classification"], "current-framework")

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

    def test_clear_authority_surfaces_block_bootstrap(self):
        for relative in (".github/CODEOWNERS", "docs/GOVERNANCE.md"):
            with self.subTest(relative=relative):
                shutil.rmtree(self.target)
                self.target.mkdir()
                authority = self.target / relative
                authority.parent.mkdir(parents=True, exist_ok=True)
                authority.write_text("# Project authority\n", encoding="utf-8")
                self.add_project()

                report = self.run_bootstrap()

                self.assertEqual(report["status"], "blocked")
                self.assertEqual(report["classification"]["classification"], "independent")
                self.assertEqual(authority.read_text(), "# Project authority\n")

    def test_ordinary_github_actions_are_not_authority_evidence(self):
        action = self.target / ".github/actions/build/action.yml"
        action.parent.mkdir(parents=True)
        action.write_text("name: Build\n", encoding="utf-8")
        self.add_project()

        classification = classify_target(self.target, ROOT)

        self.assertEqual(classification["classification"], "greenfield")

    def test_project_only_validation_observes_uncommitted_framework_candidate(self):
        self.add_project()
        source = self.candidate_visibility_source()

        report = bootstrap(
            self.target,
            source_root=source,
            no_github=True,
            run_tests=True,
        )

        self.assertEqual(
            report["local"]["validation"]["status"],
            "complete",
            report["local"]["validation"],
        )
        self.assertEqual(report["status"], "incomplete")

    def test_ignored_framework_candidate_must_be_in_head_before_github_setup(self):
        self.add_project()
        self.init_git(commit=True)
        exclude = self.target / ".git/info/exclude"
        exclude.write_text("*\n", encoding="utf-8")
        source = self.candidate_visibility_source()

        with patch("tools.greenfield_bootstrap.configure_repository") as configure:
            report = bootstrap(
                self.target,
                source_root=source,
                repo="owner/game",
                run_tests=True,
            )

        self.assertEqual(
            report["local"]["validation"]["status"],
            "complete",
            report["local"]["validation"],
        )
        self.assertTrue(report["local"]["validation"]["candidate_tree"])
        self.assertFalse(report["local"]["git"]["ready"])
        self.assertEqual(report["local"]["status"], "incomplete")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["github"]["status"], "incomplete")
        baseline = report["local"]["git"]["framework_baseline"]
        self.assertIn("AGENTS.md", baseline["missing_from_head"])
        actions = " ".join(report["manual_actions"])
        for required_action in ("review", "stage", "commit"):
            self.assertIn(required_action, actions)
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(self.target), "status", "--porcelain=v1", "--untracked-files=all"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout,
            "",
        )
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(self.target), "check-ignore", "--quiet", "AGENTS.md"],
                check=False,
            ).returncode,
            0,
        )
        head_paths = subprocess.run(
            ["git", "-C", str(self.target), "ls-tree", "-r", "--name-only", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertNotIn("AGENTS.md", head_paths)
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(self.target), "diff", "--cached", "--quiet"],
                check=False,
            ).returncode,
            0,
        )
        self.assertEqual(exclude.read_text(encoding="utf-8"), "*\n")
        configure.assert_not_called()


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

    def test_uncommitted_bootstrap_reports_incomplete_after_local_validation(self):
        self.add_project()
        with patch(
            "tools.greenfield_bootstrap._local_validation",
            return_value={"status": "complete"},
        ):
            report = bootstrap(
                self.target,
                source_root=ROOT,
                no_github=True,
                run_tests=True,
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["local"]["status"], "incomplete")
        self.assertFalse(report["local"]["git"]["has_commit"])
        self.assertFalse(report["local"]["git"]["ready"])
        self.assertTrue(any("commit" in action for action in report["manual_actions"]))

    def test_committed_dev_with_unrelated_dirty_work_remains_incomplete(self):
        self.add_project()
        self.init_git(commit=True)
        unrelated = self.target / "notes.txt"
        unrelated.write_text("user-owned work\n", encoding="utf-8")
        with patch(
            "tools.greenfield_bootstrap._local_validation",
            return_value={"status": "complete"},
        ):
            report = bootstrap(
                self.target,
                source_root=ROOT,
                no_github=True,
                run_tests=True,
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["local"]["git"]["branch"], "dev")
        self.assertIn("notes.txt", report["local"]["git"]["dirty_paths"])
        self.assertFalse(report["local"]["git"]["ready"])
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "user-owned work\n")
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(self.target), "diff", "--cached", "--quiet", "--", "notes.txt"],
                check=False,
            ).returncode,
            0,
        )

    def test_clean_committed_dev_with_bootstrap_writes_defers_github(self):
        self.add_project()
        self.init_git(commit=True)
        with patch(
            "tools.greenfield_bootstrap._local_validation",
            return_value={"status": "complete"},
        ), patch("tools.greenfield_bootstrap.configure_repository") as configure:
            report = bootstrap(
                self.target,
                source_root=ROOT,
                repo="owner/game",
                run_tests=True,
            )

        self.assertEqual(report["local"]["validation"]["status"], "complete")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["local"]["git"]["branch"], "dev")
        self.assertTrue(report["local"]["git"]["has_commit"])
        self.assertIn("AGENTS.md", report["local"]["git"]["dirty_paths"])
        self.assertFalse(report["local"]["git"]["ready"])
        self.assertEqual(report["github"]["status"], "incomplete")
        self.assertTrue((self.target / "AGENTS.md").is_file())
        configure.assert_not_called()

    def test_ordinary_non_dev_branch_installs_but_reports_incomplete(self):
        self.add_project()
        self.init_git(branch="feature/setup", commit=True)
        with patch(
            "tools.greenfield_bootstrap._local_validation",
            return_value={"status": "complete"},
        ):
            report = bootstrap(
                self.target,
                source_root=ROOT,
                no_github=True,
                run_tests=True,
            )

        self.assertEqual(report["classification"]["classification"], "greenfield")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["local"]["status"], "incomplete")
        self.assertTrue((self.target / "tools/setup_github.py").exists())
        self.assertTrue(any("dev" in action for action in report["manual_actions"]))

    def test_reserved_human_branch_is_not_modified(self):
        self.add_project()
        self.init_git(branch="human/owner", commit=False)

        report = bootstrap(
            self.target,
            source_root=ROOT,
            no_github=True,
            run_tests=False,
        )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["local"]["status"], "blocked")
        self.assertEqual(report["local"]["writes"], [])
        self.assertFalse((self.target / "AGENTS.md").exists())
        self.assertTrue(any("human/*" in action for action in report["manual_actions"]))

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
