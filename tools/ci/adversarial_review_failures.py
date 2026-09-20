"""Keep isolated-session failure diagnostics bounded and repository-owned."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .adversarial_review import ReviewSessionError
    from .adversarial_review_contracts import (
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_SCHEMA,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review import ReviewSessionError  # type: ignore[no-redef]
    from adversarial_review_contracts import (  # type: ignore[no-redef]
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_SCHEMA,
    )


def session_error(
    message: str,
    *,
    role: str | None = None,
    exit_status: int | None = None,
    output_exists: bool | None = None,
    failure_class: str | None = None,
) -> ReviewSessionError:
    """Attach bounded facts to the existing session exception type."""
    error = ReviewSessionError(message)
    error.session_role = role
    error.session_exit_status = exit_status
    error.session_output_exists = output_exists
    error.session_failure_class = failure_class
    return error


def session_error_with_role(error: ReviewSessionError, role: str) -> ReviewSessionError:
    if getattr(error, "session_role", None) == role:
        return error
    return session_error(
        str(error),
        role=role,
        exit_status=getattr(error, "session_exit_status", None),
        output_exists=getattr(error, "session_output_exists", None),
        failure_class=getattr(error, "session_failure_class", None),
    )


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
    return {
        "schema": SESSION_FAILURE_SCHEMA,
        "role": resolved_role,
        "exit_status": exit_status,
        "output_exists": output_exists,
        "failure_class": failure_class,
    }


def process_failure_class(
    result_path: Path,
    *,
    output_exists: bool,
    authentication_available: bool,
) -> str:
    """Classify a nonzero provider exit without forwarding provider text."""
    if output_exists:
        try:
            json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return "invalid-output"
    if not authentication_available:
        return "authentication"
    return "sandbox"
