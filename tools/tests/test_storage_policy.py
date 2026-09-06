"""Candidate storage contracts verified against isolated Git repositories."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.ci.storage_policy import collect_storage_errors, storage_policy_errors


LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    f"oid sha256:{'a' * 64}\n"
    "size 1024\n"
).encode()


class StorageFixture(unittest.TestCase):
    def setUp(self):
        """Disable developer filters so fixture bytes are the stored Git bytes."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        for key, value in {
            "user.name": "Storage fixture",
            "user.email": "fixture@example.test",
            "commit.gpgsign": "false",
            "core.attributesFile": "/dev/null",
            "core.excludesFile": "/dev/null",
            "filter.lfs.clean": "",
            "filter.lfs.smudge": "",
            "filter.lfs.process": "",
            "filter.lfs.required": "false",
        }.items():
            self.git("config", key, value)
        self.policy = {
            "storage": {
                "enabled": True,
                "check_tracked_ignored": True,
                "prohibited_patterns": [],
                "exceptions": [],
                "lfs": {
                    "enforce_pointers": True,
                    "raw_patterns": [],
                    "max_raw_bytes": 10485760,
                    "binary_only": True,
                    "fsck": "required",
                },
            },
        }
        self.write_policy()

    def git(self, *arguments):
        """Run checked Git operations without relying on a fixture branch name."""
        return subprocess.run(
            ["git", *arguments], cwd=self.root, check=True,
            text=True, capture_output=True,
        ).stdout.strip()

    def write(self, name, content):
        """Write text or exact binary content beneath the fixture root."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)

    def write_policy(self):
        """Persist the small candidate policy without a TOML writer dependency."""
        if "storage" not in self.policy:
            self.write("PROJECT_POLICY.toml", "version = 1\n")
            return
        storage = self.policy["storage"]
        lines = ["version = 1", "[storage]"]
        lines.extend(
            f"{key} = {json.dumps(value)}"
            for key, value in storage.items() if key != "lfs"
        )
        lines.append("[storage.lfs]")
        lines.extend(
            f"{key} = {json.dumps(value)}" for key, value in storage["lfs"].items()
        )
        self.write("PROJECT_POLICY.toml", "\n".join(lines) + "\n")

    def commit(self):
        """Force-stage artifacts to reproduce the tracked-ignore failure mode."""
        self.git("add", "--force", "--all")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Fixture snapshot")
        return self.git("rev-parse", "HEAD")

    def collect(self, ref="HEAD", policy=None):
        """Collect only the identified stored candidate's storage diagnostics."""
        return collect_storage_errors(self.root, ref=ref, policy=policy)

    def assert_rejected(self, errors, *paths):
        """Check concrete rejected paths without freezing diagnostic prose."""
        self.assertTrue(errors, "Invalid stored candidate was accepted")
        for path in paths:
            self.assertTrue(any(path in error for error in errors), (path, errors))

    def raw_limit(self, *, patterns=None, limit=8, binary_only=True):
        """Select only fixture classes explicitly subject to the raw blob cap."""
        self.policy["storage"]["lfs"].update(
            raw_patterns=patterns or ["*.dat"],
            max_raw_bytes=limit,
            binary_only=binary_only,
        )
        self.write_policy()


