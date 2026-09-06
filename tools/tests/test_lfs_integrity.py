"""Separate stored-pointer policy from bounded candidate LFS object evidence."""

import contextlib
import hashlib
import io
import json
import re
import shlex
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from tools.ci import check_lfs_integrity as integrity
from tools.ci.candidate_git import git_environment


class IntegrityFixture(unittest.TestCase):
    def setUp(self):
        """Store literal pointers without inheriting checkout filters or hooks."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        self.environment = git_environment()
        self.git("init", "--quiet", "--template=")
        self.git("config", "user.name", "Integrity fixture")
        self.git("config", "user.email", "fixture@example.test")
        self.data = b"\x00candidate LFS object\n"
        self.oid = hashlib.sha256(self.data).hexdigest()
        self.relative_object = Path(self.oid[:2]) / self.oid[2:4] / self.oid
        self.object = self.root / ".git/lfs/objects" / self.relative_object
        self.write_policy("required")
        (self.root / ".gitattributes").write_text("*.dat filter=lfs\n")
        self.pointer = (
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{self.oid}\nsize {len(self.data)}\n"
        )
        (self.root / "asset.dat").write_text(self.pointer)
        self.candidate = self.commit()

    def git(self, *arguments):
        """Run fixture Git without depending on developer settings."""
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *arguments],
            cwd=self.root, env=self.environment, check=True,
            text=True, capture_output=True,
        ).stdout.strip()

    def commit(self):
        """Capture an explicit commit for every evidence assertion."""
        self.git("add", "--all")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Candidate fixture")
        return self.git("rev-parse", "HEAD")

    def write_policy(self, mode):
        """Configure only the integrity mode relevant to this fixture."""
        (self.root / "PROJECT_POLICY.toml").write_text(
            f'[storage.lfs]\nfsck = "{mode}"\n', encoding="utf-8",
        )

    def write_object(self, content=None):
        """Place exact object bytes in the local source store."""
        self.object.parent.mkdir(parents=True, exist_ok=True)
        self.object.write_bytes(self.data if content is None else content)

    def collect(self, candidate=None, **kwargs):
        """Bind checks to committed state even when worktree files change."""
        return integrity.collect_integrity(
            self.root, candidate or self.candidate, **kwargs,
        )

    def assert_status(self, report, status, exit_code):
        """Check evidence semantics without freezing explanatory prose."""
        self.assertEqual(status, report["status"], report)
        self.assertEqual(exit_code, integrity.evidence_exit_code(report), report)


class IntegrityCapabilityTests(IntegrityFixture):
    def test_required_unavailable_lfs_fails_with_explicit_capability(self):
        with mock.patch.object(integrity, "_capability", return_value=(False, "missing git-lfs")):
            report = self.collect()
        self.assert_status(report, "unsupported", 1)
        self.assertEqual("missing git-lfs", report["capability"])

    def test_optional_unsupported_is_explicit_and_does_not_claim_pass(self):
        self.write_policy("optional")
        candidate = self.commit()
        with mock.patch.object(integrity, "_capability", return_value=(False, "no --objects option")):
            report = self.collect(candidate)
        self.assert_status(report, "unsupported", 0)
        self.assertNotIn("fsck_exit_code", report)

    def test_capability_requires_available_lfs_and_object_check_option(self):
        version = subprocess.CompletedProcess([], 0, b"git-lfs/fixture\n", b"")
        cases = (
            [subprocess.CompletedProcess([], 1, b"", b"git-lfs unavailable")],
            [version, subprocess.CompletedProcess([], 0, b"--pointers\n", b"")],
            [version, subprocess.CompletedProcess([], 1, b"--objects\n", b"")],
        )
        for responses in cases:
            with self.subTest(responses=responses):
                with mock.patch.object(integrity, "_git", side_effect=responses):
                    supported, detail = integrity._capability(self.root)
                self.assertFalse(supported)
                self.assertTrue(detail)
        with mock.patch.object(integrity, "_git", side_effect=[
            version, subprocess.CompletedProcess([], 0, b"--objects\n", b""),
        ]):
            self.assertTrue(integrity._capability(self.root)[0])

    def test_capability_execution_error_is_not_optional_unsupported(self):
        self.write_policy("optional")
        candidate = self.commit()
        with mock.patch.object(integrity, "_capability", side_effect=integrity.IntegrityError("timed out")):
            report = self.collect(candidate)
        self.assert_status(report, "unavailable", 1)

    def test_off_and_disabled_storage_do_not_request_object_evidence(self):
        for policy in (
            '[storage.lfs]\nfsck = "off"\n',
            '[storage]\nenabled = false\n[storage.lfs]\nfsck = "required"\n',
            'version = 1\n',
        ):
            with self.subTest(policy=policy):
                (self.root / "PROJECT_POLICY.toml").write_text(policy)
                candidate = self.commit()
                with mock.patch.object(integrity, "_capability") as capability:
                    report = self.collect(candidate)
                self.assert_status(report, "off", 0)
                capability.assert_not_called()

    def test_enabled_storage_defaults_to_required_integrity(self):
        (self.root / "PROJECT_POLICY.toml").write_text("[storage]\nenabled = true\n")
        candidate = self.commit()
        with mock.patch.object(integrity, "_capability", return_value=(False, "unavailable")):
            report = self.collect(candidate)
        self.assertEqual("required", report["mode"])
        self.assert_status(report, "unsupported", 1)

    def test_candidates_without_pointers_are_explicitly_not_applicable(self):
        (self.root / "asset.dat").write_bytes(self.data)
        candidate = self.commit()
        with mock.patch.object(integrity, "_capability") as capability:
            report = self.collect(candidate)
        self.assert_status(report, "not-applicable", 0)
        capability.assert_not_called()

    def test_missing_candidate_and_invalid_candidate_policy_fail_closed(self):
        self.assert_status(self.collect("missing-ref"), "unavailable", 1)
        self.write_policy("unknown")
        self.assert_status(self.collect(self.commit()), "unavailable", 1)

    def test_snapshot_command_failure_becomes_unavailable_evidence(self):
        error = subprocess.CalledProcessError(1, ["git", "read-tree"])
        with mock.patch.object(integrity, "candidate_snapshot", side_effect=error):
            report = self.collect()
        self.assert_status(report, "unavailable", 1)

    def test_json_output_preserves_candidate_and_failed_evidence(self):
        output = Path(self.temporary.name) / "reports/integrity.json"
        with mock.patch.object(integrity, "_capability", return_value=(False, "missing")):
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                code = integrity.main([
                    "--root", str(self.root), "--candidate-ref", self.candidate,
                    "--output", str(output),
                ])
        self.assertEqual(1, code)
        report = json.loads(output.read_text())
        self.assertEqual(report, json.loads(printed.getvalue()))
        self.assertEqual(self.candidate, report["candidate_commit"])
        self.assertIn("candidate_tree", report)
        self.assert_status(report, "unsupported", 1)

    def test_supported_fsck_failure_cannot_become_an_optional_skip(self):
        self.write_policy("optional")
        candidate = self.commit()
        original_git = integrity._git

        def copy_objects(root, pointers, storage):
            """Provide object bytes without depending on an installed LFS binary."""
            target = storage / "objects" / self.relative_object
            target.parent.mkdir(parents=True)
            target.write_bytes(self.data)

        for failure, status in (
            (subprocess.CompletedProcess([], 2, b"", b"fsck failure"), "failed"),
            (integrity.IntegrityError("fsck timed out"), "unavailable"),
        ):
            def run(root, *arguments, **kwargs):
                """Replace only the supported fsck execution with failed evidence."""
                if "fsck" in arguments and "--objects" in arguments:
                    if isinstance(failure, Exception):
                        raise failure
                    return failure
                return original_git(root, *arguments, **kwargs)

            with self.subTest(status=status):
                with mock.patch.object(integrity, "_capability", return_value=(True, "fixture LFS")):
                    with mock.patch.object(integrity, "_copy_objects", side_effect=copy_objects):
                        with mock.patch.object(integrity, "_git", side_effect=run):
                            report = self.collect(candidate)
                self.assert_status(report, status, 1)


class RealLfsIntegrityTests(IntegrityFixture):
    def setUp(self):
        """Exercise the installed LFS implementation when object fsck is supported."""
        super().setUp()
        supported, detail = integrity._capability(self.root)
        if not supported:
            self.skipTest(detail)

    def test_correct_local_object_passes_for_pointer_and_smudged_worktree(self):
        self.write_object()
        pointer_report = self.collect()
        (self.root / "asset.dat").write_bytes(self.data)
        smudged_report = self.collect()
        self.assert_status(pointer_report, "passed", 0)
        self.assert_status(smudged_report, "passed", 0)
        self.assertEqual(pointer_report["candidate_tree"], smudged_report["candidate_tree"])
        self.assertEqual(self.data, self.object.read_bytes())

    def test_missing_object_fails_even_when_integrity_is_optional(self):
        self.write_policy("optional")
        report = self.collect(self.commit())
        self.assert_status(report, "failed", 1)
        self.assertTrue(report["object_errors"])

    def test_corrupt_object_fails_without_quarantining_original_store(self):
        corrupt = b"X" * len(self.data)
        self.write_object(corrupt)
        report = self.collect()
        self.assert_status(report, "failed", 1)
        self.assertNotEqual(0, report["fsck_exit_code"])
        self.assertEqual(corrupt, self.object.read_bytes())
        self.assertFalse((self.root / ".git/lfs/bad").exists())

    def test_wrong_declared_size_fails_even_with_correct_object_hash(self):
        self.write_object()
        (self.root / "asset.dat").write_text(self.pointer.replace(
            f"size {len(self.data)}", f"size {len(self.data) + 1}",
        ))
        report = self.collect(self.commit())
        self.assert_status(report, "failed", 1)
        self.assertTrue(report["object_errors"])

    def test_committed_and_local_fetch_exclusions_cannot_hide_missing_objects(self):
        (self.root / ".lfsconfig").write_text('[lfs]\n\tfetchexclude = "*"\n')
        candidate = self.commit()
        self.git("config", "lfs.fetchexclude", "*")
        self.git("config", "lfs.fetchinclude", "unrelated/**")
        self.assert_status(self.collect(candidate), "failed", 1)

    def test_unrelated_history_and_worktree_policy_do_not_enter_candidate(self):
        self.write_object()
        (self.root / "other.dat").write_text(self.pointer.replace(self.oid, "a" * 64))
        self.commit()
        self.write_policy("off")
        report = self.collect()
        self.assert_status(report, "passed", 0)
        self.assertEqual(1, report["pointer_count"])
        self.assertEqual("required", report["mode"])

    def test_local_storage_override_is_read_without_mutation(self):
        external = Path(self.temporary.name) / "external-lfs"
        self.git("config", "lfs.storage", str(external))
        self.object = external / "objects" / self.relative_object
        self.write_object()
        self.assert_status(self.collect(), "passed", 0)
        self.assertEqual(self.data, self.object.read_bytes())

    def test_fetch_obtains_only_exact_candidate_objects_in_isolated_store(self):
        fixture = self
        requested = []

        class LfsHandler(BaseHTTPRequestHandler):
            """Serve one real object through the standard LFS batch/download API."""

            def do_POST(self):
                """Return download URLs only for the candidate's known object."""
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requested.extend(item["oid"] for item in request["objects"])
                objects = []
                for item in request["objects"]:
                    response = {"oid": item["oid"], "size": item["size"]}
                    if item["oid"] == fixture.oid:
                        response["actions"] = {"download": {"href": f"{url}/object"}}
                    else:
                        response["error"] = {"code": 404, "message": "Unknown object"}
                    objects.append(response)
                data = json.dumps({"transfer": "basic", "objects": objects}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.git-lfs+json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                """Supply object bytes for Git LFS itself to store and verify."""
                self.send_response(200)
                self.send_header("Content-Length", str(len(fixture.data)))
                self.end_headers()
                self.wfile.write(fixture.data)

            def log_message(self, format, *args):
                """Keep successful local HTTP fixture requests out of test output."""

        server = HTTPServer(("127.0.0.1", 0), LfsHandler)
        url = f"http://127.0.0.1:{server.server_port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.git("remote", "add", "origin", f"{url}/repository.git")
        (self.root / "other.dat").write_text(self.pointer.replace(self.oid, "a" * 64))
        self.commit()
        self.git("config", "lfs.fetchrecentalways", "true")
        self.git("config", "lfs.fetchexclude", "*")
        try:
            report = self.collect(fetch_remote="origin")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assert_status(report, "passed", 0)
        self.assertEqual(0, report["fetch_exit_code"])
        self.assertFalse(self.object.exists())
        self.assertEqual({self.oid}, set(requested))

    def test_fetch_failure_cannot_be_reported_as_optional_skip(self):
        self.write_policy("optional")
        report = self.collect(self.commit(), fetch_remote="missing-remote")
        self.assert_status(report, "unavailable", 1)
        self.assertNotEqual(0, report["fetch_exit_code"])


class IntegrityWorkflowTests(unittest.TestCase):
    def test_policy_and_integrity_use_the_same_explicit_ci_candidate(self):
        """Require both checks to inspect the merge candidate retained by checkout."""
        text = (integrity.ROOT / ".github/workflows/ci.yml").read_text()
        match = re.search(
            r"(?ms)^  repository-policy:\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)", text,
        )
        self.assertIsNotNone(match)
        job = match.group(1)
        self.assertNotRegex(job, r"(?m)^\s+ref:")
        commands = {}
        for line in job.replace("\\\n", " ").splitlines():
            tokens = shlex.split(line)
            if len(tokens) > 1 and tokens[0] == "python3":
                commands[Path(tokens[1]).name] = tokens[2:]
        for script in ("check_repo.py", "check_lfs_integrity.py"):
            with self.subTest(script=script):
                arguments = commands[script]
                self.assertEqual("$GITHUB_SHA", arguments[arguments.index("--candidate-ref") + 1])
        arguments = commands["check_lfs_integrity.py"]
        self.assertEqual("origin", arguments[arguments.index("--fetch-remote") + 1])
        self.assertIn("--output", arguments)


if __name__ == "__main__":
    unittest.main()
