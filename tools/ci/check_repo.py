#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]


def load_policy(root: Path) -> dict:
    return tomllib.loads(
        (root / "PROJECT_POLICY.toml").read_text(encoding="utf-8")
    )


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )

    return [
        Path(value.decode("utf-8"))
        for value in result.stdout.split(b"\0")
        if value
    ]


def is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def source_is_tracked(
    path: Path,
    tracked: set[str],
) -> bool:
    key = path.as_posix()

    if key in tracked:
        return True

    prefix = key.rstrip("/") + "/"

    return any(
        item.startswith(prefix)
        for item in tracked
    )


def validate_structure(
    root: Path,
    policy: dict,
    files: list[Path],
    errors: list[str],
) -> None:
    rules = policy["structure"]

    extensions = set(rules["source_extensions"])
    forbidden = set(rules["forbidden_generic_stems"])
    exceptions = set(rules["large_file_exceptions"])
    max_lines = int(rules["max_source_lines"])

    for path in files:
        key = path.as_posix()

        if key in exceptions:
            continue

        if path.suffix.lower() not in extensions:
            continue

        if path.stem.lower() in forbidden:
            errors.append(
                f"{path}: generic source filename is forbidden"
            )

        try:
            text = (root / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(
                f"{path}: source must be UTF-8"
            )
            continue

        count = len(text.splitlines())

        if count > max_lines:
            errors.append(
                f"{path}: {count} lines exceeds limit {max_lines}"
            )


def validate_json(
    root: Path,
    files: list[Path],
    errors: list[str],
) -> None:
    for path in files:
        if path.suffix.lower() != ".json":
            continue

        try:
            json.loads(
                (root / path).read_text(encoding="utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            errors.append(
                f"{path}: invalid JSON: {exc}"
            )


def validate_assets(
    root: Path,
    policy: dict,
    files: list[Path],
    errors: list[str],
) -> None:
    assets = policy["assets"]

    source_root = Path(assets["source_root"])
    runtime_root = Path(assets["runtime_root"])
    manifest_path = Path(assets["manifest"])

    tracked = {
        path.as_posix()
        for path in files
    }

    try:
        manifest = json.loads(
            (root / manifest_path).read_text(encoding="utf-8")
        )
    except OSError:
        errors.append(
            f"{manifest_path}: manifest is missing or unreadable"
        )
        return
    except json.JSONDecodeError as exc:
        errors.append(
            f"{manifest_path}: invalid manifest: {exc}"
        )
        return

    if manifest.get("version") != 1:
        errors.append(
            f"{manifest_path}: version must be 1"
        )

    entries = manifest.get("exports")

    if not isinstance(entries, list):
        errors.append(
            f"{manifest_path}: exports must be a list"
        )
        return

    pipelines = assets["pipelines"]
    mapped_runtime: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(
                f"{manifest_path}: export {index} must be an object"
            )
            continue

        kind = entry.get("kind")
        sources = entry.get("sources")
        runtime = entry.get("runtime")

        if kind not in pipelines:
            errors.append(
                f"{manifest_path}: export {index} has unknown kind {kind}"
            )
            continue

        if (
            not isinstance(sources, list)
            or not sources
            or not all(isinstance(item, str) for item in sources)
        ):
            errors.append(
                f"{manifest_path}: export {index} has invalid sources"
            )
            continue

        if (
            not isinstance(runtime, list)
            or not runtime
            or not all(isinstance(item, str) for item in runtime)
        ):
            errors.append(
                f"{manifest_path}: export {index} has invalid runtime"
            )
            continue

        source_paths = [
            Path(item)
            for item in sources
        ]

        runtime_paths = [
            Path(item)
            for item in runtime
        ]

        expected_source_extensions = set(
            pipelines[kind]["source_extensions"]
        )

        expected_runtime_extensions = set(
            pipelines[kind]["runtime_extensions"]
        )

        actual_source_extensions = {
            path.suffix.lower()
            for path in source_paths
        }

        actual_runtime_extensions = {
            path.suffix.lower()
            for path in runtime_paths
        }

        if actual_source_extensions != expected_source_extensions:
            errors.append(
                f"{manifest_path}: export {index} kind {kind} "
                f"requires source extensions "
                f"{sorted(expected_source_extensions)}"
            )

        if actual_runtime_extensions != expected_runtime_extensions:
            errors.append(
                f"{manifest_path}: export {index} kind {kind} "
                f"requires runtime extensions "
                f"{sorted(expected_runtime_extensions)}"
            )

        for path in source_paths:
            if (
                path.is_absolute()
                or ".." in path.parts
                or not is_under(path, source_root)
            ):
                errors.append(
                    f"{path}: invalid source path"
                )
                continue

            full_path = root / path

            if not full_path.exists():
                errors.append(
                    f"{path}: source does not exist"
                )
                continue

            if not source_is_tracked(path, tracked):
                errors.append(
                    f"{path}: source is not tracked"
                )

        for path in runtime_paths:
            if (
                path.is_absolute()
                or ".." in path.parts
                or not is_under(path, runtime_root)
            ):
                errors.append(
                    f"{path}: invalid runtime path"
                )
                continue

            key = path.as_posix()

            if key in mapped_runtime:
                errors.append(
                    f"{path}: runtime export mapped more than once"
                )

            mapped_runtime.add(key)

            full_path = root / path

            if not full_path.exists():
                errors.append(
                    f"{path}: runtime export does not exist"
                )
                continue

            if key not in tracked:
                errors.append(
                    f"{path}: runtime export is not tracked"
                )

            if (
                assets["plain_runtime_svg"]
                and path.suffix.lower() == ".svg"
            ):
                text = full_path.read_text(encoding="utf-8")

                if (
                    "inkscape:" in text
                    or "xmlns:inkscape" in text
                    or "sodipodi:" in text
                ):
                    errors.append(
                        f"{path}: runtime SVG is not plain SVG"
                    )

    runtime_prefix = runtime_root.as_posix().rstrip("/") + "/"

    for path in files:
        key = path.as_posix()

        if not key.startswith(runtime_prefix):
            continue

        if path.name in {
            ".gitkeep",
            "README.md",
        }:
            continue

        if key not in mapped_runtime:
            errors.append(
                f"{path}: runtime asset is missing from "
                f"{manifest_path}"
            )


def collect_errors(root: Path) -> list[str]:
    policy = load_policy(root)
    files = tracked_files(root)
    errors: list[str] = []

    validate_structure(root, policy, files, errors)
    validate_json(root, files, errors)
    validate_assets(root, policy, files, errors)

    return errors


def new_policy_errors(
    errors: list[str],
    baseline_errors: list[str],
) -> list[str]:
    inherited = Counter(
        policy_error_key(error)
        for error in baseline_errors
    )
    introduced: list[str] = []

    for error in errors:
        key = policy_error_key(error)

        if inherited[key]:
            inherited[key] -= 1
        else:
            introduced.append(error)

    return introduced


def policy_error_key(error: str) -> str:
    normalized = re.sub(
        r"(: export )\d+",
        r"\1#",
        error,
    )
    normalized = re.sub(
        r": \d+ lines exceeds limit \d+$",
        ": source line limit exceeded",
        normalized,
    )

    for marker in (
        ": invalid JSON:",
        ": invalid manifest:",
    ):
        if marker in normalized:
            return normalized.split(marker, 1)[0] + marker[:-1]

    return normalized


@contextmanager
def detached_checkout(ref: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(
        prefix="repository-policy-",
    ) as temporary:
        checkout = Path(temporary) / "baseline"
        resolved = subprocess.run(
            [
                "git",
                "rev-parse",
                "--verify",
                f"{ref}^{{commit}}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        environment = os.environ.copy()
        environment["GIT_LFS_SKIP_SMUDGE"] = "1"

        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--shared",
                "--no-checkout",
                str(ROOT),
                str(checkout),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )

        subprocess.run(
            [
                "git",
                "checkout",
                "--quiet",
                "--detach",
                resolved,
            ],
            cwd=checkout,
            check=True,
            capture_output=True,
            env=environment,
        )

        yield checkout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline-ref",
        help=(
            "allow repository-policy violations already present "
            "at this Git ref"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = collect_errors(ROOT)

    if args.baseline_ref:
        try:
            with detached_checkout(args.baseline_ref) as baseline:
                baseline_errors = collect_errors(baseline)
        except subprocess.CalledProcessError:
            print(
                "repository-policy: baseline ref is unavailable: "
                f"{args.baseline_ref}",
                file=sys.stderr,
            )
            return 2

        if errors:
            errors = new_policy_errors(errors, baseline_errors)

    if errors:
        for error in errors:
            print(
                f"repository-policy: {error}",
                file=sys.stderr,
            )

        return 1

    if args.baseline_ref:
        print("repository policy passed: no new violations")
    else:
        print("repository policy passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
