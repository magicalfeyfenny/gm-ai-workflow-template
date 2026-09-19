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
        candidate_identity,
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
        candidate_identity,
        validate_adjudication_result,
        validate_review_packet,
        validate_review_result,
    )

try:
    from .adversarial_review_state import (
        review_lifecycle_decision,
        stage2_evidence_current,
        validate_lifecycle_state,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review_state import (  # type: ignore[no-redef]
        review_lifecycle_decision,
        stage2_evidence_current,
        validate_lifecycle_state,
    )


def _session_prompt(role: str, packet: Mapping[str, object]) -> str:
    if role == "reviewer":
        instructions = (
            "Act as the read-only adversarial reviewer. Examine only the supplied "
            "packet against its accepted contract, governance, and exclusions. "
            "Return JSON matching the output schema. Report evidence-backed "
            "findings only; do not provide fixes, commands, implementation advice, "
            "or conversational reasoning. supporting_evidence must contain only "
            "stable evidence IDs from the packet's evidence_catalog."
        )
    elif role == "adjudicator":
        instructions = (
            "Act as the independent read-only adjudicator. Use only the supplied "
            "contract, governance, candidate identity, source_items evidence, scope, "
            "and structured findings. Assign exactly one disposition to every finding. "
            "Evaluate each reviewer claim against the actual source item text; a "
            "reviewer paraphrase is not evidence. "
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


def _sandbox_path() -> str:
    path = shutil.which("sandbox-exec")
    if not path:
        raise ReviewSessionError(
            "sandbox-exec is unavailable; refusing to run an unbounded review session"
        )
    return path


def _sbpl_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')


_RUNTIME_FRAMEWORKS = (
    Path("/System/Library/Frameworks/AppKit.framework"),
    Path("/System/Library/Frameworks/CFNetwork.framework"),
    Path("/System/Library/Frameworks/CoreFoundation.framework"),
    Path("/System/Library/Frameworks/CoreGraphics.framework"),
    Path("/System/Library/Frameworks/CoreServices.framework"),
    Path("/System/Library/Frameworks/Foundation.framework"),
    Path("/System/Library/Frameworks/IOKit.framework"),
    Path("/System/Library/Frameworks/LocalAuthentication.framework"),
    Path("/System/Library/Frameworks/Security.framework"),
    Path("/System/Library/Frameworks/SystemConfiguration.framework"),
)
_RUNTIME_FILES = (
    Path("/bin/cat"),
    Path("/bin/sh"),
    Path("/usr/bin/git"),
    Path("/usr/bin/grep"),
    Path("/usr/bin/sed"),
    Path("/usr/lib/dyld"),
    Path("/usr/lib/libSystem.B.dylib"),
    Path("/usr/lib/libobjc.A.dylib"),
    Path("/usr/lib/libbz2.1.0.dylib"),
    Path("/usr/lib/libiconv.2.dylib"),
    Path("/usr/lib/liblzma.5.dylib"),
)


def _session_environment(working_directory: Path) -> tuple[dict[str, str], Path]:
    configured_home = os.environ.get("CODEX_HOME")
    source_home = (
        Path(configured_home).expanduser().resolve()
        if configured_home
        else Path.home().joinpath(".codex").resolve()
    )
    codex_home = working_directory / "codex-home"
    codex_home.mkdir(mode=0o700)
    source_auth = source_home / "auth.json"
    if source_auth.is_file():
        target_auth = codex_home / "auth.json"
        shutil.copyfile(source_auth, target_auth)
        target_auth.chmod(0o600)
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(working_directory),
        "TMPDIR": str(working_directory),
        "CODEX_HOME": str(codex_home),
        "LANG": os.environ.get("LANG", "C"),
        "LC_CTYPE": os.environ.get("LC_CTYPE", "C"),
    }
    if os.environ.get("OPENAI_API_KEY"):
        environment["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]
    return environment, codex_home


def _write_sandbox_profile(
    path: Path,
    working_directory: Path,
    command_path: Path,
    codex_home: Path,
) -> None:
    lines = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
        "(allow ipc-posix*)",
        "(allow socket-ioctl)",
        "(allow socket-option*)",
        "(allow syscall*)",
        "(allow system-fcntl)",
        "(allow system-mac-syscall)",
        "(allow system-socket)",
        "(allow mach-lookup)",
        "(allow darwin-notification-post)",
        "(allow process-exec*)",
        "(allow process-fork)",
        "(allow signal (target self))",
        "(allow network-outbound)",
    ]
    for root in _RUNTIME_FRAMEWORKS:
        encoded = _sbpl_path(root)
        lines.append(f'(allow file-read* (subpath "{encoded}"))')
        lines.append(f'(allow file-map-executable (subpath "{encoded}"))')
    for runtime_file in (command_path, *_RUNTIME_FILES):
        encoded = _sbpl_path(runtime_file)
        lines.append(f'(allow file-read* (literal "{encoded}"))')
        lines.append(f'(allow file-map-executable (literal "{encoded}"))')
        lines.append(
            f'(allow file-read-metadata file-test-existence (path-ancestors "{encoded}"))'
        )
    workspace = _sbpl_path(working_directory)
    lines.append(
        f'(allow file-read-metadata file-test-existence (path-ancestors "{workspace}"))'
    )
    lines.append(f'(allow file-read* file-write* (subpath "{workspace}"))')
    if codex_home.is_dir():
        encoded_home = _sbpl_path(codex_home)
        lines.append(f'(allow file-read-metadata (literal "{encoded_home}"))')
        auth_path = codex_home / "auth.json"
        if auth_path.is_file():
            lines.append(f'(allow file-read* (literal "{_sbpl_path(auth_path)}"))')
    lines.extend(
        [
            '(allow file-read* (literal "/private/etc/ssl/cert.pem"))',
            '(allow file-read* (literal "/private/etc/hosts"))',
            '(allow file-read* (literal "/private/etc/resolv.conf"))',
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    command_path = Path(_codex_path(executable)).resolve()
    sandbox_path = _sandbox_path()
    with tempfile.TemporaryDirectory(prefix=f"governed-{role}-") as directory:
        working_directory = Path(directory).resolve()
        schema_path = working_directory / "output-schema.json"
        result_path = working_directory / "last-message.json"
        profile_path = working_directory / "sandbox.sb"
        environment, codex_home = _session_environment(working_directory)
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        _write_sandbox_profile(
            profile_path, working_directory, command_path, codex_home
        )
        command = [
            sandbox_path,
            "-f",
            str(profile_path),
            "--",
            str(command_path),
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
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
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        except OSError as exc:
            raise ReviewSessionError(
                f"{role} session could not start: {type(exc).__name__}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ReviewSessionError(
                f"{role} session timed out after 300 seconds"
            ) from exc
        except UnicodeError as exc:
            raise ReviewSessionError(
                f"{role} session output could not be decoded"
            ) from exc
        if completed.returncode != 0:
            raise ReviewSessionError(
                f"{role} session failed with exit status {completed.returncode}"
            )
        try:
            output = result_path.read_text(encoding="utf-8")
            parsed = json.loads(output)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReviewSessionError(f"{role} session returned invalid JSON: {exc}") from exc
    parsed_mapping = _mapping(parsed, f"{role} session result")
    return parsed_mapping


SessionRunner = Callable[[str, Mapping[str, object], Mapping[str, object]], Mapping[str, object]]


def _run_adversarial_review_sessions(
    packet: Mapping[str, object],
    *,
    session_runner: SessionRunner | None = None,
    codex_executable: str = "codex",
) -> tuple[dict, dict]:
    """Run both fresh roles and retain the internal adjudication packet locally."""
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
    return adjudication, adjudication_packet


def run_adversarial_review(
    packet: Mapping[str, object],
    *,
    session_runner: SessionRunner | None = None,
    codex_executable: str = "codex",
) -> dict:
    """Run reviewer then independent adjudicator and return only adjudication."""
    adjudication, _ = _run_adversarial_review_sessions(
        packet,
        session_runner=session_runner,
        codex_executable=codex_executable,
    )
    return adjudication


def _handoff_summary(
    candidate: Mapping[str, object],
    adjudication: Mapping[str, object] | None,
    transition: Mapping[str, object],
) -> dict:
    dispositions = [] if adjudication is None else adjudication["dispositions"]
    adjudicator_handoff = (
        adjudication is not None and adjudication["human_handoff"]["required"]
    )
    required = adjudicator_handoff or transition["status"] == "human-handoff"
    reason = None
    if adjudicator_handoff:
        reason = adjudication["human_handoff"]["reason"]
    elif required:
        reason = transition["reason"]
    return {
        "required": required,
        "candidate_identity": candidate_identity(candidate),
        "finding_dispositions": [
            {
                "finding_id": item["finding_id"],
                "disposition": item["disposition"],
                "basis": item["basis"],
                "correction_accepted": item["correction_accepted"],
            }
            for item in dispositions
        ],
        "reason": reason,
        "cycle": transition["cycle"],
    }


def _session_failure_outcome(
    candidate: Mapping[str, object], lifecycle: Mapping[str, object]
) -> dict:
    """Return a bounded handoff without exposing unvalidated provider output."""
    reason = (
        "a fresh reviewer or adjudicator session failed bounded validation or "
        "execution; human disposition is required before rerun"
    )
    transition = {
        "status": "human-handoff",
        "cycle": lifecycle["cycle"],
        "corrections": [],
        "reason": reason,
        "requirements": [
            "human disposition of the failed review session",
            "fresh reviewer and adjudicator sessions",
        ],
    }
    return {
        "schema": "adversarial-review-outcome:v1",
        "candidate_identity": candidate_identity(candidate),
        "adjudication": None,
        "transition": transition,
        "human_handoff": _handoff_summary(candidate, None, transition),
    }


def run_review_lifecycle(
    packet: Mapping[str, object],
    *,
    state: Mapping[str, object] | None = None,
    session_runner: SessionRunner | None = None,
    codex_executable: str = "codex",
) -> dict:
    """Run sessions and the same deterministic state transition used by governance."""
    review_packet = validate_review_packet(packet)
    lifecycle = validate_lifecycle_state(state)
    if not stage2_evidence_current(
        review_packet,
        review_packet["candidate"],
        lifecycle["issue_contract_revision"],
    ):
        transition = {
            "status": "revalidate",
            "cycle": lifecycle["cycle"],
            "corrections": [],
            "reason": "Stage 2 evidence is stale or uses a different issue revision",
            "requirements": ["fresh Stage 2 evidence", "fresh exact candidate"],
        }
        adjudication = None
    elif (
        lifecycle["accepted_correction"]
        and lifecycle["expected_candidate"]
        != candidate_identity(review_packet["candidate"])
    ):
        transition = {
            "status": "revalidate",
            "cycle": lifecycle["cycle"],
            "corrections": [],
            "reason": "the reviewed candidate does not match the expected correction candidate",
            "requirements": ["establish the exact corrected candidate identity"],
        }
        adjudication = None
    else:
        try:
            adjudication, adjudication_packet = _run_adversarial_review_sessions(
                review_packet,
                session_runner=session_runner,
                codex_executable=codex_executable,
            )
            transition = review_lifecycle_decision(
                adjudication,
                review_packet,
                adjudication_packet,
                state=lifecycle,
            )
        except (ReviewContractError, ReviewSessionError):
            return _session_failure_outcome(review_packet["candidate"], lifecycle)
    return {
        "schema": "adversarial-review-outcome:v1",
        "candidate_identity": candidate_identity(review_packet["candidate"]),
        "adjudication": adjudication,
        "transition": transition,
        "human_handoff": _handoff_summary(
            review_packet["candidate"], adjudication, transition
        ),
    }


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
    run.add_argument("--state", type=Path)
    run.add_argument("--codex", default="codex", help="Codex executable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        packet = validate_review_packet(_load_json(args.packet))
        state = (
            validate_lifecycle_state(_load_json(args.state))
            if args.state is not None
            else validate_lifecycle_state()
        )
        result = run_review_lifecycle(
            packet,
            state=state,
            codex_executable=args.codex,
        )
        _write_json(args.output, result)
        print(f"adversarial-review: result written to {args.output}")
        return 3 if result["transition"]["status"] in {"revalidate", "human-handoff"} else 0
    except (ReviewContractError, ReviewSessionError) as exc:
        print(f"adversarial-review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
