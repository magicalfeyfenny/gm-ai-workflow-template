"""Exercise candidate storage through the actual repository-policy command."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER_FILES = ("check_repo.py", "candidate_git.py", "storage_policy.py")
LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    f"oid sha256:{'a' * 64}\n"
    "size 1024\n"
).encode()
CONTENT_POLICY = '''version = 1
[structure]
max_source_lines = 3
source_extensions = [".gml"]
forbidden_generic_stems = []
large_file_exceptions = []
[assets]
manifest = "assets/exports.json"
content_root = "content"
plain_runtime_svg = true
[assets.pipelines]
'''
STORAGE_POLICY = '''
[storage]
enabled = true
check_tracked_ignored = true
prohibited_patterns = ["artifacts/**"]
exceptions = []
[storage.lfs]
enforce_pointers = true
raw_patterns = ["*.dat"]
max_raw_bytes = 8
binary_only = true
fsck = "off"
'''


class StorageCliTests(unittest.TestCase):
    def setUp(self):
        """Keep fixture commits and stored bytes independent of developer setup."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        self.environment.update(
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_ATTR_NOSYSTEM="1", GIT_LFS_SKIP_SMUDGE="1",
        )
        self.git("init", "--quiet", "--template=")
        for key, value in {
            "user.name": "Storage CLI fixture",
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
        self.checker = self.root / "tools/ci/check_repo.py"
        self.install_checker()
        self.write("PROJECT_POLICY.toml", CONTENT_POLICY + STORAGE_POLICY)
        self.write("assets/exports.json", '{"version": 1, "exports": []}\n')

    def git(self, *arguments):
        """Run isolated Git fixture operations with checked results."""
        return subprocess.run(
            ["git", *arguments], cwd=self.root, env=self.environment,
            check=True, text=True, capture_output=True,
        ).stdout.strip()

    def write(self, name, content):
        """Persist exact bytes or UTF-8 fixture text beneath the repository."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)

    def install_checker(self):
        """Copy the complete current entrypoint and its repository-owned imports."""
        self.checker.parent.mkdir(parents=True, exist_ok=True)
        for name in CHECKER_FILES:
            shutil.copy2(ROOT / "tools/ci" / name, self.checker.parent / name)

    def commit(self):
        """Include forced tracked artifacts so ignores cannot hide fixture input."""
        self.git("add", "--all", "--force")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Fixture snapshot")
        return self.git("rev-parse", "HEAD")

    def run_checker(self, *, candidate=None, baseline=None):
        """Invoke the real CLI, leaving ref resolution and baselining untouched."""
        arguments = [sys.executable, str(self.checker)]
        if candidate is not None:
            arguments.extend(["--candidate-ref", candidate])
        if baseline is not None:
            arguments.extend(["--baseline-ref", baseline])
        return subprocess.run(
            arguments, cwd=self.root, env=self.environment,
            check=False, text=True, capture_output=True, timeout=30,
        )

    def assert_rejected(self, result, *paths):
        """Distinguish a concrete storage rejection from unavailable validation."""
        self.assertEqual(result.returncode, 1, result.stderr)
        for path in paths:
            self.assertIn(path, result.stderr)
        self.assertNotIn("repository policy passed", result.stdout)

    def assert_passed(self, result, tree):
        """A successful command must identify the stored tree it validated."""
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(tree, result.stdout)
        self.assertIn("repository policy passed", result.stdout)

    def test_default_storage_uses_staged_policy_rules_and_blobs(self):
        self.commit()
        self.write(".gitignore", "*.tmp\n")
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("asset.dat", b"\x00staged raw asset")
        self.write("staged.tmp", "forced tracked cache")
        self.write("artifacts/output.bin", "prohibited artifact")
        self.git("add", "--all", "--force")
        tree = self.git("write-tree")
        self.write("PROJECT_POLICY.toml", CONTENT_POLICY + STORAGE_POLICY.replace(
            "enabled = true", "enabled = false",
        ))
        self.write(".gitignore", "")
        self.write(".gitattributes", "*.dat -filter\n")
        self.write("asset.dat", LFS_POINTER)
        self.write("untracked.tmp", "not a candidate path")
        result = self.run_checker()
        self.assert_rejected(result, "asset.dat", "staged.tmp", "artifacts/output.bin")
        self.assertIn(tree, result.stdout)
        self.assertNotIn("untracked.tmp", result.stderr)

    def test_default_storage_accepts_stored_pointer_despite_materialized_worktree(self):
        self.write(".gitignore", "*.tmp\n")
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("asset.dat", LFS_POINTER)
        self.commit()
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.write("asset.dat", b"\x00materialized raw asset" * 100)
        self.write("untracked.tmp", "untracked cache")
        self.write("artifacts/untracked.bin", "untracked artifact")
        self.assert_passed(self.run_checker(), tree)

    def test_explicit_candidate_ignores_unrelated_head_dirty_and_untracked_content(self):
        self.write(".gitignore", "*.tmp\n")
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("asset.dat", LFS_POINTER)
        self.write("source/main.gml", "return 1;\n")
        candidate = self.commit()
        tree = self.git("rev-parse", f"{candidate}^{{tree}}")
        self.git("checkout", "--quiet", "-b", "unrelated-history")
        self.write("asset.dat", b"\x00unrelated raw asset")
        self.write("unrelated.tmp", "bad on a different branch")
        self.write("source/main.gml", b"\xffinvalid source")
        self.commit()
        self.write("PROJECT_POLICY.toml", "this is not valid TOML\n")
        self.write("assets/exports.json", "not valid JSON")
        self.write("source/untracked.gml", b"\xffnot candidate source")
        self.assert_passed(self.run_checker(candidate=candidate), tree)

    def historical_storage_baseline(self):
        """Represent an older complete repository before storage enforcement existed."""
        self.write("PROJECT_POLICY.toml", CONTENT_POLICY)
        self.write("tools/ci/check_repo.py", "def collect_errors(root):\n    return []\n")
        for name in ("candidate_git.py", "storage_policy.py"):
            (self.checker.parent / name).unlink()
        self.write(".gitignore", "*.tmp\n")
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("legacy.tmp", "inherited tracked cache")
        self.write("legacy.dat", b"\x00inherited raw asset")
        self.write("artifacts/legacy.bin", "inherited artifact")
        baseline = self.commit()
        self.install_checker()
        self.write("PROJECT_POLICY.toml", CONTENT_POLICY + STORAGE_POLICY)
        self.commit()
        return baseline

    def test_first_storage_enforcement_preserves_unchanged_historical_violations(self):
        baseline = self.historical_storage_baseline()
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assert_passed(self.run_checker(candidate="HEAD", baseline=baseline), tree)

    def test_first_storage_enforcement_rejects_changed_historical_raw_blob(self):
        baseline = self.historical_storage_baseline()
        self.write("legacy.dat", b"\x00modified raw asset!")
        self.commit()
        result = self.run_checker(candidate="HEAD", baseline=baseline)
        self.assert_rejected(result, "legacy.dat")
        self.assertNotIn("legacy.tmp", result.stderr)
        self.assertNotIn("artifacts/legacy.bin", result.stderr)

    def test_first_storage_enforcement_rejects_new_raw_blob(self):
        baseline = self.historical_storage_baseline()
        self.write("introduced.dat", b"\x00new raw asset")
        self.commit()
        self.assert_rejected(
            self.run_checker(candidate="HEAD", baseline=baseline), "introduced.dat",
        )

    def test_source_baseline_cannot_swallow_changed_storage_violation(self):
        self.write("source/large.gml", "// existing line\n" * 5)
        self.write("legacy.dat", b"\x00inherited raw asset")
        baseline = self.commit()
        self.write("source/large.gml", "// shorter source\n" * 4)
        self.commit()
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assert_passed(self.run_checker(candidate="HEAD", baseline=baseline), tree)
        self.write("legacy.dat", b"\x00changed raw blob!!")
        self.commit()
        result = self.run_checker(candidate="HEAD", baseline=baseline)
        self.assert_rejected(result, "legacy.dat")
        self.assertNotIn("source/large.gml", result.stderr)

    def test_changed_storage_helper_cannot_hide_changed_or_new_violation(self):
        self.write(".gitignore", "*.tmp\n")
        self.write("legacy.tmp", "inherited tracked cache")
        baseline = self.commit()
        helper = self.root / "tools/ci/storage_policy.py"
        helper.write_text(
            helper.read_text(encoding="utf-8")
            + "\n# Simulate a candidate checker that removes all storage rules.\n"
            + "def collect_storage_errors(root, ref=None, policy=None):\n"
            + "    return []\n"
            + "def storage_policy_errors(root, baseline_ref=None, candidate_ref=None):\n"
            + "    return []\n",
            encoding="utf-8",
        )
        self.write("legacy.tmp", "changed tracked cache")
        self.write("introduced.tmp", "new tracked cache")
        self.commit()
        self.assert_rejected(
            self.run_checker(candidate="HEAD", baseline=baseline),
            "legacy.tmp", "introduced.tmp",
        )

    def test_harmless_storage_helper_edit_preserves_inherited_storage_baseline(self):
        self.write(".gitignore", "*.tmp\n")
        self.write("legacy.tmp", "inherited tracked cache")
        baseline = self.commit()
        helper = self.root / "tools/ci/storage_policy.py"
        helper.write_text(
            helper.read_text(encoding="utf-8") + "\n# Harmless documentation edit.\n",
            encoding="utf-8",
        )
        self.commit()
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assert_passed(self.run_checker(candidate="HEAD", baseline=baseline), tree)

    def test_invalid_candidate_or_baseline_fails_without_reporting_a_pass(self):
        self.commit()
        for arguments in (
            {"candidate": "missing-candidate-ref"},
            {"candidate": "HEAD", "baseline": "missing-baseline-ref"},
        ):
            with self.subTest(arguments=arguments):
                result = self.run_checker(**arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(result.stderr)
                self.assertNotIn("repository policy passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
