"""Run dependency-sensitive repository checks through the environment router."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

if __package__:
    from .python_environment import (
        DEFAULT_REQUIREMENTS,
        EnvironmentSetupError,
        select_environment,
    )
else:
    from python_environment import (  # type: ignore[no-redef]
        DEFAULT_REQUIREMENTS,
        EnvironmentSetupError,
        select_environment,
    )


ROOT = Path(__file__).resolve().parents[2]


def _check_command(
    check: str,
    root: Path,
    executable: Path,
    baseline_ref: str | None,
    candidate_ref: str | None,
) -> tuple[str, list[str], Path, dict[str, str]]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if check == "repository-policy":
        command = [str(executable), str(root / "tools/ci/check_repo.py")]
        if baseline_ref:
            command.extend(["--baseline-ref", baseline_ref])
        if candidate_ref:
            command.extend(["--candidate-ref", candidate_ref])
        return check, command, root, environment

    test_environment = {
        key: value
        for key, value in environment.items()
        if not key.startswith("GIT_")
    }
    return (
        "template-tests",
        [
            str(executable),
            "-m",
            "unittest",
            "discover",
            "-s",
            "tools/tests",
            "-p",
            "test_*.py",
        ],
        root,
        test_environment,
    )


def _run_check(
    name: str,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
) -> int:
    print(f"repository-check: name={name} interpreter={command[0]}", flush=True)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        print(
            f"repository-check: {name} could not start: {exc}",
            file=sys.stderr,
        )
        return 2

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        print(
            f"repository-check: {name} failed with exit status {result.returncode}",
            file=sys.stderr,
        )
    else:
        print(f"repository-check: {name} passed")
    return result.returncode


def run_checks(
    check: str,
    *,
    root: Path = ROOT,
    requirements: Path | None = DEFAULT_REQUIREMENTS,
    explicit_interpreter: str | None = None,
    baseline_ref: str | None = None,
    candidate_ref: str | None = None,
) -> int:
    """Select one environment and run one or both repository checks."""
    selected = select_environment(
        root,
        requirements=requirements,
        explicit_interpreter=explicit_interpreter,
    )
    try:
        print(selected.evidence(), flush=True)
        for diagnostic in selected.diagnostics:
            print(f"python-environment: candidate={diagnostic}", flush=True)

        checks = (
            ("repository-policy", "repository-policy"),
            ("template-tests", "tests"),
        ) if check == "all" else ((check, check),)
        results: list[int] = []
        for _, check_name in checks:
            name, command, cwd, environment = _check_command(
                check_name,
                root,
                selected.executable,
                baseline_ref,
                candidate_ref,
            )
            results.append(_run_check(name, command, cwd, environment))
        return next((result for result in results if result), 0)
    finally:
        selected.cleanup()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Route repository checks through a validated Python environment.",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS,
        help="pinned dependency file; use --no-requirements for policy-only checks",
    )
    parser.add_argument("--no-requirements", action="store_true")
    parser.add_argument(
        "--interpreter",
        help="explicit interpreter or environment path; otherwise read .python-version",
    )
    subparsers = parser.add_subparsers(dest="check", required=True)
    for name in ("all", "repository-policy", "tests"):
        subparser = subparsers.add_parser(name)
        if name in {"all", "repository-policy"}:
            subparser.add_argument("--baseline-ref")
            subparser.add_argument("--candidate-ref")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    requirements = None if args.no_requirements else args.requirements
    if args.check == "repository-policy" and not args.no_requirements:
        requirements = None
    try:
        return run_checks(
            args.check,
            root=args.root,
            requirements=requirements,
            explicit_interpreter=args.interpreter,
            baseline_ref=getattr(args, "baseline_ref", None),
            candidate_ref=getattr(args, "candidate_ref", None),
        )
    except EnvironmentSetupError as exc:
        print(f"python-environment: setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
