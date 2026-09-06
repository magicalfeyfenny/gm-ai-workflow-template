#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# Historical checker execution supplies this directory through sys.path as well.
if __package__:
    from .candidate_git import candidate_snapshot, is_lfs_pointer
    from .storage_policy import (
        collect_storage_errors, historical_storage_errors, storage_policy_errors,
    )
else:
    from candidate_git import candidate_snapshot, is_lfs_pointer
    from storage_policy import (
        collect_storage_errors, historical_storage_errors, storage_policy_errors,
    )

ROOT = Path(__file__).resolve().parents[2]
ASSET_COMPLETION_LEVELS = frozenset(
    {
        "deterministic-placeholder",
        "authored-placeholder",
        "final",
    }
)


@dataclass(frozen=True)
class SourceLineViolation:
    """Only source line counts have an established non-worsening order."""

    path: str
    limit: int
    count: int

    def __str__(self) -> str:
        """Keep the human diagnostic separate from its comparison fields."""
        return f"{self.path}: {self.count} lines exceeds limit {self.limit}"


PolicyError = str | SourceLineViolation
CHECKER_CONTRACT_PATHS = frozenset({
    "PROJECT_POLICY.toml", "tools/ci/check_repo.py", "tools/ci/candidate_git.py",
    "tools/ci/storage_policy.py",
})


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


def validate_structure(
    root: Path,
    policy: dict,
    files: list[Path],
    errors: list[PolicyError],
) -> None:
    """Collect line measurements without inferring severity from diagnostics."""
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
            errors.append(SourceLineViolation(key, max_lines, count))


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


def collect_errors(root: Path, include_storage: bool = True) -> list[PolicyError]:
    """Collect typed line violations and exact, unordered diagnostics."""
    policy = load_policy(root)
    files = tracked_files(root)
    errors: list[PolicyError] = []

    validate_structure(root, policy, files, errors)
    validate_json(root, files, errors)
    validate_assets(root, policy, files, errors)
    if include_storage:
        errors.extend(collect_storage_errors(root))

    return errors


def baseline_policy_errors(root: Path, checker_root: Path | None = None) -> list[str]:
    """Run the historical checker against its tree or a candidate data snapshot."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import inspect, json, runpy, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(sys.argv[1]).parent))\n"
            "checker = runpy.run_path(sys.argv[1])\n"
            "collect = checker['collect_errors']\n"
            "options = ({'include_storage': False} if 'include_storage' in\n"
            "           inspect.signature(collect).parameters else {})\n"
            "errors = collect(Path.cwd(), **options)\n"
            "line_type = checker.get('SourceLineViolation')\n"
            "if not isinstance(errors, list) or any(\n"
            "    not isinstance(error, str) and not (\n"
            "        isinstance(line_type, type) and type(error) is line_type\n"
            "    ) for error in errors\n"
            "):\n"
            "    raise ValueError('invalid baseline diagnostics')\n"
            "print(json.dumps([str(error) for error in errors]))",
            str((checker_root or root) / "tools/ci/check_repo.py"),
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


def historical_candidate_errors(baseline: Path, candidate: Path) -> list[str]:
    """Check candidate data under old rules so contract edits cannot hide growth.

    Execute the historical checker separately from the data it inspects, so
    even edits to the candidate checker source remain subject to the old rules.
    """
    with tempfile.TemporaryDirectory(prefix="repository-policy-candidate-") as temporary:
        snapshot = Path(temporary)
        for path in tracked_files(candidate):
            source = baseline if path.as_posix() == "PROJECT_POLICY.toml" else candidate
            target = snapshot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / path, target)
        for command in (["git", "init", "--quiet"], ["git", "add", "--all", "--force"]):
            subprocess.run(command, cwd=snapshot, check=True, capture_output=True)
        return baseline_policy_errors(snapshot, checker_root=baseline)


def new_policy_errors(
    errors: list[PolicyError],
    baseline_errors: list[PolicyError],
    strict: bool = False,
) -> list[PolicyError]:
    """Match inherited occurrences once; only the same line rule may improve."""
    inherited = Counter(
        str(error) if strict else error
        for error in baseline_errors
        if strict or isinstance(error, str)
    )
    line_counts: dict[tuple[str, int], list[int]] = defaultdict(list)
    if not strict:
        for error in baseline_errors:
            if isinstance(error, SourceLineViolation):
                line_counts[(error.path, error.limit)].append(error.count)
        for counts in line_counts.values():
            counts.sort()

    # Match the largest counts first so duplicate accounting is order-independent.
    ordered = sorted(
        enumerate(errors),
        key=lambda item: item[1].count if isinstance(item[1], SourceLineViolation) else 0,
        reverse=True,
    )
    introduced: set[int] = set()
    for index, error in ordered:
        if not strict and isinstance(error, SourceLineViolation):
            counts = line_counts[(error.path, error.limit)]
            if counts and error.count <= counts[-1]:
                counts.pop()
            else:
                introduced.add(index)
        else:
            identity = str(error) if strict else error
            if inherited[identity]:
                inherited[identity] -= 1
            else:
                introduced.add(index)

    return [error for index, error in enumerate(errors) if index in introduced]


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


def changed_files(ref: str, candidate_ref: str | None = None) -> set[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            ref,
            *([candidate_ref] if candidate_ref is not None else []),
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
    parser.add_argument(
        "--candidate-ref",
        help="inspect all content from this stored Git tree (storage defaults to the index)",
    )
    return parser.parse_args()


def main() -> int:
    """Check local content or an explicit stored candidate with bounded baselines."""
    args = parse_args()
    try:
        with ExitStack() as contexts:
            candidate = contexts.enter_context(candidate_snapshot(ROOT, args.candidate_ref))
            # Local content checks retain their authoring workflow. Storage always
            # uses the frozen index; CI explicitly selects its stored merge candidate.
            content_root = candidate.root if args.candidate_ref else ROOT
            print(f"repository-policy: storage candidate tree {candidate.tree}")
            errors = collect_errors(content_root, include_storage=False)
            if args.baseline_ref:
                baseline, baseline_sha = contexts.enter_context(detached_checkout(args.baseline_ref))
                changed = changed_files(baseline_sha, args.candidate_ref)
                if changed & CHECKER_CONTRACT_PATHS:
                    baseline_errors = baseline_policy_errors(baseline)
                    errors = new_policy_errors(errors, baseline_errors, strict=True)
                    errors.extend(
                        f"under baseline checker and policy: {error}"
                        for error in new_policy_errors(
                            historical_candidate_errors(baseline, content_root),
                            baseline_errors, strict=True,
                        )
                    )
                else:
                    errors = new_policy_errors(
                        errors, collect_errors(baseline, include_storage=False)
                    )
            errors.extend(storage_policy_errors(ROOT, args.baseline_ref, candidate.tree))
            if args.baseline_ref and changed & CHECKER_CONTRACT_PATHS:
                errors.extend(historical_storage_errors(ROOT, baseline_sha, candidate.tree))
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(
            "repository-policy: candidate or baseline is unavailable or could not "
            f"be validated: {exc}", file=sys.stderr,
        )
        return 2

    if errors:
        prefix = "new or worsened violation: " if args.baseline_ref else ""
        for error in errors:
            print(f"repository-policy: {prefix}{error}", file=sys.stderr)
        return 1
    print("repository policy passed" + (
        ": no new or worsened violations" if args.baseline_ref else ""
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