class CandidateHygieneTests(StorageFixture):
    def test_forced_tracked_ignored_file_is_rejected(self):
        self.write(".gitignore", "cache/\n")
        self.write("cache/session.bin", b"cache")
        self.commit()
        self.assert_rejected(self.collect(), "cache/session.bin")

    def test_nested_ignore_rules_and_negations_use_git_semantics(self):
        self.write(".gitignore", "*.tmp\n!root.tmp\n")
        self.write("nested/.gitignore", "!kept.tmp\nblocked.dat\n")
        for path in ("root.tmp", "nested/kept.tmp", "nested/lost.tmp", "nested/blocked.dat"):
            self.write(path, "fixture")
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "nested/lost.tmp", "nested/blocked.dat")
        self.assertFalse(any("root.tmp" in error or "kept.tmp" in error for error in errors))

    def test_untracked_ignored_files_do_not_enter_candidate(self):
        self.write(".gitignore", "cache/\n")
        self.commit()
        self.write("cache/session.bin", "local only")
        self.assertEqual(self.collect(), [])

    def test_candidate_ignore_blob_overrides_unstaged_and_local_excludes(self):
        self.write(".gitignore", "tracked.tmp\n")
        self.write("tracked.tmp", "candidate ignored")
        self.write("kept.dat", "candidate allowed")
        candidate = self.commit()
        self.write(".gitignore", "kept.dat\n")
        self.write(".git/info/exclude", "kept.dat\n")
        errors = self.collect(candidate)
        self.assert_rejected(errors, "tracked.tmp")
        self.assertFalse(any("kept.dat" in error for error in errors))

    def test_configured_artifacts_use_patterns_and_negations(self):
        self.policy["storage"]["prohibited_patterns"] = [
            "**/.DS_Store", "build/*", "!build/retained.txt",
        ]
        self.write_policy()
        for path in ("nested/.DS_Store", "build/output.bin", "build/retained.txt", "cache/allowed"):
            self.write(path, "fixture")
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "nested/.DS_Store", "build/output.bin")
        self.assertFalse(any("retained.txt" in error or "cache/allowed" in error for error in errors))

    def test_exact_exception_exempts_only_declared_path(self):
        self.policy["storage"]["prohibited_patterns"] = ["build/**"]
        self.policy["storage"]["exceptions"] = ["build/keep", "build/tree"]
        self.write_policy()
        for path in ("build/keep", "build/keep-other", "build/tree/child"):
            self.write(path, "fixture")
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "build/keep-other", "build/tree/child")
        self.assertFalse(any("build/keep:" in error for error in errors))

    def test_exact_exception_applies_to_ignored_target_without_exempting_sibling(self):
        self.policy["storage"]["exceptions"] = ["cache/keep.bin"]
        self.write_policy()
        self.write(".gitignore", "cache/\n")
        self.write("cache/keep.bin", "accepted")
        self.write("cache/other.bin", "rejected")
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "cache/other.bin")
        self.assertFalse(any("cache/keep.bin" in error for error in errors))

    def test_unrelated_branch_does_not_enter_candidate(self):
        self.write(".gitignore", "*.tmp\n")
        candidate = self.commit()
        self.git("checkout", "-q", "-b", "unrelated-history")
        self.write("unrelated.tmp", "bad on another branch")
        self.commit()
        self.assertEqual(self.collect(candidate), [])

    def test_default_index_uses_staged_paths_rules_policy_and_blobs(self):
        baseline = self.commit()
        self.policy["storage"]["prohibited_patterns"] = ["artifacts/**"]
        self.write_policy()
        self.write(".gitignore", "*.tmp\n")
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("staged.tmp", "ignored in the index")
        self.write("artifacts/output.bin", "prohibited in the index")
        self.write("asset.dat", b"\x00raw in the index")
        self.git("add", "--force", "--all")
        self.policy["storage"]["enabled"] = False
        self.write_policy()
        self.write(".gitignore", "")
        self.write(".gitattributes", "*.dat -filter\n")
        self.write("asset.dat", LFS_POINTER)
        self.write("untracked.tmp", "absent from the index")
        errors = collect_storage_errors(self.root)
        self.assert_rejected(errors, "staged.tmp", "artifacts/output.bin", "asset.dat")
        self.assertFalse(any("untracked.tmp" in error for error in errors))
        self.assertEqual(self.collect(baseline), [])
        self.assertEqual(storage_policy_errors(self.root), errors)
        introduced = storage_policy_errors(self.root, baseline_ref=baseline)
        self.assert_rejected(introduced, "staged.tmp", "artifacts/output.bin", "asset.dat")
        self.assertFalse(any("untracked.tmp" in error for error in introduced))

    def test_disabling_tracked_ignore_check_preserves_artifact_checks(self):
        self.policy["storage"]["check_tracked_ignored"] = False
        self.policy["storage"]["prohibited_patterns"] = ["artifacts/**"]
        self.write_policy()
        self.write(".gitignore", "*.tmp\n")
        self.write("allowed.tmp", "configured ignore exemption")
        self.write("artifacts/output.bin", "still prohibited")
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "artifacts/output.bin")
        self.assertFalse(any("allowed.tmp" in error for error in errors))


