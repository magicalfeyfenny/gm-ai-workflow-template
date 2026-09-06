"""Exercise required test evidence with synthetic GitHub job results."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from tools.ci.aggregate_tests import evaluate


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR = ROOT / "tools/ci/aggregate_tests.py"
REQUIRED = ["template-tests", "gamemaker-tests", "package-build"]


def successful_results(jobs: list[str]) -> dict[str, dict[str, object]]:
    """Build independent successful constituent results for each fixture."""
    return {job: {"result": "success", "outputs": {}} for job in jobs}


def run_cli(
    required: str | None,
    results: str | None,
) -> subprocess.CompletedProcess[str]:
    """Run the real script with controlled aggregate environment inputs."""
    environment = os.environ.copy()
    environment.pop("REQUIRED_TEST_JOBS", None)
    environment.pop("TEST_JOB_RESULTS", None)
    if required is not None:
        environment["REQUIRED_TEST_JOBS"] = required
    if results is not None:
        environment["TEST_JOB_RESULTS"] = results
    return subprocess.run(
        [sys.executable, str(AGGREGATOR)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


class AggregateEvidenceTests(unittest.TestCase):
    """Require positive evidence from every explicitly configured suite."""

    def test_template_only_and_multiple_required_jobs_succeed(self) -> None:
        """The empty template and projects with additional suites can pass."""
        for required in (["template-tests"], REQUIRED):
            with self.subTest(required=required):
                results = successful_results(list(reversed(required)))
                self.assertEqual(evaluate(required, results), [])

    def test_each_required_non_success_conclusion_fails(self) -> None:
        """Other successes cannot hide any required unsuccessful result."""
        for job in REQUIRED:
            for conclusion in (
                "failure", "cancelled", "skipped", "unknown", "neutral", None,
            ):
                with self.subTest(job=job, conclusion=conclusion):
                    results = successful_results(REQUIRED)
                    results[job]["result"] = conclusion
                    errors = evaluate(REQUIRED, results)
                    self.assertTrue(errors)
                    self.assertTrue(any(job in error for error in errors))

    def test_each_missing_job_or_conclusion_fails(self) -> None:
        """Absent required evidence and absent conclusions are both failures."""
        for job in REQUIRED:
            for absent in ("job", "conclusion"):
                with self.subTest(job=job, absent=absent):
                    results = successful_results(REQUIRED)
                    if absent == "job":
                        del results[job]
                    else:
                        del results[job]["result"]
                    errors = evaluate(REQUIRED, results)
                    self.assertTrue(errors)
                    self.assertTrue(any(job in error for error in errors))

    def test_multiple_incomplete_jobs_are_all_reported(self) -> None:
        """A failure does not suppress evidence about another missing job."""
        results = successful_results(REQUIRED)
        results["gamemaker-tests"]["result"] = "failure"
        del results["package-build"]
        errors = evaluate(REQUIRED, results)
        for job in ("gamemaker-tests", "package-build"):
            self.assertTrue(any(job in error for error in errors))

    def test_configuration_requires_template_and_unique_valid_job_ids(self) -> None:
        """Empty or malformed declarations cannot create vacuous success."""
        configurations = (
            [], None, {}, "template-tests", 1, False,
            ["gamemaker-tests"],
            ["template-tests", "template-tests"],
            ["template-tests", ""],
            ["template-tests", "job with spaces"],
            ["template-tests", "job.name"],
            ["template-tests", 1],
            ["template-tests", None],
            ["template-tests", []],
        )
        for required in configurations:
            with self.subTest(required=required):
                jobs = (
                    [job for job in required if isinstance(job, str)]
                    if isinstance(required, list) else []
                )
                self.assertTrue(evaluate(required, successful_results(jobs)))

    def test_result_structure_must_supply_objects(self) -> None:
        """Invalid needs objects, job records, and outputs fail closed."""
        required = ["template-tests"]
        for invalid in (None, [], "success", 1, True):
            with self.subTest(location="needs", invalid=invalid):
                self.assertTrue(evaluate(required, invalid))
            with self.subTest(location="job", invalid=invalid):
                self.assertTrue(evaluate(required, {"template-tests": invalid}))
            with self.subTest(location="outputs", invalid=invalid):
                results = successful_results(required)
                results["template-tests"]["outputs"] = invalid
                self.assertTrue(evaluate(required, results))

    def test_undeclared_results_fail_even_when_successful(self) -> None:
        """A dependency cannot silently bypass the required-job declaration."""
        results = successful_results(REQUIRED)
        errors = evaluate(["template-tests"], results)
        self.assertTrue(errors)
        for job in ("gamemaker-tests", "package-build"):
            self.assertTrue(any(job in error for error in errors))

    def test_evidence_limitations_fail_even_with_success(self) -> None:
        """Unavailable capability cannot be converted into successful evidence."""
        limitations = (
            "Licensed GameMaker runner unavailable",
            "Required signing credential unavailable",
            "Unsupported runtime environment",
        )
        for conclusion in ("success", "failure", "skipped"):
            for limitation in limitations:
                with self.subTest(conclusion=conclusion, limitation=limitation):
                    results = successful_results(REQUIRED)
                    results["gamemaker-tests"] = {
                        "result": conclusion,
                        "outputs": {"evidence_limitation": limitation},
                    }
                    errors = evaluate(REQUIRED, results)
                    self.assertTrue(errors)
                    self.assertTrue(any(limitation in error for error in errors))

    def test_absent_or_empty_limitation_allows_complete_evidence(self) -> None:
        """Ordinary outputs and an empty capability message preserve success."""
        for outputs in ({}, {"evidence_limitation": ""}, {"artifact": "build"}):
            with self.subTest(outputs=outputs):
                results = {
                    "template-tests": {"result": "success", "outputs": outputs}
                }
                self.assertEqual(evaluate(["template-tests"], results), [])
        self.assertEqual(
            evaluate(["template-tests"], {"template-tests": {"result": "success"}}),
            [],
        )


class AggregateCliTests(unittest.TestCase):
    """Check actual process exit status and useful operator diagnostics."""

    def test_success_exit_reports_every_required_suite(self) -> None:
        """A complete successful run emits a success report and exit zero."""
        completed = run_cli(
            json.dumps(REQUIRED), json.dumps(successful_results(REQUIRED))
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertIn("Tests", completed.stdout)
        for job in REQUIRED:
            self.assertIn(job, completed.stdout)

    def test_failure_exit_identifies_job_and_conclusion(self) -> None:
        """The workflow process itself fails when a required suite is cancelled."""
        results = successful_results(REQUIRED)
        results["package-build"]["result"] = "cancelled"
        completed = run_cli(json.dumps(REQUIRED), json.dumps(results))
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("package-build", completed.stderr)
        self.assertIn("cancelled", completed.stderr)

    def test_limitation_exit_preserves_the_missing_capability(self) -> None:
        """The CLI reports the execution limitation despite a success conclusion."""
        limitation = "GameMaker license not configured on runner"
        results = successful_results(REQUIRED)
        results["gamemaker-tests"]["outputs"] = {"evidence_limitation": limitation}
        completed = run_cli(json.dumps(REQUIRED), json.dumps(results))
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("gamemaker-tests", completed.stderr)
        self.assertIn(limitation, completed.stderr)
        self.assertIn("evidence", completed.stderr.lower())

    def test_missing_or_malformed_environment_fails_without_traceback(self) -> None:
        """Either missing JSON input produces a controlled failed aggregate."""
        valid_required = json.dumps(["template-tests"])
        valid_results = json.dumps(successful_results(["template-tests"]))
        for required, results in (
            (None, valid_results),
            (valid_required, None),
            (None, None),
            ("{", valid_results),
            (valid_required, "{"),
            ("", valid_results),
            (valid_required, ""),
        ):
            with self.subTest(required=required, results=results):
                completed = run_cli(required, results)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")
                self.assertTrue(completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
