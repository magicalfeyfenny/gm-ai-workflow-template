"""Check the aggregate's actual workflow wiring and project extension example."""

import json
import os
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

from tools.ci.aggregate_tests import evaluate


ROOT = Path(__file__).resolve().parents[2]


def load_workflow(path):
    """Keep GitHub's on key and expression scalars intact when parsing YAML."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def expression(value):
    """Compare expression meaning without requiring GitHub's optional wrapper."""
    return re.sub(r"\s+", "", value).removeprefix("${{").removesuffix("}}")


class CiTestContractTests(unittest.TestCase):
    def setUp(self):
        """Load the workflow candidate for every structural assertion."""
        self.workflow = load_workflow(ROOT / ".github/workflows/ci.yml")
        self.jobs = self.workflow["jobs"]
        self.aggregate = self.jobs["tests"]
        self.required = json.loads(self.aggregate["env"]["REQUIRED_TEST_JOBS"])

    def assert_aggregate_contract(self, jobs):
        """Require a reachable decision over complete explicitly named jobs."""
        aggregate = jobs["tests"]
        required = json.loads(aggregate["env"]["REQUIRED_TEST_JOBS"])
        dependencies = aggregate["needs"]
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        self.assertEqual(set(dependencies), set(required))
        self.assertEqual(expression(aggregate["if"]), "always()")
        self.assertEqual(aggregate["name"], "Tests")
        self.assertEqual(
            expression(aggregate["env"]["TEST_JOB_RESULTS"]), "toJSON(needs)"
        )
        success = {job: {"result": "success"} for job in dependencies}
        self.assertEqual(evaluate(required, success), [])
        for job in required:
            self.assertIn(job, jobs)
            for state in ("failure", "cancelled", "skipped"):
                with self.subTest(job=job, state=state):
                    results = {**success, job: {"result": state}}
                    self.assertTrue(evaluate(required, results))
            with self.subTest(job=job, state="missing"):
                results = {key: value for key, value in success.items() if key != job}
                self.assertTrue(evaluate(required, results))

        # Every dependency in the supported fixed-job extension must preserve
        # failing step/job conclusions, including any preparation ancestors.
        pending = ["tests", *required]
        visited = set()
        while pending:
            job_id = pending.pop()
            if job_id in visited:
                continue
            visited.add(job_id)
            job = jobs[job_id]
            self.assertEqual(job.get("continue-on-error", "false"), "false")
            self.assertNotIn("matrix", job.get("strategy", {}))
            for step in job.get("steps", []):
                self.assertEqual(step.get("continue-on-error", "false"), "false")
            needs = job.get("needs", [])
            pending.extend([needs] if isinstance(needs, str) else needs)

        command = next(
            step for step in aggregate["steps"]
            if "tools/ci/aggregate_tests.py" in step.get("run", "")
        )
        self.assertNotIn("if", command)
        self.assertEqual(
            shlex.split(command["run"]), ["python3", "tools/ci/aggregate_tests.py"]
        )
        for step in aggregate["steps"]:
            self.assertNotIn("if", step)
        self.assertTrue(any(
            step.get("uses", "").startswith("actions/checkout@")
            for step in aggregate["steps"]
        ))

    def test_actual_workflow_reaches_fail_closed_aggregate(self):
        """A dependency skip must reach a required failing Tests decision."""
        self.assert_aggregate_contract(self.jobs)

    def test_template_suite_and_dependency_install_remain_required(self):
        """Keep the repository's full suite and YAML test dependency in CI."""
        self.assertIn("template-tests", self.required)
        template = self.jobs["template-tests"]
        self.assertNotIn("if", template)
        self.assertNotIn("needs", template)
        commands = [
            shlex.split(step["run"].replace("\\\n", " "))
            for step in template["steps"] if "run" in step
        ]
        install = [
            "python3", "-m", "pip", "install", "-r", "tools/tests/requirements.txt"
        ]
        suite = [
            "python3", "-m", "unittest", "discover", "-s", "tools/tests",
            "-p", "test_*.py",
        ]
        self.assertIn(install, commands)
        self.assertIn(suite, commands)
        self.assertLess(commands.index(install), commands.index(suite))
        for step in template["steps"]:
            self.assertNotIn("if", step)

    def test_workflow_command_consumes_results_without_success_masking(self):
        """Execute the actual aggregate step with success and skipped evidence."""
        command = next(
            step["run"] for step in self.aggregate["steps"]
            if "tools/ci/aggregate_tests.py" in step.get("run", "")
        )
        for state, expected in (("success", 0), ("skipped", 1)):
            with self.subTest(state=state):
                environment = dict(os.environ)
                environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment["PATH"]
                environment["REQUIRED_TEST_JOBS"] = json.dumps(self.required)
                environment["TEST_JOB_RESULTS"] = json.dumps({
                    job: {"result": state} for job in self.required
                })
                result = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", command],
                    cwd=ROOT, env=environment, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_required_contexts_and_read_only_pr_execution_are_preserved(self):
        """Compose Tests without changing branch protection or PR privilege."""
        self.assertEqual(self.workflow["name"], "CI")
        self.assertEqual(set(self.workflow["on"]), {"pull_request"})
        trigger = self.workflow["on"]["pull_request"]
        self.assertEqual(set(trigger["branches"]), {"dev", "main"})
        self.assertFalse({"paths", "paths-ignore"}.intersection(trigger))
        self.assertTrue({
            "opened", "synchronize", "reopened", "edited", "labeled", "unlabeled"
        }.issubset(trigger["types"]))
        self.assertEqual(self.workflow["permissions"], {
            "contents": "read", "pull-requests": "read"
        })
        for job in self.jobs.values():
            self.assertNotIn("write", job.get("permissions", {}).values())
        names = [job.get("name", job_id) for job_id, job in self.jobs.items()]
        self.assertEqual(names.count("Tests"), 1)
        for path in (ROOT / ".github/rulesets").glob("*.json"):
            ruleset = json.loads(path.read_text())
            for rule in ruleset["rules"]:
                if rule["type"] == "required_status_checks":
                    contexts = {
                        check["context"]
                        for check in rule["parameters"]["required_status_checks"]
                    }
                    self.assertEqual(contexts, {"Tests", "PR policy", "Repository policy", "Format"})
                    self.assertTrue(contexts.issubset(names))

    def test_all_external_workflow_actions_are_immutable(self):
        """Check every external action reference without coupling to tag names."""
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            workflow = load_workflow(path)
            for job in workflow["jobs"].values():
                for invocation in [job, *job.get("steps", [])]:
                    reference = invocation.get("uses", "")
                    if reference and not reference.startswith("./"):
                        with self.subTest(path=path, reference=reference):
                            self.assertRegex(reference, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

    def test_documented_extension_uses_the_same_complete_contract(self):
        """Keep the copyable project extension runnable with the real evaluator."""
        document = (ROOT / "docs/CI.md").read_text()
        examples = [
            yaml.load(block, Loader=yaml.BaseLoader)
            for block in re.findall(r"```ya?ml\s*\n(.*?)```", document, re.DOTALL)
        ]
        extension = next(example for example in examples if "tests" in example)
        jobs = {**self.jobs, **extension}
        self.assert_aggregate_contract(jobs)
        self.assertGreater(set(jobs["tests"]["needs"]), {"template-tests"})
        for job in extension.values():
            for step in job.get("steps", []):
                if "uses" in step:
                    self.assertRegex(step["uses"], r"@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