class CandidateLfsTests(StorageFixture):
    def test_valid_stored_pointer_passes_without_local_asset_object(self):
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("asset.dat", LFS_POINTER)
        self.commit()
        self.assertEqual(self.collect(), [])

    def test_lfs_raw_and_malformed_blobs_are_rejected(self):
        self.write(".gitattributes", "*.dat filter=lfs\n")
        malformed = {
            "raw.dat": b"\x00raw asset",
            "bad-oid.dat": LFS_POINTER.replace(b"a" * 64, b"a" * 63),
            "bad-size.dat": LFS_POINTER.replace(b"size 1024", b"size -1"),
            "truncated.dat": LFS_POINTER.split(b"size")[0],
            "trailing.dat": LFS_POINTER + b"unexpected content\n",
            "empty.dat": b"",
        }
        for path, content in malformed.items():
            self.write(path, content)
        self.commit()
        self.assert_rejected(self.collect(), *malformed)

    def test_attribute_overrides_and_nested_packages_use_effective_attributes(self):
        self.write(".gitattributes", "*.dat filter=lfs\n*.wav filter=lfs\n")
        self.write("nested/.gitattributes", "raw.dat -filter\n")
        self.write("nested/raw.dat", b"\x00raw allowed")
        self.write("nested/pointer.dat", LFS_POINTER)
        self.write("song.logicx/Media/Audio/take.wav", b"\x00raw package audio")
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "song.logicx/Media/Audio/take.wav")
        self.assertFalse(any("nested/raw.dat" in error for error in errors))

    def test_local_attributes_and_unstaged_edits_do_not_change_candidate(self):
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("asset.dat", b"\x00raw candidate")
        candidate = self.commit()
        self.write(".gitattributes", "*.dat -filter\n")
        self.write(".git/info/attributes", "*.dat -filter\n")
        self.write("asset.dat", LFS_POINTER)
        self.assert_rejected(self.collect(candidate), "asset.dat")

    def test_pointer_only_and_smudged_worktrees_have_identical_verdicts(self):
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("asset.dat", LFS_POINTER)
        candidate = self.commit()
        pointer_errors = self.collect(candidate)
        self.write("asset.dat", b"\x00materialized asset" * 100)
        self.assertEqual(self.collect(candidate), pointer_errors)
        self.assertEqual(pointer_errors, [])

    def test_raw_size_boundary_is_inclusive_and_only_configured_classes_apply(self):
        self.raw_limit()
        self.write("boundary.dat", b"\x00" * 8)
        self.write("large.dat", b"\x00" * 9)
        self.write("unconfigured.png", b"\x00" * 100)
        self.write("text.dat", b"x" * 100)
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "large.dat")
        for path in ("boundary.dat", "unconfigured.png", "text.dat"):
            self.assertFalse(any(path in error for error in errors))

    def test_binary_only_can_be_disabled_for_configured_text_class(self):
        self.raw_limit(binary_only=False)
        self.write("large.dat", b"x" * 9)
        self.commit()
        self.assert_rejected(self.collect(), "large.dat")

    def test_binary_detection_uses_initial_eight_thousand_bytes(self):
        self.raw_limit(limit=8000)
        self.write("early.dat", b"x" * 7999 + b"\x00xx")
        self.write("late.dat", b"x" * 8000 + b"\x00xx")
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "early.dat")
        self.assertFalse(any("late.dat" in error for error in errors))

    def test_raw_patterns_support_negation_and_pointers_are_not_raw_assets(self):
        self.raw_limit(patterns=["*.dat", "!allowed.dat"], binary_only=False)
        self.write("blocked.dat", b"x" * 9)
        self.write("allowed.dat", b"x" * 9)
        self.write("pointer.dat", LFS_POINTER)
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "blocked.dat")
        self.assertFalse(any("allowed.dat" in error or "pointer.dat" in error for error in errors))

    def test_exact_exceptions_cover_pointer_and_raw_size_without_exempting_siblings(self):
        self.raw_limit()
        self.policy["storage"]["exceptions"] = ["allowed.dat"]
        self.write_policy()
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("allowed.dat", b"\x00" * 9)
        self.write("allowed-other.dat", b"\x00" * 9)
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "allowed-other.dat")
        self.assertFalse(any("allowed.dat" in error for error in errors))

    def test_disabling_pointer_enforcement_preserves_configured_raw_size_cap(self):
        self.raw_limit()
        self.policy["storage"]["lfs"]["enforce_pointers"] = False
        self.write_policy()
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("small.dat", b"\x00" * 8)
        self.write("large.dat", b"\x00" * 9)
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "large.dat")
        self.assertFalse(any("small.dat" in error for error in errors))

    def test_attributed_symlink_cannot_substitute_for_a_stored_pointer(self):
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.write("target.dat", LFS_POINTER)
        (self.root / "link.dat").symlink_to("target.dat")
        self.commit()
        errors = self.collect()
        self.assert_rejected(errors, "link.dat")
        self.assertFalse(any("target.dat" in error for error in errors))


