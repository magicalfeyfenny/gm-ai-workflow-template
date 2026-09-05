import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import adoption_git
from tools.adoption_git import collect_git_evidence


class GitEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repository"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Evidence Tests")
        self.git("config", "user.email", "evidence@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.write_commit("source.txt", "base\n")

    def git(self, *args, root=None):
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "filter.lfs.process=",
             "-c", "filter.lfs.clean=", "-c", "filter.lfs.required=false",
             "-C", str(root or self.root), *args],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def write_commit(self, path, contents):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
        self.git("add", "--", path)
        self.git("commit", "-m", f"Write {path}")
        return self.git("rev-parse", "HEAD")

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }

    def add_pointer(self, data=b"authored asset\n", *, object_data=None):
        oid = hashlib.sha256(data).hexdigest()
        pointer = (
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{oid}\nsize {len(data)}\n"
        )
        self.write_commit("assets/model.bin", pointer)
        if object_data is not None:
            path = self.root / ".git" / "lfs" / "objects" / oid[:2] / oid[2:4] / oid
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(object_data)
        return oid

    def test_related_divergent_unrelated_and_missing_refs_are_preserved(self):
        self.git("switch", "-c", "dev")
        dev = self.write_commit("dev.txt", "development\n")
        self.git("switch", "-c", "topic", "main")
        topic = self.write_commit("topic.txt", "related branch\n")
        self.git("switch", "--orphan", "archive")
        archive = self.write_commit("archive.txt", "unrelated source\n")
        before = self.snapshot()

        evidence = collect_git_evidence(
            self.root, ["main", "dev", "topic", "archive", "absent"],
        )

        self.assertEqual(before, self.snapshot())
        self.assertFalse(evidence["repository"]["shallow"])
        refs = {ref["requested"]: ref for ref in evidence["refs"]}
        self.assertEqual(refs["dev"]["commit_id"], dev)
        self.assertEqual(refs["topic"]["commit_id"], topic)
        self.assertEqual(refs["archive"]["commit_id"], archive)
        self.assertFalse(refs["absent"]["available"])
        relations = {(item["left"], item["right"]): item["relationship"]
                     for item in evidence["ancestry"]}
        self.assertEqual(relations[("main", "dev")], "ancestor")
        self.assertEqual(relations[("dev", "topic")], "divergent")
        self.assertEqual(relations[("dev", "archive")], "unrelated")
        self.assertEqual(relations[("dev", "absent")], "unknown")
        self.assertIn("Divergence alone", evidence["history"]["limitations"][0])

    def test_commit_provenance_is_separate_from_tree_identity(self):
        first = self.git("rev-parse", "HEAD")
        self.git("commit", "--allow-empty", "-m", "Different provenance")
        second = self.git("rev-parse", "HEAD")
        evidence = collect_git_evidence(self.root, [first, second])
        self.assertNotEqual(first, second)
        self.assertEqual(evidence["ancestry"][0]["relationship"], "ancestor")
        self.assertTrue(evidence["ancestry"][0]["tree_equal"])
        self.assertEqual(evidence["snapshots"][1]["commit_id"], second)

    def test_annotated_and_lightweight_tags_record_tag_and_commit_objects(self):
        commit = self.git("rev-parse", "HEAD")
        self.git("tag", "lightweight")
        self.git("-c", "tag.gpgsign=false", "tag", "-a", "annotated", "-m", "Release")
        evidence = collect_git_evidence(self.root, ["refs/tags/lightweight", "refs/tags/annotated"])
        lightweight, annotated = evidence["refs"]
        self.assertEqual(lightweight["object_id"], commit)
        self.assertNotEqual(annotated["object_id"], commit)
        self.assertEqual(annotated["commit_id"], commit)
        self.assertEqual(evidence["ancestry"][0]["relationship"], "same_commit")

    def test_ambiguous_short_ref_is_not_silently_selected(self):
        self.git("tag", "main")
        self.git("config", "core.warnAmbiguousRefs", "false")
        with patch.dict(os.environ, {"LC_ALL": "fr_FR.UTF-8"}):
            evidence = collect_git_evidence(self.root, ["main", "refs/heads/main"])
        self.assertFalse(evidence["refs"][0]["available"])
        self.assertIn("ambiguous", evidence["refs"][0]["reason"])
        self.assertTrue(evidence["refs"][1]["available"])

    def test_ref_movement_during_collection_does_not_mix_object_commit_and_tree(self):
        first = self.git("rev-parse", "main")
        first_tree = self.git("rev-parse", "main^{tree}")
        self.git("switch", "-c", "dev")
        second = self.write_commit("source.txt", "concurrent new source\n")
        read_git = adoption_git._git

        def move_after_capture(root, *args, **kwargs):
            result = read_git(root, *args, **kwargs)
            if args == ("rev-parse", "--verify", "--end-of-options", "refs/heads/main"):
                self.git("update-ref", "refs/heads/main", second)
            return result

        with patch("tools.adoption_git._git", side_effect=move_after_capture):
            evidence = collect_git_evidence(self.root, ["refs/heads/main"])

        self.assertEqual(self.git("rev-parse", "main"), second)
        ref = evidence["refs"][0]
        self.assertTrue(ref["available"])
        self.assertEqual(ref["object_id"], first)
        self.assertEqual(ref["commit_id"], first)
        self.assertEqual(ref["tree_id"], first_tree)
        self.assertEqual(evidence["snapshots"][0]["commit_id"], first)
        self.assertEqual(evidence["snapshots"][0]["tree_id"], first_tree)

    def test_shallow_history_does_not_claim_independent_lineages(self):
        self.git("switch", "-c", "dev")
        self.write_commit("dev.txt", "development\n")
        shallow_root = Path(self.directory.name) / "shallow"
        self.git("clone", "--depth=1", "--no-single-branch", "--no-checkout",
                 self.root.as_uri(), str(shallow_root))
        evidence = collect_git_evidence(
            shallow_root, ["refs/remotes/origin/main", "refs/remotes/origin/dev"],
        )
        self.assertTrue(evidence["repository"]["shallow"])
        self.assertEqual(evidence["ancestry"][0]["relationship"], "unknown")
        self.assertIn("Shallow", evidence["ancestry"][0]["reason"])

    def test_historical_records_are_available_without_rewrite_inference(self):
        self.git("branch", "dev")
        second = self.write_commit("source.txt", "new source\n")
        self.git("update-ref", "-m", "selected historical update", "refs/heads/dev", second)
        evidence = collect_git_evidence(self.root, ["refs/heads/dev"])
        records = evidence["history"]["reflog_records"]
        self.assertTrue(any(record["message"] == "selected historical update"
                            and record["commit_id"] == second for record in records))
        self.assertNotIn("rewritten", evidence["history"])

    def test_tracked_configuration_and_lfs_bytes_come_from_selected_snapshots(self):
        self.write_commit(".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n")
        old = self.git("rev-parse", "HEAD")
        self.write_commit(".lfsconfig", "[lfs]\n\turl = https://example.invalid/lfs\n")
        self.write_commit("assets/.gitattributes", "*.bin -text\n")
        data = b"authored asset\n"
        oid = self.add_pointer(data, object_data=data)
        (self.root / ".gitattributes").write_text("uncommitted difference\n")
        before = self.snapshot()
        evidence = collect_git_evidence(self.root, [old, "HEAD"])
        self.assertEqual(before, self.snapshot())
        old_snapshot, current = evidence["snapshots"]
        self.assertEqual(old_snapshot["lfs_pointers"], [])
        configurations = {entry["path"]: entry for entry in current["configuration_files"]}
        self.assertEqual(set(configurations), {".gitattributes", ".lfsconfig", "assets/.gitattributes"})
        self.assertIn("filter=lfs", configurations[".gitattributes"]["text"])
        pointer = current["lfs_pointers"][0]
        self.assertEqual(pointer["oid"], oid)
        self.assertEqual(pointer["size"], len(data))
        self.assertEqual(pointer["local_object"]["status"], "available")
        self.assertEqual(pointer["local_object"]["sha256"], oid)

    def test_missing_lfs_object_is_reported_without_fetching_or_creating_storage(self):
        self.add_pointer()
        before = self.snapshot()
        evidence = collect_git_evidence(self.root, ["main"])
        self.assertEqual(before, self.snapshot())
        local = evidence["snapshots"][0]["lfs_pointers"][0]["local_object"]
        self.assertEqual(local["status"], "missing")
        self.assertFalse((self.root / ".git" / "lfs").exists())

    def test_corrupt_lfs_object_is_distinct_from_available_object(self):
        self.add_pointer(object_data=b"corrupt bytes")
        evidence = collect_git_evidence(self.root, ["main"])
        local = evidence["snapshots"][0]["lfs_pointers"][0]["local_object"]
        self.assertEqual(local["status"], "invalid")
        self.assertFalse(local["digest_matches"])
        self.assertFalse(local["size_matches"])

    def test_custom_lfs_storage_is_read_without_creating_default_storage(self):
        data = b"custom stored bytes"
        oid = self.add_pointer(data)
        self.git("config", "lfs.storage", "custom-lfs")
        path = self.root / ".git" / "custom-lfs" / "objects" / oid[:2] / oid[2:4] / oid
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        evidence = collect_git_evidence(self.root, ["main"])
        local = evidence["snapshots"][0]["lfs_pointers"][0]["local_object"]
        self.assertEqual(local["status"], "available")
        self.assertEqual(Path(local["path"]), path.resolve())
        self.assertFalse((self.root / ".git" / "lfs").exists())

    def test_malformed_pointer_preserves_unavailable_metadata(self):
        self.write_commit("assets/model.bin", "version https://git-lfs.github.com/spec/v1\n"
                          "oid sha256:wrong\nsize 10\n")
        evidence = collect_git_evidence(self.root, ["main"])
        pointer = evidence["snapshots"][0]["lfs_pointers"][0]
        self.assertFalse(pointer["valid"])
        self.assertNotIn("local_object", pointer)

    def test_missing_repository_is_explicitly_unavailable(self):
        evidence = collect_git_evidence(self.root / "absent", ["main"])
        self.assertFalse(evidence["repository"]["available"])
        self.assertTrue(evidence["repository"]["limitations"])
        self.assertEqual(evidence["refs"], [])

    def test_partial_clone_lazy_fetch_and_optional_locks_are_disabled_for_every_git_call(self):
        run = subprocess.run
        with patch("tools.adoption_git.subprocess.run", wraps=run) as calls:
            collect_git_evidence(self.root, ["main"])
        self.assertGreater(len(calls.call_args_list), 0)
        for call in calls.call_args_list:
            env = call.kwargs["env"]
            self.assertEqual(env["GIT_NO_LAZY_FETCH"], "1")
            self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(env["LC_ALL"], "C")
            self.assertIn("core.warnAmbiguousRefs=true", call.args[0])
            self.assertIn("--no-replace-objects", call.args[0])


if __name__ == "__main__":
    unittest.main()
