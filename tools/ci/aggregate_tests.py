"""Require complete successful evidence from the configured CI test jobs."""

import json
import os
import re
import sys


def evaluate(required: object, results: object) -> list[str]:
    """Reject incomplete job results, including a missing template suite."""
    if not isinstance(required, list) or not required:
        return ["required test jobs must be a nonempty list"]
    if any(
        not isinstance(job, str)
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", job) is None
        for job in required
    ):
        return ["required test jobs must contain valid job IDs"]
    errors = []
    if len(set(required)) != len(required):
        errors.append("required test jobs contain duplicate IDs")
    if "template-tests" not in required:
        errors.append("required test jobs must include template-tests")
    if not isinstance(results, dict):
        return errors + ["test job results must be an object"]

    for job in sorted(set(required) - results.keys()):
        errors.append(f"{job}: missing required result")
    for job in sorted(results.keys() - set(required)):
        errors.append(f"{job}: result has no required-job declaration")
    for job in required:
        if job not in results:
            continue
        result = results[job]
        if not isinstance(result, dict):
            errors.append(f"{job}: invalid job result")
            continue
        conclusion = result.get("result")
        if conclusion != "success":
            errors.append(f"{job}: expected success, received {conclusion!r}")
        outputs = result.get("outputs", {})
        if not isinstance(outputs, dict):
            errors.append(f"{job}: invalid job outputs")
        elif outputs.get("evidence_limitation"):
            errors.append(
                f"{job}: automated execution/evidence limitation: "
                f"{outputs['evidence_limitation']}"
            )
    return errors


def main() -> int:
    """Read GitHub's needs JSON from the environment and fail closed."""
    try:
        required = json.loads(os.environ["REQUIRED_TEST_JOBS"])
        results = json.loads(os.environ["TEST_JOB_RESULTS"])
    except (KeyError, json.JSONDecodeError) as error:
        print(f"Tests: invalid or missing aggregate input: {error}", file=sys.stderr)
        return 1

    errors = evaluate(required, results)
    if errors:
        for error in errors:
            print(f"Tests: {error}", file=sys.stderr)
        print(
            "Tests: required automated evidence is incomplete. Unavailable "
            "runners, credentials, or tools are execution/evidence limitations; "
            "human playtesting is not a substitute.",
            file=sys.stderr,
        )
        return 1
    print(f"Tests: all required jobs succeeded: {', '.join(required)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
