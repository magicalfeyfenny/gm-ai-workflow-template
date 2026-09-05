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
ASSET_COMPLETION_LEVELS = frozenset(
    {
        "deterministic-placeholder",
        "authored-placeholder",
        "final",
    }
)


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


def is_lfs_pointer(text: str) -> bool:
    """Recognize stored pointers before interpreting materialized asset content."""
    # Current v1 encoding and extension records: git-lfs/docs/spec.md and
    # git-lfs/docs/extensions.md. This recognizes content, not storage policy.
    if len(text.encode("utf-8")) >= 1024:
        return False
    match = re.fullmatch(
        r"version https://git-lfs.github.com/spec/v1\n"
        r"(?P<extensions>(?:ext-(?:0|[1-9][0-9]*)-[a-z0-9.-]+ "
        r"sha256:[0-9a-f]{64}\n)*)"
        r"oid sha256:[0-9a-f]{64}\n"
        r"size (?:0|[1-9][0-9]*)\n",
        text,
    )
    if match is None:
        return False
    keys = [line.split(" ", 1)[0] for line in match["extensions"].splitlines()]
    priorities = [key.split("-", 2)[1] for key in keys]
    return keys == sorted(keys) and len(priorities) == len(set(priorities))


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
            text = (root / path).read_bytes().decode("utf-8")
            if not is_lfs_pointer(text):
                json.loads(text)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            errors.append(
                f"{path}: invalid JSON: {exc}"
            )


def configured_roots(pipeline: dict, field: str) -> list[Path]:
    """Return the locations owned by one pipeline, without inherited aliases."""
    return [Path(value) for value in pipeline[field]]


def valid_asset_path(path: Path, roots: list[Path]) -> bool:
    """Require a repository-relative path inside a configured location."""
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and any(is_under(path, location) for location in roots)
    )


def validate_source(
    root: Path,
    path: Path,
    tracked: set[str],
    errors: list[str],
) -> None:
    """Editable packages must retain every existing and tracked descendant."""
    full_path = root / path
    if not full_path.exists():
        errors.append(f"{path}: source does not exist")
        return
    if not full_path.is_dir():
        if path.as_posix() not in tracked:
            errors.append(f"{path}: source is not tracked")
        return

    prefix = path.as_posix().rstrip("/") + "/"
    package_tracked = {key for key in tracked if key.startswith(prefix)}
    if not package_tracked:
        errors.append(f"{path}: source package has no tracked descendants")

    present = {
        child.relative_to(root).as_posix()
        for child in full_path.rglob("*")
        if not child.is_dir()
    }
    for key in sorted(present - package_tracked):
        errors.append(f"{key}: source package descendant is not tracked")
    for key in sorted(package_tracked):
        if not (root / key).is_file():
            errors.append(f"{key}: tracked source package descendant is missing")


