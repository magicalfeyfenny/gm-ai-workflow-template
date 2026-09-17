"""Run the reviewer and adjudicator in fresh, read-only Codex sessions."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

try:
    from .adversarial_review import (
        ADJUDICATION_RESULT_OUTPUT_SCHEMA,
        ReviewContractError,
        ReviewSessionError,
        REVIEW_RESULT_OUTPUT_SCHEMA,
        _copy_json,
        _mapping,
        _reject_forbidden_keys,
        build_adjudication_packet,
        validate_adjudication_result,
        validate_review_packet,
        validate_review_result,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review import (  # type: ignore[no-redef]
        ADJUDICATION_RESULT_OUTPUT_SCHEMA,
        ReviewContractError,
        ReviewSessionError,
        REVIEW_RESULT_OUTPUT_SCHEMA,
        _copy_json,
        _mapping,
        _reject_forbidden_keys,
        build_adjudication_packet,
        validate_adjudication_result,
        validate_review_packet,
        validate_review_result,
    )


def _session_prompt(role: str, packet: Mapping[str, object]) -> str:
    if role == "reviewer":
        instructions = (
            "Act as the read-only adversarial reviewer. Examine only the supplied "
            "packet against its accepted contract, governance, and exclusions. "
            "Return JSON matching the output schema. Report evidence-backed "
            "findings only; do not provide fixes, commands, implementation advice, "
            "or conversational reasoning."
        )
    elif role == "adjudicator":
        instructions = (
            "Act as the independent read-only adjudicator. Use only the supplied "
            "contract, governance, candidate identity, evidence, scope, and "
            "structured findings. Assign exactly one disposition to every finding. "
            "Return JSON matching the output schema. Return current-pass corrections "
            "only for supported blocker or patch-now decisions; set human_handoff "
            "when disagreement, uncertainty, oscillation, scope, authority, or the "
            "correction cap prevents a safe decision. Do not return raw findings as "
            "implementation instructions."
        )
    else:
        raise ReviewSessionError(f"unsupported isolated session role: {role}")
    encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2)
    return f"{instructions}\n\nBOUNDARY-PACKET (JSON):\n{encoded}\n"


def _codex_path(executable: str) -> str:
    path = executable if os.path.isabs(executable) else shutil.which(executable)
    if not path:
        raise ReviewSessionError(f"Codex executable is unavailable: {executable}")
    return path


def _run_fresh_codex_session(
    role: str,
    packet: Mapping[str, object],
    output_schema: Mapping[str, object],
    *,
    executable: str = "codex",
) -> dict:
    """Run one fresh provider process with no repository or prior session context."""
    copied_packet = _copy_json(packet, f"{role} packet")
    _reject_forbidden_keys(copied_packet, f"{role} packet")
    schema = _copy_json(output_schema, f"{role} output schema")
    if not isinstance(schema, Mapping):
        raise ReviewSessionError(f"{role} output schema must be an object")
    command_path = _codex_path(executable)
    with tempfile.TemporaryDirectory(prefix=f"governed-{role}-") as directory:
        working_directory = Path(directory)
        schema_path = working_directory / "output-schema.json"
        result_path = working_directory / "last-message.json"
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        command = [
            command_path,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "-C",
            str(working_directory),
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=working_directory,
                input=_session_prompt(role, copied_packet),
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReviewSessionError(f"{role} session could not start: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ReviewSessionError(
                f"{role} session failed with exit status {completed.returncode}"
                + (f": {detail[:1000]}" if detail else "")
            )
        try:
            output = result_path.read_text(encoding="utf-8")
            parsed = json.loads(output)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReviewSessionError(f"{role} session returned invalid JSON: {exc}") from exc
    parsed_mapping = _mapping(parsed, f"{role} session result")
    return parsed_mapping


SessionRunner = Callable[[str, Mapping[str, object], Mapping[str, object]], Mapping[str, object]]


def run_adversarial_review(
    packet: Mapping[str, object],
    *,
    session_runner: SessionRunner | None = None,
    codex_executable: str = "codex",
) -> dict:
    """Run reviewer then independent adjudicator and return only adjudication."""
    review_packet = validate_review_packet(packet)
    if session_runner is None:
        def session_runner(
            role: str,
            session_packet: Mapping[str, object],
            output_schema: Mapping[str, object],
        ) -> Mapping[str, object]:
            return _run_fresh_codex_session(
                role,
                session_packet,
                output_schema,
                executable=codex_executable,
            )

    reviewer_raw = session_runner(
        "reviewer", review_packet, REVIEW_RESULT_OUTPUT_SCHEMA
    )
    reviewer_result = validate_review_result(reviewer_raw, review_packet)
    adjudication_packet = build_adjudication_packet(
        review_packet, reviewer_result["findings"]
    )
    adjudicator_raw = session_runner(
        "adjudicator", adjudication_packet, ADJUDICATION_RESULT_OUTPUT_SCHEMA
    )
    adjudication = validate_adjudication_result(
        adjudicator_raw, adjudication_packet
    )
    return adjudication


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewContractError(f"cannot read JSON packet {path}: {exc}") from exc


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    try:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ReviewContractError(f"cannot write review result {path}: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the bounded isolated adversarial review and adjudication stage."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--packet", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--codex", default="codex", help="Codex executable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        packet = validate_review_packet(_load_json(args.packet))
        result = run_adversarial_review(
            packet,
            codex_executable=args.codex,
        )
        _write_json(args.output, result)
        print(f"adversarial-review: result written to {args.output}")
        return 0
    except (ReviewContractError, ReviewSessionError) as exc:
        print(f"adversarial-review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
