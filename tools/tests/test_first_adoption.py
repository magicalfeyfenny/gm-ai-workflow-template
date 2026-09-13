"""Validate first framework adoption against real framework-free Git history."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER_FILES = (
    "check_repo.py", "candidate_git.py", "storage_policy.py",
    "adoption_basis.py", "asset_manifest.py",
)
POLICY = '''version = 1
[structure]
max_source_lines = 3
source_extensions = [".gml"]
forbidden_generic_stems = []
large_file_exceptions = []
[assets]
manifest = "assets/exports.json"
plain_runtime_svg = true
[assets.pipelines.raster]
source_roots = ["assets/source"]
runtime_roots = ["assets/runtime"]
native_resource_roots = []
source_extensions = [".kra"]
runtime_extensions = [".png"]
[storage]
enabled = true
check_tracked_ignored = true
prohibited_patterns = []
exceptions = []
[storage.lfs]
enforce_pointers = true
raw_patterns = []
max_raw_bytes = 8
binary_only = true
fsck = "off"
'''


class FirstAdoptionCliTests(unittest.TestCase):
    def setUp(self):
        """Commit the actual old project before introducing any framework file."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.root = self.temporary / "project"
        self.root.mkdir()
        self.body = self.temporary / "pull-request.md"
        self.event = self.temporary / "event.json"
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        self.environment.update(
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_ATTR_NOSYSTEM="1", GIT_LFS_SKIP_SMUDGE="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.git("init", "--quiet", "--template=")
        for key, value in {
            "user.name": "First adoption fixture",
            "user.email": "fixture@example.test",
            "commit.gpgsign": "false",
            "core.attributesFile": os.devnull,
            "core.excludesFile": os.devnull,
            "core.hooksPath": os.devnull,
            "filter.lfs.clean": "",
            "filter.lfs.smudge": "",
            "filter.lfs.process": "",
            "filter.lfs.required": "false",
        }.items():
            self.git("config", key, value)
        self.write("legacy.gml", "// inherited line\n" * 5)
        self.write(".gitignore", "*.tmp\n")
        self.write("legacy.tmp", "original blob")
        self.write("content/legacy.json", "{invalid")
        self.write("assets/runtime/legacy.png", b"inherited runtime")
        self.baseline = self.commit()
        self.original = self.baseline
        self.initial_tree = self.git("rev-parse", f"{self.baseline}^{{tree}}")

    def git(self, *arguments):
        """Run only isolated fixture Git operations with predictable settings."""
        return subprocess.run(
            ["git", *arguments], cwd=self.root, env=self.environment,
            check=True, text=True, capture_output=True,
        ).stdout.strip()

    def write(self, name, content):
        """Write test inputs without requiring any prior framework artifacts."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)

    def commit(self):
        """Keep ignored inherited artifacts in the fixture's real stored tree."""
        self.git("add", "--all", "--force")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Fixture snapshot")
        return self.git("rev-parse", "HEAD")

    def adopt(self, state="ungoverned", *, authority=None):
        """Add the incoming framework only to the adoption candidate."""
        for name in CHECKER_FILES:
            self.write(f"tools/ci/{name}", (ROOT / "tools/ci" / name).read_bytes())
        self.write("PROJECT_POLICY.toml", POLICY)
        self.write("assets/exports.json", '{"version": 1, "exports": []}\n')
        self.record(state, authority=authority)
        self.commit()

    def record(self, state, *, authority=None, baseline=None):
        """Attest the characterized lineage using the existing PR-body surface."""
        evidence = {
            "state": state,
            "baseline": baseline or self.baseline,
            "evidence": "Inspected the original commit and project history; no prior framework adoption.",
        }
        if state == "update":
            evidence["evidence"] = (
                "The preceding fixture adoption commit records the actual framework state; "
                "compare this policy update against that adopted checker and policy."
            )
        if authority is not None:
            evidence["authority_disposition"] = authority
        self.body.write_text(
            "```framework-adoption\n" + json.dumps(evidence) + "\n```\n",
            encoding="utf-8",
        )

    def run_checker(self, *, candidate="HEAD", evidence=True, event=False):
        """Exercise actual CLI ref resolution and comparison, without mocking Git."""
        arguments = [
            sys.executable, str(self.root / "tools/ci/check_repo.py"),
            "--baseline-ref", self.baseline,
        ]
        if candidate is not None:
            arguments.extend(["--candidate-ref", candidate])
        if evidence:
            arguments.extend([
                "--event-path" if event else "--pr-body-file",
                str(self.event if event else self.body),
            ])
        return subprocess.run(
            arguments, cwd=self.root, env=self.environment,
            check=False, text=True, capture_output=True, timeout=30,
        )

    def assert_passed(self, result):
        """An unavailable baseline or ignored violation is never a passing run."""
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no new or worsened violations", result.stdout)

    def assert_rejected(self, result, *subjects):
        """Separate concrete policy failures from unavailable comparison evidence."""
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for subject in subjects:
            self.assertIn(subject, result.stderr)

    def test_ungoverned_adoption_preserves_inherited_state_in_both_modes(self):
        self.adopt()
        for candidate in (None, "HEAD"):
            with self.subTest(candidate=candidate):
                self.assert_passed(self.run_checker(candidate=candidate))
        paths = set(self.git("ls-tree", "-r", "--name-only", self.baseline).splitlines())
        self.assertNotIn("PROJECT_POLICY.toml", paths)
        self.assertFalse(any(path.startswith("tools/ci/") for path in paths))
        self.assertNotIn("assets/exports.json", paths)
        self.assertEqual(self.git("rev-parse", f"{self.baseline}^{{tree}}"), self.initial_tree)

    def test_independent_authority_and_nonframework_policy_are_preserved(self):
        authority = "# Project authority\n\nOnly the owner approves dialogue changes.\n"
        self.write("GOVERNANCE.md", authority)
        self.write("PROJECT_POLICY.toml", '[dialogue]\nreviewer = "project owner"\n')
        self.baseline = self.commit()
        self.adopt(
            "independent", authority="Preserve owner approval of dialogue in current Governance; "
            "incoming framework source and storage rules have no conflict with this authority.",
        )
        self.write("PROJECT_POLICY.toml", POLICY + '[dialogue]\nreviewer = "project owner"\n')
        self.commit()
        self.assert_passed(self.run_checker())
        self.assertEqual((self.root / "GOVERNANCE.md").read_text(), authority)
        current_policy = tomllib.loads((self.root / "PROJECT_POLICY.toml").read_text())
        self.assertEqual(current_policy["dialogue"]["reviewer"], "project owner")
        self.assertIn("[dialogue]", self.git("show", f"{self.baseline}:PROJECT_POLICY.toml"))
        self.assertNotIn("tools/ci/check_repo.py", self.git(
            "ls-tree", "-r", "--name-only", self.baseline,
        ).splitlines())

    def test_absent_evidence_does_not_infer_bootstrap_from_missing_checker(self):
        self.adopt()
        self.assertEqual(self.run_checker(evidence=False).returncode, 2)

    def test_ambiguous_partial_lineage_fails_closed(self):
        self.write("PROJECT_POLICY.toml", POLICY)
        self.baseline = self.commit()
        self.adopt("ambiguous")
        result = self.run_checker()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("ambiguous", result.stderr)

    def test_stale_adoption_baseline_fails_closed(self):
        self.adopt()
        self.record("ungoverned", baseline=self.git("rev-parse", "HEAD"))
        self.assertEqual(self.run_checker().returncode, 2)

    def test_hosted_event_uses_the_same_first_adoption_evidence(self):
        self.adopt()
        self.event.write_text(json.dumps({"pull_request": {
            "body": self.body.read_text(), "base": {"sha": self.baseline},
        }}))
        self.assert_passed(self.run_checker(event=True))

    def test_source_reduction_is_allowed_and_growth_rejected(self):
        self.adopt()
        self.write("legacy.gml", "// reduced inherited line\n" * 4)
        self.commit()
        self.assert_passed(self.run_checker())
        self.write("legacy.gml", "// worsened inherited line\n" * 6)
        self.commit()
        for candidate in (None, "HEAD"):
            self.assert_rejected(self.run_checker(candidate=candidate), "legacy.gml", "6 lines")

    def test_changed_unordered_json_error_does_not_inherit(self):
        self.adopt()
        self.write("content/legacy.json", "{\ninvalid")
        self.commit()
        self.assert_rejected(self.run_checker(), "content/legacy.json")

    def test_changed_and_renamed_storage_blobs_do_not_inherit(self):
        self.adopt()
        self.write("legacy.tmp", "modified blob")
        self.commit()
        self.assert_rejected(self.run_checker(), "legacy.tmp")
        self.write("legacy.tmp", "original blob")
        self.git("mv", "legacy.tmp", "renamed.tmp")
        self.commit()
        self.assert_rejected(self.run_checker(), "renamed.tmp")

    def test_new_ignore_and_lfs_conditions_remain_new_violations(self):
        self.write("existing.dat", b"existing raw bytes")
        self.baseline = self.commit()
        self.adopt()
        self.write(".gitignore", "*.tmp\n*.dat\n")
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.commit()
        result = self.run_checker()
        self.assert_rejected(result, "existing.dat")
        self.assertIn("ignored", result.stderr)
        self.assertIn("LFS", result.stderr)

    def test_new_runtime_inventory_violation_is_not_inherited(self):
        self.adopt()
        self.write("assets/runtime/new.png", b"new runtime")
        self.commit()
        self.assert_rejected(self.run_checker(), "assets/runtime/new.png")

    def test_missing_candidate_manifest_is_not_grandfathered(self):
        self.adopt()
        self.git("rm", "assets/exports.json")
        self.commit()
        self.assert_rejected(self.run_checker(), "manifest is missing")

    def test_untracked_local_manifest_cannot_supply_candidate_coherence(self):
        self.adopt()
        self.git("rm", "--cached", "assets/exports.json")
        self.assert_rejected(self.run_checker(candidate=None), "manifest must be tracked")

    def test_existing_malformed_manifest_document_cannot_be_grandfathered(self):
        for content in ("{invalid", "[]", '{"version": 2, "exports": []}',
                        '{"version": 1, "exports": "invalid"}',
                        '{"version": 1, "exports": [null]}',
                        json.dumps({"version": 1, "exports": [{
                            "kind": "raster", "completion": "final",
                            "sources": ["assets/source/old.kra"],
                            "runtime": ["assets/runtime/legacy.png"],
                        }]})):
            with self.subTest(content=content):
                self.git("checkout", "--quiet", "--detach", self.original)
                self.write("assets/exports.json", content)
                self.baseline = self.commit()
                self.assertNotIn("tools/ci/check_repo.py", self.git(
                    "ls-tree", "-r", "--name-only", self.baseline,
                ).splitlines())
                self.adopt("independent", authority="Retain independently owned content rules.")
                self.write("assets/exports.json", content)
                self.commit()
                self.assert_rejected(self.run_checker(), "assets/exports.json")

    def test_missing_candidate_policy_cannot_bootstrap(self):
        self.adopt()
        self.git("rm", "PROJECT_POLICY.toml")
        self.commit()
        self.assertEqual(self.run_checker().returncode, 2)

    def test_known_framework_update_keeps_historical_policy_obligations(self):
        self.adopt()
        self.baseline = self.git("rev-parse", "HEAD")
        self.write("PROJECT_POLICY.toml", POLICY.replace("max_source_lines = 3", "max_source_lines = 30"))
        self.write("legacy.gml", "// worsened under the real historical policy\n" * 6)
        self.commit()
        result = self.run_checker(evidence=False)
        self.assert_rejected(result, "under baseline checker and policy", "legacy.gml")
        self.record("update")
        self.assert_rejected(self.run_checker(), "under baseline checker and policy", "legacy.gml")


if __name__ == "__main__":
    unittest.main()