def validate_destination(
    root: Path,
    destination: object,
    pipeline: dict,
    tracked: set[str],
    subject: str,
    errors: list[str],
) -> list[Path]:
    """Bind exported artifacts to one resource or an explicit runtime file contract."""
    if not isinstance(destination, dict):
        errors.append(f"{subject}: destination must be an object")
        return []

    kind = destination.get("kind")
    if kind == "included-file":
        reason = destination.get("file_contract")
        if (
            set(destination) != {"kind", "file_contract"}
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            errors.append(f"{subject}: included-file requires only a file_contract reason")
            return []
        return configured_roots(pipeline, "runtime_roots")

    if kind != "native-resource":
        errors.append(f"{subject}: unknown destination kind {kind}")
        return []
    resource = destination.get("resource")
    if (
        set(destination) != {"kind", "resource"}
        or not isinstance(resource, str)
        or not resource
    ):
        errors.append(f"{subject}: native-resource requires only a resource path")
        return []

    path = Path(resource)
    if (
        path.suffix.lower() != ".yy"
        or not valid_asset_path(path, configured_roots(pipeline, "native_resource_roots"))
    ):
        errors.append(f"{path}: invalid native resource descriptor path")
        return []
    if not (root / path).is_file():
        errors.append(f"{path}: native resource descriptor does not exist")
    if path.as_posix() not in tracked:
        errors.append(f"{path}: native resource descriptor is not tracked")

    # Native resources own their embedded files and may themselves be exports.
    return [path.parent]


def validate_pipeline_extensions(
    pipeline: dict,
    paths: list[Path],
    role: str,
    subject: str,
    errors: list[str],
) -> None:
    """Allowed formats are alternatives; companion deliverables are explicit."""
    allowed = set(pipeline[f"{role}_extensions"])
    required = set(pipeline.get(f"required_{role}_extensions", []))
    actual = {path.suffix.lower() for path in paths}
    if not actual.issubset(allowed):
        errors.append(
            f"{subject}: unsupported {role} extensions {sorted(actual - allowed)}"
        )
    if not required.issubset(actual):
        errors.append(
            f"{subject}: missing required {role} extensions {sorted(required - actual)}"
        )


def validate_assets(
    root: Path,
    policy: dict,
    files: list[Path],
    errors: list[str],
) -> None:
    assets = policy["assets"]

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

    if not isinstance(manifest, dict):
        errors.append(f"{manifest_path}: manifest must be an object")
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
        completion = entry.get("completion")
        sources = entry.get("sources")
        runtime = entry.get("runtime")

        if not isinstance(completion, str) or completion not in ASSET_COMPLETION_LEVELS:
            errors.append(
                f"{manifest_path}: export {index} has invalid completion "
                f"level {completion}"
            )

        if not isinstance(kind, str) or kind not in pipelines:
            errors.append(
                f"{manifest_path}: export {index} has unknown kind {kind}"
            )
            continue

        if (
            not isinstance(sources, list)
            or not sources
            or not all(isinstance(item, str) and item for item in sources)
        ):
            errors.append(
                f"{manifest_path}: export {index} has invalid sources"
            )
            continue

        if (
            not isinstance(runtime, list)
            or not runtime
            or not all(isinstance(item, str) and item for item in runtime)
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

        pipeline = pipelines[kind]
        subject = f"{manifest_path}: export {index}"
        source_roots = configured_roots(pipeline, "source_roots")
        runtime_roots = validate_destination(
            root, entry.get("destination"), pipeline, tracked, subject, errors
        )
        validate_pipeline_extensions(pipeline, source_paths, "source", subject, errors)
        validate_pipeline_extensions(pipeline, runtime_paths, "runtime", subject, errors)

        for path in source_paths:
            if not valid_asset_path(path, source_roots):
                errors.append(
                    f"{path}: invalid source path"
                )
                continue

            validate_source(root, path, tracked, errors)

        for path in runtime_paths:
            if not valid_asset_path(path, runtime_roots):
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

            if not full_path.is_file():
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
                try:
                    text = full_path.read_bytes().decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    errors.append(f"{path}: runtime SVG is unreadable or not UTF-8")
                    continue

                if is_lfs_pointer(text):
                    continue
                if text.startswith("version "):
                    errors.append(f"{path}: invalid LFS pointer in runtime SVG")
                elif (
                    "inkscape:" in text
                    or "xmlns:inkscape" in text
                    or "sodipodi:" in text
                ):
                    errors.append(
                        f"{path}: runtime SVG is not plain SVG"
                    )

    # Only dedicated export locations promise complete inventory coverage.
    # Native resource directories also contain independently authored resources.
    inventory_roots = {
        location
        for pipeline in pipelines.values()
        for location in configured_roots(pipeline, "runtime_roots")
    }

    for path in files:
        key = path.as_posix()

        if not any(is_under(path, location) for location in inventory_roots):
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


def baseline_policy_errors(root: Path) -> list[str]:
    """Evaluate a historical tree with the checker and policy it actually owned."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, runpy; from pathlib import Path; "
            "checker = runpy.run_path('tools/ci/check_repo.py'); "
            "print(json.dumps(checker['collect_errors'](Path.cwd())))",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    errors = json.loads(result.stdout)
    if not isinstance(errors, list) or not all(isinstance(error, str) for error in errors):
        raise ValueError("baseline checker did not return a list of diagnostics")
    return errors


def new_policy_errors(
    errors: list[str],
    baseline_errors: list[str],
    changed_paths: set[str] | None = None,
    strict: bool = False,
) -> list[str]:
    changed = changed_paths or set()

    def key(error: str) -> str:
        subject = error.split(":", 1)[0]

        if strict or subject in changed:
            return error

        return policy_error_key(error)

    inherited = Counter(
        key(error)
        for error in baseline_errors
    )
    introduced: list[str] = []

    for error in errors:
        identity = key(error)

        if inherited[identity]:
            inherited[identity] -= 1
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
def detached_checkout(ref: str) -> Iterator[tuple[Path, str]]:
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

        yield checkout, resolved


def changed_files(ref: str) -> set[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            ref,
            "--",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )

    return {
        item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    }


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
            with detached_checkout(args.baseline_ref) as (
                baseline,
                baseline_sha,
            ):
                baseline_errors = baseline_policy_errors(baseline)
            changed = changed_files(baseline_sha)
        except (subprocess.CalledProcessError, ValueError):
            print(
                "repository-policy: baseline is unavailable or could not be validated: "
                f"{args.baseline_ref}",
                file=sys.stderr,
            )
            return 2

        if errors:
            strict = bool(
                changed
                & {
                    "PROJECT_POLICY.toml",
                    "tools/ci/check_repo.py",
                }
            )
            errors = new_policy_errors(
                errors,
                baseline_errors,
                changed,
                strict,
            )

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
