"""Exercise read-only planning against isolated Git and GitHub observations."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tools.adoption_plan import Observations, create_plan, main
from tools.setup_github import REQUIRED_LABELS, REPOSITORY_SETTINGS, ROOT, SetupError


class ReadOnlyApi:
    def __init__(self, commit, tree):
        self.commit = commit
        self.tree = tree
        self.calls = []
        self.missing = set()
        self.fail = set()
        self.metadata = {**REPOSITORY_SETTINGS, "full_name": "owner/game", "archived": False}
        self.labels = [dict(label) for label in REQUIRED_LABELS]
        self.rulesets = []
        self.details = {}
        self.issues = [{"number": 7, "title": "Recover selected outcome", "labels": []}]
        self.pulls = [{"number": 8, "head": {"ref": "work/7-recovery"}, "draft": True}]

    def __call__(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, deepcopy(payload)))
        if method != "GET" or payload is not None:
            raise AssertionError("Planning attempted an API mutation")
        url = urlsplit(endpoint)
        path = url.path.removeprefix("repos/owner/game")
        if path in self.fail:
            raise SetupError("Evidence unavailable")
        page = int(parse_qs(url.query).get("page", [1])[0])
        if path == "":
            return deepcopy(self.metadata)
        if path.startswith("/git/matching-refs/heads/"):
            branch = path.rsplit("/", 1)[1]
            return [] if branch in self.missing else [{
                "ref": f"refs/heads/{branch}", "object": {"type": "commit", "sha": self.commit},
            }]
        if path.startswith("/git/commits/"):
            return {"sha": self.commit, "tree": {"sha": self.tree}, "parents": []}
        if path == "/labels":
            return deepcopy(self.labels[(page - 1) * 100:page * 100])
        if path == "/rulesets":
            return deepcopy(self.rulesets)
        if path.startswith("/rulesets/"):
            return deepcopy(self.details[int(path.rsplit("/", 1)[1])])
        if path.startswith("/rules/branches/"):
            return [{"type": "required_status_checks", "ruleset_source_type": "Organization",
                     "parameters": {"required_status_checks": [{"context": "Custom test"}]}}]
        if path.endswith("/protection"):
            return {"required_status_checks": {"contexts": ["Classic check"]}}
        if path == "/issues":
            return deepcopy(self.issues)
        if path == "/pulls":
            return deepcopy(self.pulls)
        if path == "/releases":
            return [{"id": 1, "tag_name": "v1", "draft": False, "prerelease": False,
                     "published_at": "2026-01-01T00:00:00Z", "assets": []}]
        if path == "/releases/1/assets":
            return []
        if path == "/git/ref/tags/v1":
            return {"ref": "refs/tags/v1", "object": {"type": "commit", "sha": self.commit}}
        if path.startswith("/compare/"):
            return {"status": "identical", "merge_base_commit": {"sha": self.commit}}
        raise AssertionError(f"Unexpected read: {endpoint}")


class AdoptionPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-b", "dev")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        (self.root / "game.txt").write_text("published source\n")
        self.git("add", "game.txt")
        self.git("commit", "-m", "Source")
        self.git("branch", "main")
        self.git("tag", "v1")
        self.commit = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.api = ReadOnlyApi(self.commit, self.tree)

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.root, check=True,
                                text=True, capture_output=True)
        return result.stdout.strip()

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def plan(self, **kwargs):
        return create_plan("owner/game", self.root, api=self.api, **kwargs)

    def test_default_planning_preserves_content_refs_settings_and_tracking(self):
        before = self.snapshot()
        remote_before = deepcopy((self.api.metadata, self.api.labels, self.api.issues, self.api.pulls))
        plan = self.plan()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((self.api.metadata, self.api.labels, self.api.issues, self.api.pulls), remote_before)
        self.assertTrue(all(method == "GET" and payload is None
                            for method, _, payload in self.api.calls))
        self.assertEqual(plan["release_verification"]["status"], "pass")
        self.assertEqual(plan["remote"]["issues"], self.api.issues)
        self.assertEqual(plan["remote"]["pull_requests"], self.api.pulls)
        self.assertTrue(any(item["kind"] == "canonical_lineage"
                            for item in plan["unresolved_decisions"]))

    def test_archived_missing_branches_and_default_branch_are_evidence(self):
        self.api.metadata.update(archived=True, default_branch="legacy")
        self.api.missing.update({"main", "dev"})
        plan = self.plan()
        self.assertTrue(plan["remote"]["repository"]["archived"])
        self.assertEqual(plan["remote"]["branches"]["dev"]["status"], "missing")
        self.assertEqual(plan["remote"]["branches"]["legacy"]["commit"], self.commit)
        # Existing local main cannot fill in a missing live main implicitly.
        self.assertEqual(plan["release_verification"]["status"], "unavailable")
        self.assertTrue(any(item["kind"] == "archive_disposition"
                            for item in plan["unresolved_decisions"]))
        self.assertFalse(any("archived" in item["payload"] or "/git/refs" in item["endpoint"]
                             for item in plan["proposed_mutations"]))

    def test_inherited_custom_and_classic_protection_survives_in_plan(self):
        self.api.rulesets = [
            {"id": 11, "name": "organization-policy", "source": "owner", "source_type": "Organization"},
            {"id": 12, "name": "dev-protection", "source": "owner/game", "source_type": "Repository"},
            {"id": 13, "name": "custom-policy", "source": "owner/game", "source_type": "Repository"},
        ]
        self.api.details = {item["id"]: {**item, "rules": [{"type": "required_signatures"}]}
                            for item in self.api.rulesets}
        plan = self.plan()
        protection = plan["remote"]["protection"]
        self.assertEqual(protection["rulesets"], self.api.rulesets)
        self.assertEqual(protection["branches"]["dev"]["classic_protection"]
                         ["required_status_checks"]["contexts"], ["Classic check"])
        self.assertEqual(protection["branches"]["dev"]["active_rules"][0]
                         ["parameters"]["required_status_checks"], [{"context": "Custom test"}])
        changes = plan["proposed_mutations"]
        replace = next(item for item in changes if item["endpoint"].endswith("/rulesets/12"))
        self.assertEqual(replace["before"], self.api.details[12])
        self.assertEqual(replace["method"], "PUT")
        self.assertFalse(any(item["endpoint"].endswith(("/11", "/13")) for item in changes))

    def test_label_pagination_and_exact_reviewable_payloads(self):
        self.api.labels = [{"name": f"custom-{index}"} for index in range(102)]
        self.api.labels.append({"name": "blocked", "color": "aaaaaa"})
        self.api.metadata["allow_squash_merge"] = False
        plan = self.plan()
        self.assertEqual(plan["remote"]["labels"], self.api.labels)
        changes = plan["proposed_mutations"]
        settings = next(item for item in changes if item["endpoint"] == "repos/owner/game")
        self.assertEqual(settings["payload"], {"allow_squash_merge": True})
        renamed = next(item for item in changes if item["endpoint"].endswith("/labels/blocked"))
        self.assertEqual(renamed["payload"]["new_name"], "work:blocked")
        self.assertFalse(any(item["method"] == "DELETE" for item in changes))
        self.assertTrue(any("page=2" in endpoint for _, endpoint, _ in self.api.calls))

    def test_unavailable_protection_does_not_become_empty_or_replacement(self):
        self.api.fail.add("/rulesets")
        plan = self.plan()
        self.assertIsNone(plan["remote"]["protection"]["rulesets"])
        self.assertTrue(plan["unavailable_evidence"])
        self.assertFalse(any("/rulesets" in item["endpoint"] for item in plan["proposed_mutations"]))

    def test_explicit_lineage_records_identity_reason_and_outcomes(self):
        plan = self.plan(lineage="refs/heads/dev", lineage_reason="Saved source is canonical.",
                         outcomes=["Restore the selected game implementation"])
        recovery = plan["recovery"]
        self.assertEqual(recovery["lineage_identity"]["commit_id"], self.commit)
        self.assertEqual(recovery["intended_outcomes"], ["Restore the selected game implementation"])
        self.assertFalse(any(item["kind"].startswith("canonical_lineage")
                             for item in plan["unresolved_decisions"]))
        missing = self.plan(lineage="refs/heads/missing", lineage_reason="Chosen externally",
                            outcomes=["Recover source"])
        self.assertTrue(any(item["kind"] == "canonical_lineage_unavailable"
                            for item in missing["unresolved_decisions"]))

    def test_cli_defaults_to_plan_and_reports_incomplete_evidence(self):
        report = {"mode": "plan", "release_verification": {"status": "unavailable"},
                  "unavailable_evidence": []}
        output = io.StringIO()
        with patch("tools.adoption_plan.create_plan", return_value=report) as create:
            with contextlib.redirect_stdout(output):
                code = main(["--repo", "owner/game", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), report)
        self.assertEqual(create.call_args.args, ("owner/game", self.root))

    def test_setup_dispatch_never_calls_bootstrap(self):
        from tools.setup_github import main as setup_main

        with patch("tools.adoption_plan.main", return_value=1) as planning:
            with patch("tools.setup_github.configure_repository") as bootstrap:
                code = setup_main(["adopt-existing", "--repo", "owner/game"])
        self.assertEqual(code, 1)
        bootstrap.assert_not_called()
        planning.assert_called_once_with(["--repo", "owner/game"])

    def test_script_entrypoint_preserves_repository_even_without_bytecode_flag(self):
        # Exercise real dispatch/imports/Git reads with a GET-only gh executable.
        self.plan()
        responses = {endpoint: self.api(method, endpoint, payload)
                     for method, endpoint, payload in list(self.api.calls)}
        for name in ("__init__.py", "setup_github.py", "adoption_plan.py",
                     "adoption_git.py", "adoption_release.py"):
            target = self.root / "tools" / name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(ROOT / "tools" / name, target)
        shutil.copytree(ROOT / ".github/rulesets", self.root / ".github/rulesets")
        with tempfile.TemporaryDirectory() as command_dir:
            directory = Path(command_dir)
            response_file = directory / "responses.json"
            response_file.write_text(json.dumps(responses))
            executable = directory / "gh"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                "from pathlib import Path\n"
                "assert sys.argv[1:4] == ['api', '--method', 'GET']\n"
                "assert len(sys.argv) == 5\n"
                f"data = json.loads(Path({str(response_file)!r}).read_text())\n"
                "print(json.dumps(data[sys.argv[4]]))\n"
            )
            executable.chmod(0o755)
            environment = os.environ.copy()
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            environment["PATH"] = command_dir + os.pathsep + environment["PATH"]
            before = self.snapshot()
            result = subprocess.run(
                [sys.executable, str(self.root / "tools/setup_github.py"),
                 "adopt-existing", "--repo", "owner/game", "--root", str(self.root)],
                cwd=self.root, env=environment, text=True, capture_output=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["release_verification"]["status"], "pass")
        self.assertEqual(self.snapshot(), before)

    def test_partial_pages_are_unavailable(self):
        def read(method, endpoint, payload):
            if parse_qs(urlsplit(endpoint).query)["page"] == ["1"]:
                return [{} for _ in range(100)]
            raise SetupError("Second page inaccessible")

        reader = Observations(read)
        self.assertIsNone(reader.pages("repos/owner/game/labels"))
        self.assertTrue(reader.unavailable)


if __name__ == "__main__":
    unittest.main()
