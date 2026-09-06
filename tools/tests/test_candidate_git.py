"""Exercise candidate semantics against real Git indexes, trees, and rules."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci.candidate_git import (
    candidate_snapshot,
    git_environment,
    is_lfs_pointer,
    parse_lfs_pointer,
)


class CandidateGitTests(unittest.TestCase):
    """Keep each case independent of the developer's Git and LFS configuration."""

    def setUp(self):
        """Initialize a disposable repository, including spaces in its path."""
        self.temporary = tempfile.TemporaryDirectory(prefix="candidate git tests ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        self.environment = git_environment()
        self.git("init", "--quiet", "--template=")
        self.git("config", "user.name", "Candidate tests")
        self.git("config", "user.email", "candidate@example.invalid")

    def git(self, *arguments: str, data: bytes | None = None) -> str:
        """Run fixture Git commands without consulting external configuration."""
        return subprocess.run(
            ["git", *arguments], cwd=self.root, env=self.environment,
            input=data, capture_output=True, check=True,
        ).stdout.decode().strip()

    def stage(self, path: str, data: bytes, mode: str = "100644") -> str:
        """Write exact staged blobs without relying on checkout or clean filters."""
        oid = self.git("hash-object", "-w", "--stdin", data=data)
        self.git("update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
        return oid

    def commit(self) -> str:
        """Create a referenceable fixture commit from the current staged tree."""
        self.git("commit", "--quiet", "-m", "Candidate fixture")
        return self.git("rev-parse", "HEAD")

    def test_staged_blobs_and_rules_ignore_worktree_and_ambient_configuration(self):
        """Dirty files, untracked rules, filters, and machine overrides stay inert."""
        self.stage("asset.bin", b"stored\0blob\n")
        self.stage(".gitattributes", b"*.bin filter=lfs -text\n")
        self.stage(".gitignore", b"tracked-ignore/\n")
        (self.root / "asset.bin").write_bytes(b"dirty checkout")
        (self.root / ".gitattributes").write_text("*.bin filter=dirty\n")
        (self.root / ".gitignore").write_text("dirty-ignore/\n")
        (self.root / "untracked").mkdir()
        (self.root / "untracked/.gitattributes").write_text("* filter=untracked\n")
        (self.root / "untracked/.gitignore").write_text("*\n")
        (self.root / ".git/info").mkdir()
        (self.root / ".git/info/attributes").write_text("*.bin filter=info\n")
        (self.root / ".git/info/exclude").write_text("info-ignore/\n")
        rules = self.root / "ambient-rules"
        rules.write_text("*.bin filter=ambient\nambient-ignore/\n")
        configuration = self.root / "ambient-config"
        configuration.write_text(
            "[core]\n"
            f" attributesFile = {rules}\n excludesFile = {rules}\n"
        )
        self.git("config", "core.attributesFile", str(rules))
        self.git("config", "core.excludesFile", str(rules))
        self.git("config", "filter.lfs.smudge", "exit 91")
        self.git("config", "filter.lfs.required", "true")
        contaminated = {
            "GIT_CONFIG_GLOBAL": str(configuration),
            "GIT_CONFIG_SYSTEM": str(configuration),
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.attributesFile",
            "GIT_CONFIG_VALUE_0": str(rules),
            "GIT_INDEX_FILE": str(self.root / "nonexistent-index"),
        }
        with patch.dict(os.environ, contaminated), candidate_snapshot(self.root) as candidate:
            self.assertEqual(candidate.read_blob("asset.bin"), b"stored\0blob\n")
            self.assertNotIn("ambient-rules", candidate.entries)
            self.assertEqual(
                candidate.attributes(["asset.bin", "untracked/test.bin"], ["filter"]),
                {"asset.bin": {"filter": "lfs"}, "untracked/test.bin": {"filter": "lfs"}},
            )
            self.assertEqual(candidate.ignored([
                "tracked-ignore/file", "dirty-ignore/file", "info-ignore/file",
                "ambient-ignore/file", "untracked/file",
            ]), {"tracked-ignore/file"})
        self.assertEqual((self.root / "asset.bin").read_bytes(), b"dirty checkout")

    def test_explicit_reference_and_index_are_independent_of_other_branches(self):
        """An explicit tree stays fixed while HEAD and the index contain other work."""
        self.stage("selected.txt", b"selected commit\n")
        selected = self.commit()
        expected_tree = self.git("rev-parse", selected + "^{tree}")
        self.stage("selected.txt", b"other branch\n")
        self.stage("unrelated.bin", b"unrelated\0blob")
        other = self.commit()
        self.git("branch", "unrelated", other)
        self.stage("selected.txt", b"staged candidate\n")
        index_tree = self.git("write-tree")
        with candidate_snapshot(self.root, selected) as explicit:
            self.assertEqual(explicit.tree, expected_tree)
            self.assertEqual(explicit.read_blob("selected.txt"), b"selected commit\n")
            self.assertNotIn("unrelated.bin", explicit.entries)
        with candidate_snapshot(self.root) as staged:
            self.assertEqual(staged.tree, index_tree)
            self.assertEqual(staged.read_blob("selected.txt"), b"staged candidate\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), other)
        self.assertEqual(self.git("write-tree"), index_tree)

    def test_git_ignore_directory_rules_nested_negation_and_root_anchors(self):
        """Git decides directory exclusions and re-inclusions at their real depths."""
        self.stage(".gitignore", (
            b"/root-only.bin\nCache/\n*.tmp\n!root.keep.tmp\n"
            b"build/*\n!build/keep/\n"
        ))
        self.stage("package/.gitignore", b"!keep.tmp\ncache-local/\n")
        self.stage("build/keep/.gitignore", b"!*.tmp\n")
        paths = [
            "root-only.bin", "package/root-only.bin", "nested/Cache/file.bin",
            "file.tmp", "root.keep.tmp", "package/file.tmp", "package/keep.tmp",
            "package/cache-local/file", "cache-local/file", "build/drop/file",
            "build/keep/file.tmp",
        ]
        with candidate_snapshot(self.root) as candidate:
            self.assertEqual(candidate.ignored(paths), {
                "root-only.bin", "nested/Cache/file.bin", "file.tmp",
                "package/file.tmp", "package/cache-local/file", "build/drop/file",
            })

    def test_attributes_apply_macros_nested_overrides_and_quoted_package_paths(self):
        """The stored index supplies Git's macro and precedence behavior intact."""
        self.stage(".gitattributes", (
            b"[attr]stored filter=lfs diff=lfs merge=lfs -text\n"
            b"*.bin stored\nassets/** filter=lfs\n"
        ))
        self.stage("assets/.gitattributes", b"*.txt !filter\nnested/*.bin -filter\n")
        self.stage("package with spaces/.gitattributes", b'"*.model" stored\n')
        paths = ["root.bin", "assets/note.txt", "assets/nested/raw.bin",
                 "package with spaces/character.model"]
        with candidate_snapshot(self.root) as candidate:
            attributes = candidate.attributes(paths, ["filter", "text", "diff"])
            self.assertEqual(attributes["root.bin"], {
                "filter": "lfs", "text": "unset", "diff": "lfs",
            })
            self.assertEqual(attributes["assets/note.txt"]["filter"], "unspecified")
            self.assertEqual(attributes["assets/nested/raw.bin"]["filter"], "unset")
            self.assertEqual(attributes["package with spaces/character.model"],
                             attributes["root.bin"])

    def test_policy_patterns_have_git_semantics_without_repository_rule_leakage(self):
        """Policy matching excludes tracked ignore files but preserves Git wildcards."""
        self.stage(".gitignore", b"*.txt\n!anything.tmp\n")
        self.stage("nested/.gitignore", b"!cache/\n")
        paths = ["readme.txt", "anything.tmp", "keep.tmp", "nested/cache/a",
                 "root.bin", "nested/root.bin"]
        with candidate_snapshot(self.root) as candidate:
            self.assertEqual(candidate.match_patterns(
                paths, ["*.tmp", "!keep.tmp", "cache/", "/root.bin"],
            ), {"anything.tmp", "nested/cache/a", "root.bin"})
            self.assertEqual(candidate.match_patterns(paths, []), set())

    def test_symlinks_are_stored_bytes_and_symlinked_rule_files_do_not_apply(self):
        """External targets cannot become content or Git rules in the snapshot."""
        outside = Path(self.temporary.name) / "outside"
        outside.write_bytes(b"external secret\n")
        link = str(outside).encode()
        self.stage("link.bin", link, "120000")
        self.stage(".gitignore", link, "120000")
        self.stage(".gitattributes", link, "120000")
        with candidate_snapshot(self.root) as candidate:
            self.assertEqual(candidate.entries["link.bin"].mode, "120000")
            self.assertEqual(candidate.entries["link.bin"].size, len(link))
            self.assertEqual(candidate.read_blob("link.bin"), link)
            self.assertFalse((candidate.root / "link.bin").is_symlink())
            self.assertEqual(candidate.ignored(["external secret"]), set())
            self.assertEqual(candidate.attributes(["link.bin"], ["filter"]), {
                "link.bin": {"filter": "unspecified"},
            })
        self.assertEqual(outside.read_bytes(), b"external secret\n")

    def test_blob_metadata_prefixes_and_gitlinks_preserve_object_types(self):
        """Metadata covers large blobs and gitlinks without treating commits as files."""
        self.stage("base.txt", b"base")
        commit = self.commit()
        payload = b"prefix\0" + b"x" * (2 * 1024 * 1024)
        blob = self.stage("large.bin", payload)
        self.stage("script.sh", b"#!/bin/sh\n", "100755")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{commit},module")
        with candidate_snapshot(self.root) as candidate:
            self.assertEqual(candidate.entries["large.bin"].oid, blob)
            self.assertEqual(candidate.entries["large.bin"].size, len(payload))
            self.assertEqual(candidate.read_blob("large.bin", limit=7), b"prefix\0")
            self.assertEqual(candidate.read_blob("large.bin", limit=0), b"")
            self.assertEqual(candidate.entries["script.sh"].mode, "100755")
            self.assertTrue(os.access(candidate.root / "script.sh", os.X_OK))
            self.assertIsNone(candidate.entries["module"].size)
            self.assertEqual(candidate.entries["module"].mode, "160000")
            self.assertFalse((candidate.root / "module").exists())
            with self.assertRaises(ValueError):
                candidate.read_blob("module")
            with self.assertRaises(ValueError):
                candidate.read_blob("large.bin", limit=-1)
        self.assertFalse(candidate.root.exists())

    def test_lfs_pointer_parser_preserves_the_shared_strict_contract(self):
        """Pointer identity and size use the same grammar as content recognition."""
        oid = "a" * 64
        header = "version https://git-lfs.github.com/spec/v1\n"
        trailer = f"oid sha256:{oid}\nsize 42\n"
        valid = header + trailer
        self.assertEqual(parse_lfs_pointer(valid), {"oid": oid, "size": 42})
        self.assertTrue(is_lfs_pointer(valid))
        self.assertTrue(is_lfs_pointer(header + f"ext-0-example sha256:{oid}\n" + trailer))
        for invalid in [
            valid.rstrip("\n"), valid.replace("size 42", "size 042"),
            valid.replace("sha256:", "sha512:"), valid + "extra\n",
            header + f"ext-0-a sha256:{oid}\next-0-b sha256:{oid}\n" + trailer,
            header + f"ext-1-a sha256:{oid}\next-0-b sha256:{oid}\n" + trailer,
        ]:
            with self.subTest(pointer=invalid):
                self.assertIsNone(parse_lfs_pointer(invalid))
                self.assertFalse(is_lfs_pointer(invalid))

    def test_alternate_path_is_plain_absolute_text_for_git_lfs_scanners(self):
        """Git LFS's alternate reader requires literal paths, including spaces."""
        oid = self.stage("stored.txt", b"stored blob")
        with candidate_snapshot(self.root) as candidate:
            alternate = (candidate.root / ".git/objects/info/alternates").read_text()
            object_store = Path(alternate.removesuffix("\n"))
            self.assertTrue(object_store.is_absolute())
            self.assertTrue(object_store.is_dir())
            self.assertIn(" ", str(object_store))
            self.assertTrue((object_store / oid[:2] / oid[2:]).is_file())

    def test_alternate_paths_with_newlines_fail_explicitly(self):
        """Unsupported alternate delimiters cannot silently change object resolution."""
        self.stage("stored.txt", b"stored blob")
        renamed = self.root.with_name("source\nnewline")
        self.root.rename(renamed)
        self.root = renamed
        with self.assertRaisesRegex(ValueError, "object directories.*newlines"):
            with candidate_snapshot(self.root):
                self.fail("A newline-bearing alternate path must fail before use")


if __name__ == "__main__":
    unittest.main()