class StorageBaselineTests(StorageFixture):
    def baseline_errors(self, baseline, candidate="HEAD"):
        """Apply inherited-state treatment to two explicit Git snapshots."""
        return storage_policy_errors(
            self.root, baseline_ref=baseline, candidate_ref=candidate,
        )

    def ignored_baseline(self):
        """Commit one inherited violation shared by hygiene baseline cases."""
        self.write(".gitignore", "*.tmp\n")
        self.write("legacy.tmp", "inherited")
        return self.commit()

    def test_unchanged_inherited_artifact_has_no_new_obligation(self):
        baseline = self.ignored_baseline()
        self.write("unrelated.txt", "unrelated change")
        self.commit()
        self.assert_rejected(self.collect(), "legacy.tmp")
        self.assertEqual(self.baseline_errors(baseline), [])

    def test_edited_artifact_is_new_even_with_same_length(self):
        baseline = self.ignored_baseline()
        self.write("legacy.tmp", "different")
        self.commit()
        self.assert_rejected(self.baseline_errors(baseline), "legacy.tmp")

    def test_new_and_renamed_artifacts_do_not_inherit_another_path(self):
        baseline = self.ignored_baseline()
        self.git("mv", "legacy.tmp", "renamed.tmp")
        self.write("introduced.tmp", "inherited")
        self.commit()
        self.assert_rejected(self.baseline_errors(baseline), "renamed.tmp", "introduced.tmp")

    def test_mode_change_does_not_inherit_an_existing_blob_violation(self):
        baseline = self.ignored_baseline()
        self.git("update-index", "--chmod=+x", "legacy.tmp")
        self.git("commit", "--quiet", "-m", "Changed stored file mode")
        self.assert_rejected(self.baseline_errors(baseline), "legacy.tmp")

    def test_shrinking_raw_blob_still_changes_the_storage_condition(self):
        self.raw_limit()
        self.write("legacy.dat", b"\x00" * 20)
        baseline = self.commit()
        self.write("legacy.dat", b"\x00" * 10)
        self.commit()
        self.assert_rejected(self.baseline_errors(baseline), "legacy.dat")

    def test_changed_blob_under_boundary_resolves_raw_violation(self):
        self.raw_limit()
        self.write("legacy.dat", b"\x00" * 20)
        baseline = self.commit()
        self.write("legacy.dat", b"\x00" * 8)
        self.commit()
        self.assertEqual(self.baseline_errors(baseline), [])

    def test_new_candidate_ignore_rule_is_a_new_condition(self):
        self.write("legacy.tmp", "original")
        baseline = self.commit()
        self.write(".gitignore", "*.tmp\n")
        self.commit()
        self.assert_rejected(self.baseline_errors(baseline), "legacy.tmp")

    def test_new_effective_lfs_attribute_is_a_new_condition(self):
        self.write("legacy.dat", b"\x00raw asset")
        baseline = self.commit()
        self.write(".gitattributes", "*.dat filter=lfs\n")
        self.commit()
        self.assert_rejected(self.baseline_errors(baseline), "legacy.dat")

    def test_enabling_storage_grandfathers_existing_blobs_without_old_policy(self):
        enabled = copy.deepcopy(self.policy)
        self.policy = {}
        self.write_policy()
        baseline = self.ignored_baseline()
        self.policy = enabled
        self.write_policy()
        self.commit()
        self.assert_rejected(self.collect(), "legacy.tmp")
        self.assertEqual(self.baseline_errors(baseline), [])

    def test_enabling_storage_does_not_grandfather_changed_blob(self):
        enabled = copy.deepcopy(self.policy)
        self.policy = {}
        self.write_policy()
        baseline = self.ignored_baseline()
        self.policy = enabled
        self.write_policy()
        self.write("legacy.tmp", "changed")
        self.commit()
        self.assert_rejected(self.baseline_errors(baseline), "legacy.tmp")

    def test_loosened_policy_does_not_hide_new_old_policy_violation(self):
        self.raw_limit()
        self.write("legacy.dat", b"\x00" * 9)
        baseline = self.commit()
        self.raw_limit(limit=20)
        self.write("legacy.dat", b"\x00" * 10)
        self.commit()
        self.assertEqual(self.collect(), [])
        self.assert_rejected(self.baseline_errors(baseline), "legacy.dat")

    def test_disabling_policy_does_not_hide_changed_ignored_blob(self):
        baseline = self.ignored_baseline()
        self.policy["storage"]["enabled"] = False
        self.write_policy()
        self.write("legacy.tmp", "changed")
        self.commit()
        self.assertEqual(self.collect(), [])
        self.assert_rejected(self.baseline_errors(baseline), "legacy.tmp")

    def test_policy_only_change_does_not_require_cleanup_of_unchanged_blob(self):
        baseline = self.ignored_baseline()
        self.policy["storage"]["prohibited_patterns"] = ["*.tmp"]
        self.write_policy()
        self.commit()
        self.assertEqual(self.baseline_errors(baseline), [])

    def test_adding_exception_does_not_hide_changed_old_policy_violation(self):
        baseline = self.ignored_baseline()
        self.policy["storage"]["exceptions"] = ["legacy.tmp"]
        self.write_policy()
        self.write("legacy.tmp", "changed")
        self.commit()
        self.assertEqual(self.collect(), [])
        self.assert_rejected(self.baseline_errors(baseline), "legacy.tmp")


