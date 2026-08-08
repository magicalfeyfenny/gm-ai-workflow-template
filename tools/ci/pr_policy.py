#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

POLICY = tomllib.loads(
    (ROOT / "PROJECT_POLICY.toml").read_text(encoding="utf-8")
)


def env(
    name: str,
    default: str = "",
) -> str:
    return os.environ.get(name, default).strip()


def branch_issue(
    base: str,
    head: str,
) -> tuple[int | None, list[str]]:
    if base == "dev":
        match = re.fullmatch(
            r"work/([1-9][0-9]*)-[a-z0-9][a-z0-9-]*",
            head,
        )

        if not match:
            return None, [
                "dev PR branches must match work/<issue>-<slug>"
            ]

        return int(match.group(1)), []

    if base == "main":
        match = re.fullmatch(
            r"release/([1-9][0-9]*)-"
            r"v[0-9]+\.[0-9]+\.[0-9]+"
            r"(?:-[0-9A-Za-z.-]+)?",
            head,
        )

        if not match:
            return None, [
                "main PR branches must match "
                "release/<issue>-v<semver>"
            ]

        return int(match.group(1)), []

    return None, [
        f"unsupported PR base branch: {base}"
    ]


def forced_high_risk(
    base: str,
    paths: list[str],
    additions: int,
    deletions: int,
) -> tuple[bool, list[str]]:
    rules = POLICY["risk"]
    reasons: list[str] = []

    if base == "main":
        reasons.append("PR targets main")

    if len(paths) > int(rules["max_changed_files"]):
        reasons.append(
            "changed file count exceeds low-risk limit"
        )

    if additions + deletions > int(rules["max_changed_lines"]):
        reasons.append(
            "changed line count exceeds low-risk limit"
        )

    for path in paths:
        if any(
            fnmatch.fnmatchcase(path, pattern)
            for pattern in rules["high_risk_paths"]
        ):
            reasons.append(
                f"high-risk path: {path}"
            )
            break

    return bool(reasons), reasons


def validate(
    auto_eligible: bool,
) -> int:
    base = env("PR_BASE")
    head = env("PR_HEAD")
    body = os.environ.get("PR_BODY", "")

    labels = {
        item
        for item in env("PR_LABELS").split(",")
        if item
    }

    additions = int(env("PR_ADDITIONS", "0"))
    deletions = int(env("PR_DELETIONS", "0"))

    files_path = Path(env("PR_FILES_PATH"))

    paths = [
        line.strip()
        for line in files_path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    errors: list[str] = []

    issue, branch_errors = branch_issue(
        base,
        head,
    )

    errors.extend(branch_errors)

    closure_matches = re.findall(
        r"(?mi)^Closes #([1-9][0-9]*)\s*$",
        body,
    )

    if len(closure_matches) != 1:
        errors.append(
            "PR body must contain exactly one line: "
            "Closes #<issue>"
        )
    elif (
        issue is not None
        and int(closure_matches[0]) != issue
    ):
        errors.append(
            "PR issue must match branch issue"
        )

    risk_labels = labels.intersection(
        {
            "risk:low",
            "risk:high",
        }
    )

    if len(risk_labels) != 1:
        errors.append(
            "PR must have exactly one risk label"
        )

    forced_high, reasons = forced_high_risk(
        base,
        paths,
        additions,
        deletions,
    )

    if (
        "risk:low" in labels
        and forced_high
    ):
        errors.append(
            "policy requires risk:high"
        )

    if base == "main":
        if "release" not in labels:
            errors.append(
                "main PR requires release label"
            )

        if "risk:high" not in labels:
            errors.append(
                "main PR must be risk:high"
            )

    if errors:
        for error in errors:
            print(
                f"pr-policy: {error}",
                file=sys.stderr,
            )

        for reason in reasons:
            print(
                f"pr-policy: high-risk reason: {reason}",
                file=sys.stderr,
            )

        return 1

    effective_high = (
        forced_high
        or "risk:high" in labels
    )

    if auto_eligible:
        eligible = (
            base == "dev"
            and not effective_high
            and "manual-merge" not in labels
        )

        print(
            "true"
            if eligible
            else "false"
        )
    else:
        print(
            "PR policy passed; risk: "
            + (
                "high"
                if effective_high
                else "low"
            )
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--auto-eligible",
        action="store_true",
    )

    args = parser.parse_args()

    return validate(
        args.auto_eligible
    )


if __name__ == "__main__":
    raise SystemExit(main())