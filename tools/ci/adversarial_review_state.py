"""Persist the single validated result and continuation input for review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

try:
    from .adversarial_review import _digest, candidate_identity
    from .adversarial_review_contracts import (
        DISPOSITIONS,
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
        DISPOSITIONS,
        RISK_TIERS,
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_DIAGNOSTIC_CODES,
        SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES,
        SESSION_FAILURE_SCHEMA,
        SESSION_FAILURE_VALIDATION_STAGES,
        ReviewContractError,
    )
    from pr_policy import correction_retry_budget  # type: ignore[no-redef]


LIFECYCLE_ARTIFACT_SCHEMA = "adversarial-review-lifecycle:v3"
MAX_HANDOFF_REASON_LENGTH = 320
MAX_REVIEW_SUMMARY_LENGTH = 640
MAX_ADJUDICATION_BASIS_LENGTH = 1000
_ARTIFACT_FIELDS = {
    "schema",
    "status",
    "risk",
    "issue_contract_revision",
    "cycle",
    "candidate_identity",
    "prior_candidate_identities",
    "review_cycles",
    "reason",
    "session_failure",
}
_IDENTITY_FIELDS = ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256")
_CONTENT_FIELDS = ("tree_sha", "diff_sha256")
_REVIEW_CYCLE_FIELDS = {
    "cycle",
    "candidate_identity",
    "adjudication_status",
    "findings",
}
_REVIEW_FINDING_FIELDS = {"finding_id", "summary", "disposition", "basis"}
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


def _compact_text(value: object, subject: str, limit: int) -> str:
    text = _text(value, subject)
    normalized = " ".join(
        "".join(char if char.isprintable() else " " for char in text).split()
    )
    if not normalized:
        raise ReviewContractError(f"{subject} is empty after sanitizing")
    if len(normalized) > limit:
        normalized = normalized[:limit].rstrip()
    return normalized


def _review_cycles(value: object, retry_budget: int) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ReviewContractError("lifecycle review_cycles must be a list")
    if len(value) > retry_budget + 1:
        raise ReviewContractError("lifecycle review cycles exceed the retry budget")
    cycles: list[dict[str, object]] = []
    for index, raw in enumerate(value):
        subject = f"lifecycle review_cycles[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _REVIEW_CYCLE_FIELDS:
            raise ReviewContractError(f"{subject} has unsupported or missing fields")
        cycle = raw["cycle"]
        if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle != index:
            raise ReviewContractError(f"{subject}.cycle is not contiguous")
        identity = _identity(raw["candidate_identity"], f"{subject}.candidate_identity")
        adjudication_status = raw["adjudication_status"]
        if adjudication_status not in {"not-needed", "complete", "unavailable"}:
            raise ReviewContractError(f"{subject}.adjudication_status is unsupported")
        raw_findings = raw["findings"]
        if not isinstance(raw_findings, list):
            raise ReviewContractError(f"{subject}.findings must be a list")
        findings: list[dict[str, object]] = []
        seen: set[str] = set()
        for finding_index, raw_finding in enumerate(raw_findings):
            finding_subject = f"{subject}.findings[{finding_index}]"
            if (
                not isinstance(raw_finding, Mapping)
                or set(raw_finding) != _REVIEW_FINDING_FIELDS
            ):
                raise ReviewContractError(
                    f"{finding_subject} has unsupported or missing fields"
                )
            finding_id = _text(raw_finding["finding_id"], f"{finding_subject}.finding_id")
            if finding_id in seen:
                raise ReviewContractError(f"{subject} contains a duplicate finding")
            seen.add(finding_id)
            disposition = raw_finding["disposition"]
            basis = raw_finding["basis"]
            if disposition is None:
                if basis is not None:
                    raise ReviewContractError(
                        f"{finding_subject}.basis requires an adjudicated disposition"
                    )
                normalized_basis = None
            else:
                if disposition not in DISPOSITIONS:
                    raise ReviewContractError(
                        f"{finding_subject}.disposition is unsupported"
                    )
                normalized_basis = _compact_text(
                    basis, f"{finding_subject}.basis", MAX_ADJUDICATION_BASIS_LENGTH
                )
            findings.append(
                {
                    "finding_id": finding_id,
                    "summary": _compact_text(
                        raw_finding["summary"],
                        f"{finding_subject}.summary",
                        MAX_REVIEW_SUMMARY_LENGTH,
                    ),
                    "disposition": disposition,
                    "basis": normalized_basis,
                }
            )
        if adjudication_status == "not-needed" and findings:
            raise ReviewContractError(
                f"{subject} cannot have findings when adjudication was not needed"
            )
        if adjudication_status in {"complete", "unavailable"} and not findings:
            raise ReviewContractError(
                f"{subject} requires reviewer findings for its adjudication status"
            )
        if adjudication_status == "complete" and any(
            finding["disposition"] is None for finding in findings
        ):
            raise ReviewContractError(f"{subject} has an incomplete adjudication")
        if adjudication_status == "unavailable" and any(
            finding["disposition"] is not None for finding in findings
        ):
            raise ReviewContractError(
                f"{subject} cannot assign dispositions when adjudication is unavailable"
            )
        cycles.append(
            {
                "cycle": index,
                "candidate_identity": identity,
                "adjudication_status": adjudication_status,
                "findings": findings,
            }
        )
    return cycles


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
    review_cycles = _review_cycles(value["review_cycles"], retry_budget)
    unavailable_cycles = [
        index
        for index, review_cycle in enumerate(review_cycles)
        if review_cycle["adjudication_status"] == "unavailable"
    ]
    reason_value = value["reason"]
    failure = _session_failure(value["session_failure"])
    if unavailable_cycles and (
        status != "human-handoff"
        or failure is None
        or failure["role"] != "adjudicator"
        or unavailable_cycles != [len(review_cycles) - 1]
    ):
        raise ReviewContractError(
            "unadjudicated findings require the current adjudicator failure handoff"
        )
    if status == "revalidate-and-rereview":
        if (
            cycle < 1
            or len(history) != cycle - 1
            or current_key in set(keys)
            or len(review_cycles) != cycle
            or reason_value is not None
            or failure is not None
        ):
            raise ReviewContractError("continuation artifact is incomplete")
        if review_cycles[-1]["candidate_identity"] != identity:
            raise ReviewContractError("continuation candidate does not match its review outcome")
        if [item["candidate_identity"] for item in review_cycles[:-1]] != history:
            raise ReviewContractError("continuation history does not match prior review outcomes")
        if not has_actionable_findings(review_cycles[-1]):
            raise ReviewContractError("continuation has no current actionable disposition")
        reason = None
    elif status == "complete":
        if (
            len(history) != cycle
            or current_key in set(keys)
            or len(review_cycles) != cycle + 1
            or reason_value is not None
            or failure is not None
        ):
            raise ReviewContractError("completed artifact is inconsistent")
        if review_cycles[-1]["candidate_identity"] != identity:
            raise ReviewContractError("completed candidate does not match its review outcome")
        if [item["candidate_identity"] for item in review_cycles[:-1]] != history:
            raise ReviewContractError("completed history does not match prior review outcomes")
        if has_actionable_findings(review_cycles[-1]):
            raise ReviewContractError("completed artifact has a current actionable disposition")
        reason = None
    else:
        if len(history) != cycle or len(review_cycles) not in {cycle, cycle + 1}:
            raise ReviewContractError("human handoff artifact is inconsistent")
        reason = _reason(reason_value)
        if [item["candidate_identity"] for item in review_cycles[:cycle]] != history:
            raise ReviewContractError("handoff history does not match prior review outcomes")
        if len(review_cycles) == cycle + 1 and review_cycles[-1]["candidate_identity"] != identity:
            raise ReviewContractError("handoff candidate does not match its review outcome")
        failure_role = None if failure is None else failure["role"]
        if failure_role == "reviewer" and len(review_cycles) != cycle:
            raise ReviewContractError("reviewer failure cannot include an unvalidated review")
        if failure_role == "adjudicator" and (
            len(review_cycles) != cycle + 1
            or review_cycles[-1]["adjudication_status"] != "unavailable"
        ):
            raise ReviewContractError(
                "adjudicator failure must preserve its validated reviewer findings"
            )
        if failure is None and review_cycles and (
            review_cycles[-1]["adjudication_status"] == "unavailable"
        ):
            raise ReviewContractError(
                "unadjudicated reviewer findings require an adjudicator failure"
            )
    return {
        "schema": LIFECYCLE_ARTIFACT_SCHEMA,
        "status": status,
        "risk": risk,
        "issue_contract_revision": revision,
        "cycle": cycle,
        "candidate_identity": identity,
        "prior_candidate_identities": history,
        "review_cycles": review_cycles,
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
    review_cycles: Sequence[Mapping[str, object]] = (),
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
            "review_cycles": [dict(item) for item in review_cycles],
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


def has_actionable_findings(review_cycle: Mapping[str, object]) -> bool:
    """Only current-cycle blocker and patch-now findings require a new candidate."""
    findings = review_cycle.get("findings", [])
    return any(
        isinstance(item, Mapping) and item.get("disposition") in {"blocker", "patch-now"}
        for item in findings
    )
