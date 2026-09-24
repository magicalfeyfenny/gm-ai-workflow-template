"""Persist the single validated result and continuation input for review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

try:
    from .adversarial_review import _digest, candidate_identity
    from .adversarial_review_contracts import (
        RISK_TIERS,
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_DIAGNOSTIC_CODES,
        SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES,
        SESSION_FAILURE_SCHEMA,
        SESSION_FAILURE_VALIDATION_STAGES,
        ReviewContractError,
    )
    from .pr_policy import correction_retry_budget
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review import _digest, candidate_identity  # type: ignore[no-redef]
    from adversarial_review_contracts import (  # type: ignore[no-redef]
        RISK_TIERS,
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_DIAGNOSTIC_CODES,
        SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES,
        SESSION_FAILURE_SCHEMA,
        SESSION_FAILURE_VALIDATION_STAGES,
        ReviewContractError,
    )
    from pr_policy import correction_retry_budget  # type: ignore[no-redef]


LIFECYCLE_ARTIFACT_SCHEMA = "adversarial-review-lifecycle:v2"
MAX_HANDOFF_REASON_LENGTH = 320
_ARTIFACT_FIELDS = {
    "schema",
    "status",
    "risk",
    "issue_contract_revision",
    "cycle",
    "candidate_identity",
    "prior_candidate_identities",
    "corrections",
    "reason",
    "session_failure",
}
_IDENTITY_FIELDS = ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256")
_CONTENT_FIELDS = ("tree_sha", "diff_sha256")
_CORRECTION_FIELDS = {
    "finding_id",
    "disposition",
    "basis",
    "correction",
}
_SESSION_FAILURE_FIELDS = {
    "schema",
    "role",
    "exit_status",
    "output_exists",
    "failure_class",
    "validation_stage",
    "diagnostic_code",
    "diagnostic_detail_code",
}
_STATUSES = {"complete", "revalidate-and-rereview", "human-handoff"}


def _text(value: object, subject: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewContractError(f"{subject} must be a non-empty string")
    return value


def _risk(value: object) -> str:
    if value not in RISK_TIERS:
        raise ReviewContractError(
            "lifecycle risk must be one of: " + ", ".join(RISK_TIERS)
        )
    return value


def _identity(value: object, subject: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(_IDENTITY_FIELDS):
        raise ReviewContractError(f"{subject} must contain exactly the candidate identity")
    return candidate_identity(value)


def _content_key(value: Mapping[str, object]) -> tuple[str, str]:
    identity = candidate_identity(value)
    return tuple(identity[field] for field in _CONTENT_FIELDS)  # type: ignore[return-value]


def _reason(value: object) -> str:
    reason = _text(value, "lifecycle handoff reason")
    normalized = " ".join("".join(
        char if char.isprintable() else " " for char in reason
    ).split())
    if not normalized:
        raise ReviewContractError("lifecycle handoff reason is empty after sanitizing")
    return normalized[:MAX_HANDOFF_REASON_LENGTH]


def _corrections(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ReviewContractError("lifecycle corrections must be a list")
    corrections = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        subject = f"lifecycle corrections[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _CORRECTION_FIELDS:
            raise ReviewContractError(f"{subject} has unsupported or missing fields")
        finding_id = _text(raw["finding_id"], f"{subject}.finding_id")
        if finding_id in seen:
            raise ReviewContractError("lifecycle corrections contain a duplicate finding")
        seen.add(finding_id)
        disposition = raw["disposition"]
        if disposition not in {"blocker", "patch-now"}:
            raise ReviewContractError(f"{subject}.disposition cannot direct remediation")
        basis = _text(raw["basis"], f"{subject}.basis")
        correction = raw["correction"]
        if not isinstance(correction, Mapping) or set(correction) != {"summary"}:
            raise ReviewContractError(f"{subject}.correction is malformed")
        corrections.append(
            {
                "finding_id": finding_id,
                "disposition": disposition,
                "basis": basis,
                "correction": {
                    "summary": _text(correction["summary"], f"{subject}.correction.summary")
                },
            }
        )
    return corrections


def _session_failure(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != _SESSION_FAILURE_FIELDS:
        raise ReviewContractError("lifecycle session failure has unsupported or missing fields")
    if value["schema"] != SESSION_FAILURE_SCHEMA:
        raise ReviewContractError("lifecycle session failure schema is unsupported")
    if value["role"] not in {"reviewer", "adjudicator", "unknown"}:
        raise ReviewContractError("lifecycle session failure role is unsupported")
    exit_status = value["exit_status"]
    if exit_status is not None and (
        not isinstance(exit_status, int) or isinstance(exit_status, bool)
    ):
        raise ReviewContractError("lifecycle session failure exit status is invalid")
    if not isinstance(value["output_exists"], bool):
        raise ReviewContractError("lifecycle session failure output state is invalid")
    if value["failure_class"] not in SESSION_FAILURE_CLASSES:
        raise ReviewContractError("lifecycle session failure class is unsupported")
    stage = value["validation_stage"]
    if stage is not None and stage not in SESSION_FAILURE_VALIDATION_STAGES:
        raise ReviewContractError("lifecycle session failure validation stage is unsupported")
    code = value["diagnostic_code"]
    if code is not None and code not in SESSION_FAILURE_DIAGNOSTIC_CODES:
        raise ReviewContractError("lifecycle session failure diagnostic is unsupported")
    detail = value["diagnostic_detail_code"]
    if detail is not None and detail not in SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES:
        raise ReviewContractError("lifecycle session failure detail is unsupported")
    return dict(value)


def validate_lifecycle_artifact(value: object) -> dict[str, object]:
    """Validate the one persisted outcome and, when needed, continuation input."""
    if not isinstance(value, Mapping) or set(value) != _ARTIFACT_FIELDS:
        raise ReviewContractError("lifecycle artifact has unsupported or missing fields")
    if value["schema"] != LIFECYCLE_ARTIFACT_SCHEMA:
        raise ReviewContractError("lifecycle artifact schema is unsupported")
    status = value["status"]
    if status not in _STATUSES:
        raise ReviewContractError("lifecycle artifact status is unsupported")
    revision = _digest(value["issue_contract_revision"], "issue contract revision")
    risk = _risk(value["risk"])
    try:
        retry_budget = correction_retry_budget(risk)
    except ValueError as exc:
        raise ReviewContractError(str(exc)) from exc
    cycle = value["cycle"]
    if (
        not isinstance(cycle, int)
        or isinstance(cycle, bool)
        or cycle < 0
        or cycle > retry_budget
    ):
        raise ReviewContractError(
            "lifecycle artifact cycle is outside the configured correction "
            f"retry budget for risk:{risk} ({retry_budget})"
        )
    identity = _identity(value["candidate_identity"], "lifecycle candidate identity")
    history_value = value["prior_candidate_identities"]
    if not isinstance(history_value, list):
        raise ReviewContractError("lifecycle prior candidates must be a list")
    history = [
        _identity(item, f"lifecycle prior candidates[{index}]")
        for index, item in enumerate(history_value)
    ]
    keys = [_content_key(identity) for identity in history]
    if len(keys) != len(set(keys)):
        raise ReviewContractError("lifecycle prior candidates contain a repeated candidate")
    current_key = _content_key(identity)
    corrections = _corrections(value["corrections"])
    reason_value = value["reason"]
    failure = _session_failure(value["session_failure"])
    if status == "revalidate-and-rereview":
        if (
            cycle < 1
            or len(history) != cycle - 1
            or current_key in set(keys)
            or not corrections
            or reason_value is not None
            or failure is not None
        ):
            raise ReviewContractError("continuation artifact is incomplete")
        reason = None
    elif status == "complete":
        if (
            len(history) != cycle
            or current_key in set(keys)
            or corrections
            or reason_value is not None
            or failure is not None
        ):
            raise ReviewContractError("completed artifact is inconsistent")
        reason = None
    else:
        if len(history) != cycle or corrections:
            raise ReviewContractError("human handoff artifact is inconsistent")
        reason = _reason(reason_value)
    return {
        "schema": LIFECYCLE_ARTIFACT_SCHEMA,
        "status": status,
        "risk": risk,
        "issue_contract_revision": revision,
        "cycle": cycle,
        "candidate_identity": identity,
        "prior_candidate_identities": history,
        "corrections": corrections,
        "reason": reason,
        "session_failure": failure,
    }


def lifecycle_artifact(
    *,
    status: str,
    risk: str,
    issue_contract_revision: str,
    cycle: int,
    candidate_identity: Mapping[str, object],
    prior_candidate_identities: Sequence[Mapping[str, object]] = (),
    corrections: Sequence[Mapping[str, object]] = (),
    reason: str | None = None,
    session_failure: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the canonical persisted result without synchronized projections."""
    return validate_lifecycle_artifact(
        {
            "schema": LIFECYCLE_ARTIFACT_SCHEMA,
            "status": status,
            "risk": risk,
            "issue_contract_revision": issue_contract_revision,
            "cycle": cycle,
            "candidate_identity": dict(candidate_identity),
            "prior_candidate_identities": [
                dict(item) for item in prior_candidate_identities
            ],
            "corrections": [dict(item) for item in corrections],
            "reason": reason,
            "session_failure": (
                None if session_failure is None else dict(session_failure)
            ),
        }
    )


