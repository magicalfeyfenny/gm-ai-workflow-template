"""Keep isolated-session failure diagnostics bounded and repository-owned."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .adversarial_review import ReviewContractError, ReviewSessionError
    from .adversarial_review_contracts import (
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_DIAGNOSTIC_CODES,
        SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES,
        SESSION_FAILURE_SCHEMA,
        SESSION_FAILURE_VALIDATION_STAGES,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review import (  # type: ignore[no-redef]
        ReviewContractError,
        ReviewSessionError,
    )
    from adversarial_review_contracts import (  # type: ignore[no-redef]
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_DIAGNOSTIC_CODES,
        SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES,
        SESSION_FAILURE_SCHEMA,
        SESSION_FAILURE_VALIDATION_STAGES,
    )


def session_error(
    message: str,
    *,
    role: str | None = None,
    exit_status: int | None = None,
    output_exists: bool | None = None,
    failure_class: str | None = None,
    validation_stage: str | None = None,
    diagnostic_code: str | None = None,
    diagnostic_detail_code: str | None = None,
) -> ReviewSessionError:
    """Attach bounded facts to the existing session exception type."""
    error = ReviewSessionError(message)
    error.session_role = role
    error.session_exit_status = exit_status
    error.session_output_exists = output_exists
    error.session_failure_class = failure_class
    error.session_validation_stage = validation_stage
    error.session_diagnostic_code = diagnostic_code
    error.session_diagnostic_detail_code = diagnostic_detail_code
    return error


def session_error_with_role(error: ReviewSessionError, role: str) -> ReviewSessionError:
    if getattr(error, "session_role", None) == role:
        return error
    return session_error(
        f"{role} isolated session failed",
        role=role,
        exit_status=getattr(error, "session_exit_status", None),
        output_exists=getattr(error, "session_output_exists", None),
        failure_class=getattr(error, "session_failure_class", None),
        validation_stage=getattr(error, "session_validation_stage", None),
        diagnostic_code=getattr(error, "session_diagnostic_code", None),
        diagnostic_detail_code=getattr(error, "session_diagnostic_detail_code", None),
    )


def structured_output_diagnostic(
    error: ReviewContractError,
) -> tuple[str, str, str | None]:
    """Read classification produced by the authoritative result validator."""
    stage = error.validation_stage
    code = error.diagnostic_code
    detail = error.diagnostic_detail_code
    if stage not in SESSION_FAILURE_VALIDATION_STAGES:
        stage = "shape"
    if code not in SESSION_FAILURE_DIAGNOSTIC_CODES:
        code = "output_schema"
    if detail not in SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES:
        detail = None
    return stage, code, detail


def session_failure_diagnostic(
    error: ReviewSessionError,
    *,
    role: str | None = None,
    default_failure_class: str = "startup",
) -> dict[str, object]:
    """Return only fields safe for the production human-handoff result."""
    resolved_role = getattr(error, "session_role", None) or role or "unknown"
    if resolved_role not in {"reviewer", "adjudicator", "unknown"}:
        resolved_role = "unknown"
    failure_class = getattr(error, "session_failure_class", None)
    failure_class = failure_class or default_failure_class
    if failure_class not in SESSION_FAILURE_CLASSES:
        failure_class = "startup"
    exit_status = getattr(error, "session_exit_status", None)
    if isinstance(exit_status, bool) or not isinstance(exit_status, int):
        exit_status = None
    output_exists = getattr(error, "session_output_exists", None)
    if not isinstance(output_exists, bool):
        output_exists = False
    validation_stage = getattr(error, "session_validation_stage", None)
    diagnostic_code = getattr(error, "session_diagnostic_code", None)
    diagnostic_detail_code = getattr(error, "session_diagnostic_detail_code", None)
    if failure_class == "invalid-output":
        if validation_stage not in SESSION_FAILURE_VALIDATION_STAGES:
            validation_stage = "semantic"
        if diagnostic_code not in SESSION_FAILURE_DIAGNOSTIC_CODES:
            diagnostic_code = "output_contract_validation"
        if diagnostic_detail_code not in SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES:
            diagnostic_detail_code = None
    else:
        validation_stage = None
        diagnostic_code = None
        diagnostic_detail_code = None
    return {
        "schema": SESSION_FAILURE_SCHEMA,
        "role": resolved_role,
        "exit_status": exit_status,
        "output_exists": output_exists,
        "failure_class": failure_class,
        "validation_stage": validation_stage,
        "diagnostic_code": diagnostic_code,
        "diagnostic_detail_code": diagnostic_detail_code,
    }


def output_file_failure_diagnostic(
    result_path: Path,
    *,
    output_exists: bool,
) -> tuple[str, str]:
    """Classify only the bounded file/JSON boundary, never returning file data."""
    if not output_exists:
        return "shape", "output_missing_file"
    try:
        parsed = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return "parse", "output_read_failure"
    except json.JSONDecodeError:
        return "parse", "output_json_parse"
    if not isinstance(parsed, dict):
        return "shape", "output_top_level_shape"
    return "semantic", "output_contract_validation"


def process_failure_class(
    result_path: Path,
    *,
    output_exists: bool,
) -> str:
    """Classify malformed requested output; leave other nonzero exits unknown."""
    if output_exists:
        try:
            json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return "invalid-output"
    return "provider-unclassified"
