"""Keep isolated-session failure diagnostics bounded and repository-owned."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

try:
    from .adversarial_review import ReviewSessionError
    from .adversarial_review_contracts import (
        ADJUDICATION_RESULT_SCHEMA,
        DISPOSITIONS,
        REVIEW_RESULT_SCHEMA,
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_DIAGNOSTIC_CODES,
        SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES,
        SESSION_FAILURE_SCHEMA,
        SESSION_FAILURE_VALIDATION_STAGES,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review import ReviewSessionError  # type: ignore[no-redef]
    from adversarial_review_contracts import (  # type: ignore[no-redef]
        ADJUDICATION_RESULT_SCHEMA,
        DISPOSITIONS,
        REVIEW_RESULT_SCHEMA,
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
    if not isinstance(parsed, Mapping):
        return "shape", "output_top_level_shape"
    return "semantic", "output_contract_validation"


_IDENTITY_FIELDS = ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256")
_REVIEW_FINDING_REQUIRED = (
    "finding_id",
    "severity",
    "defect_or_invariant",
    "supporting_evidence",
    "contract_or_governance",
)
_REVIEW_FINDING_OPTIONAL = ("affected_location", "confidence", "uncertainty")
_DISPOSITION_FIELDS = (
    "finding_id",
    "disposition",
    "basis",
    "correction",
    "correction_accepted",
)


def _object_shape(
    value: object,
    required: tuple[str, ...],
    allowed: tuple[str, ...] | None = None,
) -> str | None:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        return "output_top_level_shape"
    allowed = required if allowed is None else allowed
    if set(required) - set(value):
        return "output_missing_required_field"
    if set(value) - set(allowed):
        return "output_unsupported_field"
    return None


def _identity_shape(value: object) -> bool:
    return (
        _object_shape(value, _IDENTITY_FIELDS) is None
        and all(isinstance(value[field], str) and value[field].strip() for field in _IDENTITY_FIELDS)  # type: ignore[index]
    )


def _string_list_shape(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _review_finding_shape(value: object) -> str | None:
    code = _object_shape(
        value,
        _REVIEW_FINDING_REQUIRED,
        _REVIEW_FINDING_REQUIRED + _REVIEW_FINDING_OPTIONAL,
    )
    if code:
        return "output_schema" if code == "output_top_level_shape" else code
    assert isinstance(value, Mapping)
    if any(
        not isinstance(value[field], str) or not value[field].strip()
        for field in _REVIEW_FINDING_REQUIRED
        if field != "supporting_evidence"
    ) or not _string_list_shape(value["supporting_evidence"]):
        return "output_schema"
    if "affected_location" in value and value["affected_location"] is not None and (
        not isinstance(value["affected_location"], str)
        or not value["affected_location"].strip()
    ):
        return "output_schema"
    confidence = value.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= confidence <= 1
    ):
        return "output_schema"
    uncertainty = value.get("uncertainty")
    if uncertainty is not None and (
        not isinstance(uncertainty, str) or not uncertainty.strip()
    ):
        return "output_schema"
    return None


def _correction_shape(value: object) -> str | None:
    code = _object_shape(value, ("summary", "validation"))
    if code:
        return "output_schema" if code == "output_top_level_shape" else code
    assert isinstance(value, Mapping)
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        return "output_schema"
    if not _string_list_shape(value["validation"]):
        return "output_schema"
    return None


def structured_output_failure_diagnostic(
    role: str,
    result: object,
    packet: Mapping[str, object],
) -> tuple[str, str, str | None]:
    """Return a stage/code pair without retaining or returning rejected values."""
    fields = (
        ("schema", "candidate_identity", "findings")
        if role == "reviewer"
        else ("schema", "candidate_identity", "dispositions", "human_handoff")
    )
    code = _object_shape(result, fields)
    if code:
        return "shape", code, None
    assert isinstance(result, Mapping)
    expected_schema = REVIEW_RESULT_SCHEMA if role == "reviewer" else ADJUDICATION_RESULT_SCHEMA
    if result.get("schema") != expected_schema:
        return "shape", "output_unsupported_value", None
    identity = result.get("candidate_identity")
    if not _identity_shape(identity):
        return "shape", "output_schema", None
    expected_identity = (
        {field: packet["candidate"][field] for field in _IDENTITY_FIELDS}
        if role == "reviewer"
        else packet["candidate_identity"]
    )
    if dict(identity) != expected_identity:
        return "semantic", (
            "review_candidate_identity_mismatch"
            if role == "reviewer"
            else "adjudication_candidate_identity_mismatch"
        ), None

    if role == "reviewer":
        findings = result["findings"]
        if not isinstance(findings, list):
            return "shape", "output_schema", None
        for finding in findings:
            code = _review_finding_shape(finding)
            if code:
                return "shape", code, None
        finding_ids = [finding["finding_id"] for finding in findings]
        if len(finding_ids) != len(set(finding_ids)):
            return "semantic", "review_finding_contract", "review_finding_identity_duplicate"
        catalog = packet.get("evidence_catalog", [])
        authorized = {
            item.get("evidence_id")
            for item in catalog
            if isinstance(item, Mapping)
        }
        if any(
            set(finding["supporting_evidence"]) - authorized
            for finding in findings
        ):
            return "semantic", "review_evidence_reference", None
        return "semantic", "output_contract_validation", None

    handoff = result["human_handoff"]
    code = _object_shape(handoff, ("required", "reason"))
    if code:
        return "shape", "output_schema" if code == "output_top_level_shape" else code, None
    assert isinstance(handoff, Mapping)
    if not isinstance(handoff["required"], bool):
        return "shape", "output_schema", None
    if handoff["required"] and (
        not isinstance(handoff["reason"], str) or not handoff["reason"].strip()
    ):
        return "shape", "output_schema", None
    dispositions = result["dispositions"]
    if not isinstance(dispositions, list):
        return "shape", "output_schema", None
    findings = packet["findings"]
    expected_ids = [finding["finding_id"] for finding in findings]
    if len(dispositions) != len(expected_ids):
        return "semantic", "adjudication_disposition_contract", "adjudication_disposition_count"
    for index, disposition in enumerate(dispositions):
        code = _object_shape(disposition, _DISPOSITION_FIELDS)
        if code:
            return "shape", "output_schema" if code == "output_top_level_shape" else code, None
        assert isinstance(disposition, Mapping)
        if not all(
            isinstance(disposition[field], str) and disposition[field].strip()
            for field in ("finding_id", "disposition", "basis")
        ) or not isinstance(disposition["correction_accepted"], bool):
            return "shape", "output_schema", None
        if disposition["finding_id"] != expected_ids[index]:
            return "semantic", "adjudication_disposition_contract", "adjudication_disposition_order"
        decision = disposition["disposition"]
        if decision not in DISPOSITIONS:
            return "semantic", "adjudication_disposition_contract", "adjudication_disposition_value"
        correction = disposition["correction"]
        if correction is not None:
            code = _correction_shape(correction)
            if code:
                return "shape", code, None
        if decision in {"blocker", "patch-now"}:
            if correction is None and not (decision == "blocker" and handoff["required"]):
                return "semantic", "adjudication_correction_contract", "adjudication_correction_required_missing"
        elif correction is not None:
            return "semantic", "adjudication_correction_contract", "adjudication_correction_on_non_mutating_disposition"
        if disposition["correction_accepted"] != (correction is not None):
            return "semantic", "adjudication_correction_contract", "adjudication_correction_acceptance_mismatch"
    return "semantic", "output_contract_validation", None


def process_failure_class(
    result_path: Path,
    *,
    output_exists: bool,
) -> str:
    """Classify output corruption or leave an unknown provider exit unclassified.

    The Codex JSONL surface does not expose a reliable typed provider error.
    Auth-file state is not evidence of an authentication or sandbox failure.
    """
    if output_exists:
        try:
            json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return "invalid-output"
    return "provider-unclassified"