def load_lifecycle_artifact(value: object) -> dict[str, object]:
    """Load the same artifact emitted as the result of a prior review cycle."""
    return validate_lifecycle_artifact(value)


def continuation_reason(
    artifact: Mapping[str, object],
    *,
    issue_contract_revision: str,
    candidate: Mapping[str, object],
    risk: str,
) -> str | None:
    """Reject stale, unchanged, repeated, or non-continuation candidates."""
    continuation = validate_lifecycle_artifact(artifact)
    if continuation["status"] != "revalidate-and-rereview":
        return "saved lifecycle does not require another correction cycle"
    current_risk = _risk(risk)
    if continuation["risk"] != current_risk:
        return (
            "continuation artifact uses a different risk tier; a fresh "
            "human-authorized lifecycle is required"
        )
    if continuation["issue_contract_revision"] != _digest(
        issue_contract_revision, "issue contract revision"
    ):
        return "continuation artifact belongs to a different issue contract revision"
    history = continuation["prior_candidate_identities"]
    current = candidate_identity(candidate)
    current_key = _content_key(current)
    previous_key = _content_key(continuation["candidate_identity"])
    if current_key == previous_key:
        return "the continuation candidate did not change the reviewed candidate"
    if current_key in {_content_key(item) for item in history}:
        return "candidate correction oscillated to an earlier identity"
    return None


def accepted_corrections(adjudication: Mapping[str, object]) -> list[dict[str, object]]:
    """Project only validated, accepted remediation into the canonical artifact."""
    return [
        {
            "finding_id": item["finding_id"],
            "disposition": item["disposition"],
            "basis": item["basis"],
            "correction": item["correction"],
        }
        for item in adjudication["dispositions"]
        if item["correction_accepted"]
    ]
