"""Existing release verification against temporary, preserved Git histories."""

import hashlib
import os
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tools.adoption_release import verify_release


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Adoption test")
        self.git("config", "user.email", "adoption@example.invalid")
        (self.root / "source.txt").write_text("published source\n")
        self.git("add", "source.txt")
        self.git("commit", "-m", "Published source")
        self.release_commit = self.git("rev-parse", "HEAD")
        self.git("tag", "v1")
        self.release = self.release_record("v1")

    def git(self, *arguments):
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            text=True, capture_output=True, check=True,
        )
        return result.stdout.strip()

    def release_record(self, tag, published_at="2026-09-01T00:00:00Z", **fields):
        sha = self.git("rev-parse", f"refs/tags/{tag}")
        return {
            "id": tag,
            "tag_name": tag,
            "draft": False,
            "prerelease": False,
            "published_at": published_at,
            "target_commitish": "main",
            "tag_ref": {
                "ref": f"refs/tags/{tag}",
                "object": {"sha": sha, "type": self.git("cat-file", "-t", sha)},
            },
            "assets": [],
        } | fields

    def verify(self, **kwargs):
        return verify_release(
            self.root, kwargs.pop("releases", [self.release]),
            kwargs.pop("tag", "v1"), kwargs.pop("candidate_ref", "refs/heads/main"),
            **kwargs,
        )

    def test_lightweight_and_annotated_tags_record_separate_object_and_commit(self):
        lightweight = self.verify()
        self.assertEqual(lightweight["status"], "pass")
        self.assertEqual(lightweight["anchor"]["kind"], "commit")
        self.git("tag", "-a", "v2", "-m", "Annotated release")
        annotated = self.verify(releases=[self.release_record("v2")], tag="v2")
        self.assertEqual(annotated["status"], "pass")
        self.assertEqual(annotated["anchor"]["kind"], "tag")
        self.assertNotEqual(annotated["anchor"]["local_object"], self.release_commit)
        self.assertEqual(annotated["anchor"]["commit"], self.release_commit)

    def test_distinct_commits_with_same_tree_pass_without_ancestry_contract(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        unrelated = self.git("commit-tree", tree, "-m", "Independent source lineage")
        result = self.verify(candidate_ref=unrelated)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["tree_equivalence"]["equivalent"])
        self.assertNotEqual(result["provenance"]["release_commit"], result["provenance"]["candidate_commit"])
        self.assertEqual(result["provenance"]["candidate_commit"], unrelated)

    def test_different_trees_fail(self):
        (self.root / "source.txt").write_text("changed source\n")
        self.git("commit", "-am", "Changed source")
        result = self.verify()
        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["tree_equivalence"]["equivalent"])

    def test_replace_refs_cannot_disguise_a_different_source_tree(self):
        (self.root / "source.txt").write_text("changed source\n")
        self.git("commit", "-am", "Changed source")
        changed = self.git("rev-parse", "HEAD")
        self.git("replace", changed, self.release_commit)
        result = self.verify()
        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["tree_equivalence"]["equivalent"])
        self.assertEqual(result["provenance"]["candidate_commit"], changed)

    def test_latest_selection_uses_published_time_and_ignores_drafts_and_prereleases(self):
        releases = [self.release]
        for tag, fields in (
            ("new", {}), ("draft", {"draft": True}), ("preview", {"prerelease": True}),
        ):
            self.git("tag", tag)
            releases.append(self.release_record(tag, "2026-09-02T00:00:00Z", **fields))
        result = self.verify(releases=releases, tag=None)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["release"]["tag_name"], "new")
        preview = self.verify(releases=releases, tag="preview")
        self.assertEqual(preview["status"], "pass")
        self.assertEqual(self.verify(releases=releases, tag="draft")["status"], "unavailable")

    def test_equal_latest_timestamps_and_duplicate_exact_tags_are_ambiguous(self):
        self.git("tag", "v2")
        tied = [self.release, self.release_record("v2")]
        self.assertEqual(self.verify(releases=tied, tag=None)["status"], "ambiguous")
        self.assertEqual(self.verify(releases=[self.release, deepcopy(self.release)])["status"], "ambiguous")

    def test_missing_publication_or_release_cannot_pass(self):
        for published_at in (None, "", "bad timestamp", "2026-09-01T00:00:00"):
            with self.subTest(published_at=published_at):
                record = self.release | {"published_at": published_at}
                self.assertEqual(self.verify(releases=[record])["status"], "unavailable")
        self.assertEqual(self.verify(releases=[])["status"], "unavailable")
        self.assertEqual(self.verify(tag="missing")["status"], "unavailable")

    def test_missing_local_or_remote_tags_cannot_pass(self):
        missing_remote = self.release | {"tag_ref": {"unavailable": "not found"}}
        self.assertEqual(self.verify(releases=[missing_remote])["status"], "unavailable")
        self.git("tag", "-d", "v1")
        result = self.verify()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["tree_equivalence"]["equivalent"])

    def test_stale_local_tag_and_wrong_remote_reference_fail(self):
        wrong = deepcopy(self.release)
        wrong["tag_ref"]["ref"] = "refs/tags/v10"
        self.assertEqual(self.verify(releases=[wrong])["status"], "fail")
        self.git("commit", "--allow-empty", "-m", "Another commit")
        self.git("tag", "-f", "v1")
        result = self.verify()
        self.assertEqual(result["status"], "fail")
        self.assertNotEqual(result["anchor"]["local_object"], self.release_commit)

    def test_missing_and_ambiguous_candidates_do_not_pass(self):
        self.assertEqual(self.verify(candidate_ref="missing")["status"], "unavailable")
        self.git("tag", "main")
        self.assertEqual(self.verify(candidate_ref="main")["status"], "ambiguous")
        self.assertEqual(self.verify(candidate_ref="refs/heads/main")["status"], "pass")

    def test_git_environment_cannot_redirect_verification_to_another_repository(self):
        with tempfile.TemporaryDirectory() as other_directory:
            subprocess.run(
                ["git", "init", "--bare", other_directory],
                capture_output=True, check=True,
            )
            overrides = {
                "GIT_DIR": other_directory,
                "GIT_COMMON_DIR": other_directory,
                "GIT_WORK_TREE": other_directory,
                "GIT_INDEX_FILE": str(Path(other_directory) / "index"),
                "GIT_OBJECT_DIRECTORY": str(Path(other_directory) / "objects"),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": other_directory,
                "GIT_NAMESPACE": "other-repository",
            }
            with patch.dict(os.environ, overrides):
                result = self.verify()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["candidate"]["commit"], self.release_commit)
        self.assertEqual(result["anchor"]["commit"], self.release_commit)

    def test_git_timeout_is_unavailable_evidence(self):
        with patch(
            "tools.adoption_release.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                ["git", "-c", "core.warnAmbiguousRefs=true"], 30,
            ),
        ):
            result = self.verify()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["candidate"]["status"], "unavailable")
        self.assertEqual(result["anchor"]["status"], "unavailable")

    def artifact(self, *, digest=True):
        content = b"release artifact\n"
        path = self.root / "build.zip"
        path.write_bytes(content)
        sha = hashlib.sha256(content).hexdigest()
        self.release["assets"] = [{"name": "build.zip", "digest": f"sha256:{sha}" if digest else None}]
        return {"name": "build.zip", "path": "build.zip"}, sha

    def test_published_and_explicit_matching_artifact_digests_pass(self):
        spec, sha = self.artifact()
        for contract in (spec, spec | {"sha256": sha}):
            with self.subTest(contract=contract):
                result = self.verify(artifacts=[contract])
                self.assertEqual(result["status"], "pass")
                self.assertEqual(result["artifacts"][0]["local_sha256"], sha)
                self.assertEqual(result["artifacts"][0]["status"], "pass")
        self.release["assets"][0]["digest"] = None
        self.assertEqual(self.verify(artifacts=[spec | {"sha256": sha}])["status"], "pass")

    def test_optional_metadata_is_recorded_without_claiming_local_verification(self):
        _, sha = self.artifact()
        result = self.verify()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["published_artifacts"][0]["digest"], f"sha256:{sha}")
        self.assertEqual(result["artifacts"], [])

    def test_historical_file_with_explicit_digest_passes_without_published_asset(self):
        spec, sha = self.artifact()
        self.release["assets"] = []
        result = self.verify(artifacts=[spec | {"sha256": sha}])
        self.assertEqual(result["status"], "pass")
        artifact = result["artifacts"][0]
        self.assertEqual(artifact["status"], "pass")
        self.assertEqual(artifact["local_sha256"], sha)
        self.assertIsNone(artifact["published_digest"])
        self.assertEqual(artifact["published_metadata"]["status"], "unavailable")

    def test_historical_file_without_expected_digest_remains_unavailable(self):
        spec, sha = self.artifact()
        self.release["assets"] = []
        result = self.verify(artifacts=[spec])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["artifacts"][0]["local_sha256"], sha)
        self.assertIsNone(result["artifacts"][0]["expected_sha256"])

    def test_required_historical_digest_without_local_bytes_remains_unavailable(self):
        spec, sha = self.artifact()
        self.release["assets"] = []
        (self.root / "build.zip").unlink()
        result = self.verify(artifacts=[spec | {"sha256": sha}])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["artifacts"][0]["expected_sha256"], sha)

    def test_historical_digest_mismatch_fails_even_without_published_asset(self):
        spec, sha = self.artifact()
        self.release["assets"] = []
        (self.root / "build.zip").write_bytes(b"different historical artifact")
        for required in (True, False):
            with self.subTest(required=required):
                result = self.verify(artifacts=[spec | {"sha256": sha, "required": required}])
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["artifacts"][0]["status"], "fail")

    def test_artifact_mismatch_fails_even_when_optional(self):
        spec, _ = self.artifact()
        (self.root / "build.zip").write_bytes(b"different artifact")
        for required in (True, False):
            with self.subTest(required=required):
                result = self.verify(artifacts=[spec | {"required": required}])
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["tree_equivalence"]["status"], "pass")

    def test_conflicting_contract_and_published_digest_fail(self):
        spec, _ = self.artifact()
        result = self.verify(artifacts=[spec | {"sha256": "0" * 64}])
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["artifacts"][0]["expected_sha256"], "0" * 64)

    def test_required_missing_artifact_evidence_blocks_but_optional_does_not(self):
        spec, _ = self.artifact(digest=False)
        for contract in (spec, spec | {"path": "missing.zip"}, {"name": "missing.zip"}):
            for required in (True, False):
                with self.subTest(contract=contract, required=required):
                    result = self.verify(artifacts=[contract | {"required": required}])
                    self.assertEqual(result["status"], "unavailable" if required else "pass")
                    self.assertEqual(result["artifacts"][0]["status"], "unavailable")

    def test_duplicate_asset_names_are_ambiguous(self):
        spec, _ = self.artifact()
        self.release["assets"].append(deepcopy(self.release["assets"][0]))
        self.assertEqual(self.verify(artifacts=[spec])["status"], "ambiguous")

    def test_verification_preserves_all_repository_bytes_and_disables_lazy_fetch(self):
        spec, _ = self.artifact()
        (self.root / "source.txt").write_text("uncommitted source\n")
        before = {str(path.relative_to(self.root)): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        run = subprocess.run
        with patch("tools.adoption_release.subprocess.run", wraps=run) as mocked:
            result = self.verify(artifacts=[spec])
        after = {str(path.relative_to(self.root)): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(result["status"], "pass")
        self.assertEqual(before, after)
        for call in mocked.call_args_list:
            self.assertEqual(call.kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
            self.assertEqual(call.kwargs["env"]["GIT_NO_REPLACE_OBJECTS"], "1")


if __name__ == "__main__":
    unittest.main()
