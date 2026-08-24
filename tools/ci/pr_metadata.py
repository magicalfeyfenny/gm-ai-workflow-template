#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
MAX_JSON_BYTES = 2 * 1024 * 1024

MATCH = 0
INVALID = 1
STALE = 3


class MetadataError(ValueError):
    pass


def _object(
    value: object,
    field: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MetadataError(f"{field} must be an object")

    return value


def _string(
    value: object,
    field: str,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise MetadataError(f"{field} must be a string")

    if not allow_empty and not value:
        raise MetadataError(f"{field} must not be empty")

    return value


def _positive_integer(
    value: object,
    field: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise MetadataError(f"{field} must be a positive integer")

    return value


def _body(
    value: object,
    field: str,
) -> str:
    if value is None:
        return ""

    return _string(
        value,
        field,
        allow_empty=True,
    )


def _label_names(
    value: object,
    field: str,
) -> list[str]:
    if not isinstance(value, list):
        raise MetadataError(f"{field} must be an array")

    names: list[str] = []

    for index, item in enumerate(value):
        label = _object(
            item,
            f"{field}[{index}]",
        )
        names.append(
            _string(
                label.get("name"),
                f"{field}[{index}].name",
            )
        )

    if len(names) != len(set(names)):
        raise MetadataError(f"{field} contains duplicate names")

    return sorted(names)


def _exact_keys(
    value: dict[str, object],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)

    if actual != expected:
        raise MetadataError(
            f"{field} must contain exactly {sorted(expected)}"
        )


def event_metadata_state(
    event: object,
    repository: str,
) -> dict[str, object]:
    repository = _string(repository, "repository")
    root = _object(event, "event")
    event_repository = _object(
        root.get("repository"),
        "event.repository",
    )
    event_repository_name = _string(
        event_repository.get("full_name"),
        "event.repository.full_name",
    )

    if event_repository_name != repository:
        raise MetadataError(
            "event repository does not match workflow repository"
        )

    pull_request = _object(
        root.get("pull_request"),
        "event.pull_request",
    )
    base = _object(
        pull_request.get("base"),
        "event.pull_request.base",
    )
    head = _object(
        pull_request.get("head"),
        "event.pull_request.head",
    )
    head_repository = _object(
        head.get("repo"),
        "event.pull_request.head.repo",
    )

    return {
        "repository": repository,
        "number": _positive_integer(
            pull_request.get("number"),
            "event.pull_request.number",
        ),
        "base_ref": _string(
            base.get("ref"),
            "event.pull_request.base.ref",
        ),
        "head_ref": _string(
            head.get("ref"),
            "event.pull_request.head.ref",
        ),
        "head_repository": _string(
            head_repository.get("full_name"),
            "event.pull_request.head.repo.full_name",
        ),
        "head_sha": _string(
            head.get("sha"),
            "event.pull_request.head.sha",
        ),
        "body": _body(
            pull_request.get("body"),
            "event.pull_request.body",
        ),
        "labels": _label_names(
            pull_request.get("labels"),
            "event.pull_request.labels",
        ),
    }


def current_metadata_state(
    pull_request: object,
    repository: str,
) -> dict[str, object]:
    repository = _string(repository, "repository")
    current = _object(pull_request, "current pull request")
    head_repository = _object(
        current.get("headRepository"),
        "current pull request.headRepository",
    )

    return {
        "repository": repository,
        "number": _positive_integer(
            current.get("number"),
            "current pull request.number",
        ),
        "base_ref": _string(
            current.get("baseRefName"),
            "current pull request.baseRefName",
        ),
        "head_ref": _string(
            current.get("headRefName"),
            "current pull request.headRefName",
        ),
        "head_repository": _string(
            head_repository.get("nameWithOwner"),
            "current pull request.headRepository.nameWithOwner",
        ),
        "head_sha": _string(
            current.get("headRefOid"),
            "current pull request.headRefOid",
        ),
        "body": _body(
            current.get("body"),
            "current pull request.body",
        ),
        "labels": _label_names(
            current.get("labels"),
            "current pull request.labels",
        ),
    }


def metadata_digest(
    state: dict[str, object],
) -> str:
    encoded = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def build_attestation(
    event: object,
    repository: str,
    run_id: int,
    run_attempt: int,
) -> dict[str, object]:
    run_id = _positive_integer(run_id, "workflow run id")
    run_attempt = _positive_integer(
        run_attempt,
        "workflow run attempt",
    )
    state = event_metadata_state(
        event,
        repository,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "workflow_run": {
            "id": run_id,
            "attempt": run_attempt,
        },
        "repository": repository,
        "pull_request": {
            "number": state["number"],
            "head_sha": state["head_sha"],
        },
        "metadata_sha256": metadata_digest(state),
    }


def _attestation_values(
    attestation: object,
) -> tuple[int, int, str, int, str, str]:
    root = _object(attestation, "attestation")
    _exact_keys(
        root,
        {
            "schema_version",
            "workflow_run",
            "repository",
            "pull_request",
            "metadata_sha256",
        },
        "attestation",
    )

    if root.get("schema_version") != SCHEMA_VERSION:
        raise MetadataError(
            f"attestation schema_version must be {SCHEMA_VERSION}"
        )

    workflow_run = _object(
        root.get("workflow_run"),
        "attestation.workflow_run",
    )
    _exact_keys(
        workflow_run,
        {"id", "attempt"},
        "attestation.workflow_run",
    )
    pull_request = _object(
        root.get("pull_request"),
        "attestation.pull_request",
    )
    _exact_keys(
        pull_request,
        {"number", "head_sha"},
        "attestation.pull_request",
    )
    digest = _string(
        root.get("metadata_sha256"),
        "attestation.metadata_sha256",
    )

    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise MetadataError(
            "attestation.metadata_sha256 must be lowercase SHA-256"
        )

    return (
        _positive_integer(
            workflow_run.get("id"),
            "attestation.workflow_run.id",
        ),
        _positive_integer(
            workflow_run.get("attempt"),
            "attestation.workflow_run.attempt",
        ),
        _string(
            root.get("repository"),
            "attestation.repository",
        ),
        _positive_integer(
            pull_request.get("number"),
            "attestation.pull_request.number",
        ),
        _string(
            pull_request.get("head_sha"),
            "attestation.pull_request.head_sha",
        ),
        digest,
    )


def compare_attestation(
    attestation: object,
    current_pull_request: object,
    *,
    repository: str,
    pull_request_number: int,
    head_sha: str,
    run_id: int,
    run_attempt: int,
    attestation_run_attempt: int | None = None,
) -> tuple[int, str]:
    try:
        repository = _string(repository, "repository")
        pull_request_number = _positive_integer(
            pull_request_number,
            "pull request number",
        )
        head_sha = _string(head_sha, "head SHA")
        run_id = _positive_integer(run_id, "workflow run id")
        run_attempt = _positive_integer(
            run_attempt,
            "workflow run attempt",
        )
        if attestation_run_attempt is None:
            attestation_run_attempt = run_attempt
        else:
            attestation_run_attempt = _positive_integer(
                attestation_run_attempt,
                "attestation workflow run attempt",
            )

        if attestation_run_attempt > run_attempt:
            raise MetadataError(
                "attestation attempt is newer than completed attempt"
            )

        (
            recorded_run_id,
            recorded_run_attempt,
            recorded_repository,
            recorded_pull_request,
            recorded_head_sha,
            recorded_digest,
        ) = _attestation_values(attestation)
    except MetadataError as exc:
        return INVALID, str(exc)

    envelope = (
        recorded_run_id,
        recorded_run_attempt,
        recorded_repository,
        recorded_pull_request,
        recorded_head_sha,
    )
    expected_envelope = (
        run_id,
        attestation_run_attempt,
        repository,
        pull_request_number,
        head_sha,
    )

    if envelope != expected_envelope:
        return (
            INVALID,
            "attestation does not match the triggering workflow run",
        )

    try:
        current_state = current_metadata_state(
            current_pull_request,
            repository,
        )
    except MetadataError as exc:
        return INVALID, str(exc)

    current_identity = (
        current_state["number"],
        current_state["head_sha"],
    )

    if current_identity != (
        pull_request_number,
        head_sha,
    ):
        return STALE, "current PR identity differs from validated CI"

    current_digest = metadata_digest(current_state)

    if not hmac.compare_digest(
        recorded_digest,
        current_digest,
    ):
        return STALE, "current PR metadata differs from validated CI"

    return MATCH, "current PR metadata matches validated CI"


def read_json_evidence(
    path: Path,
) -> object:
    """Read one size-bounded JSON input from an untrusted workflow source."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MetadataError(f"cannot read {path}: {exc}") from exc

    if size > MAX_JSON_BYTES:
        raise MetadataError(
            f"{path} exceeds {MAX_JSON_BYTES} bytes"
        )

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataError(f"cannot parse {path}: {exc}") from exc


def _write_json(
    path: Path,
    value: object,
) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _positive_argument(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "must be a positive integer"
        ) from exc

    if parsed < 1:
        raise argparse.ArgumentTypeError(
            "must be a positive integer"
        )

    return parsed


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    capture = commands.add_parser("capture")
    capture.add_argument(
        "--event-path",
        type=Path,
        required=True,
    )
    capture.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    capture.add_argument("--repository", required=True)
    capture.add_argument(
        "--run-id",
        type=_positive_argument,
        required=True,
    )
    capture.add_argument(
        "--run-attempt",
        type=_positive_argument,
        required=True,
    )

    compare = commands.add_parser("compare")
    compare.add_argument(
        "--attestation-path",
        type=Path,
        required=True,
    )
    compare.add_argument(
        "--current-pr-path",
        type=Path,
        required=True,
    )
    compare.add_argument("--repository", required=True)
    compare.add_argument(
        "--pull-request-number",
        type=_positive_argument,
        required=True,
    )
    compare.add_argument("--head-sha", required=True)
    compare.add_argument(
        "--run-id",
        type=_positive_argument,
        required=True,
    )
    compare.add_argument(
        "--run-attempt",
        type=_positive_argument,
        required=True,
    )
    compare.add_argument(
        "--attestation-run-attempt",
        type=_positive_argument,
    )

    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
) -> int:
    """Capture or compare bounded pull-request metadata evidence."""
    args = parse_args(argv)

    try:
        if args.command == "capture":
            event = read_json_evidence(args.event_path)
            attestation = build_attestation(
                event,
                args.repository,
                args.run_id,
                args.run_attempt,
            )
            _write_json(args.output, attestation)
            print("pr-metadata: captured CI metadata attestation")
            return MATCH

        attestation = read_json_evidence(args.attestation_path)
        current_pull_request = read_json_evidence(
            args.current_pr_path
        )
    except (MetadataError, OSError) as exc:
        print(f"pr-metadata: invalid evidence: {exc}", file=sys.stderr)
        return INVALID

    status, message = compare_attestation(
        attestation,
        current_pull_request,
        repository=args.repository,
        pull_request_number=args.pull_request_number,
        head_sha=args.head_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        attestation_run_attempt=args.attestation_run_attempt,
    )
    destination = sys.stdout if status == MATCH else sys.stderr
    print(f"pr-metadata: {message}", file=destination)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