class StorageSchemaTests(StorageFixture):
    def test_absent_or_disabled_storage_is_opt_in(self):
        self.write(".gitignore", "*.tmp\n")
        self.write("legacy.tmp", "ignored")
        self.commit()
        for policy in ({}, {"storage": {"enabled": False}}):
            with self.subTest(policy=policy):
                self.assertEqual(self.collect(policy=policy), [])

    def test_malformed_fields_and_unknown_keys_fail_closed(self):
        self.commit()
        invalid = [
            {"storage": []},
            {"storage": {"enabled": "true"}},
            {"storage": {"enabled": True, "unknown": False}},
            {"storage": {"enabled": True, "check_tracked_ignored": 1}},
            {"storage": {"enabled": True, "prohibited_patterns": "*.tmp"}},
            {"storage": {"enabled": True, "prohibited_patterns": [1]}},
            {"storage": {"enabled": True, "exceptions": "cache/keep"}},
            {"storage": {"enabled": True, "lfs": []}},
        ]
        for field, value in (
            ("unknown", True), ("enforce_pointers", 1), ("raw_patterns", "*.dat"),
            ("raw_patterns", [False]), ("max_raw_bytes", -1),
            ("max_raw_bytes", True), ("max_raw_bytes", 1.5),
            ("binary_only", "yes"), ("fsck", "perhaps"),
        ):
            policy = copy.deepcopy(self.policy)
            policy["storage"]["lfs"][field] = value
            invalid.append(policy)
        for policy in invalid:
            with self.subTest(policy=policy):
                with self.assertRaises(ValueError):
                    self.collect(policy=policy)

    def test_exceptions_reject_globs_absolute_parent_and_directory_paths(self):
        self.commit()
        for path in ("*.tmp", "cache/[ab]", "/absolute", "../outside", "cache/../item", "cache/"):
            policy = copy.deepcopy(self.policy)
            policy["storage"]["exceptions"] = [path]
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.collect(policy=policy)


if __name__ == "__main__":
    unittest.main()
