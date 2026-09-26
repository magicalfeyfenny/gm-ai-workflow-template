"""Apply bounded review outcomes to one candidate lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping

try:
    from .adversarial_review import (
        ReviewContractError,
        ReviewSessionError,
        candidate_identity,
        validate_review_packet,
    )
    from .adversarial_review_failures import session_error, session_failure_diagnostic
    from .adversarial_review_state import (
        continuation_reason,
        has_actionable_findings,
        lifecycle_artifact,
        load_lifecycle_artifact,
    )
    from .pr_policy import correction_retry_budget
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review import (  # type: ignore[no-redef]
        ReviewContractError,
        ReviewSessionError,
        candidate_identity,
        validate_review_packet,
    )
    from adversarial_review_failures import (  # type: ignore[no-redef]
        session_error,
        session_failure_diagnostic,
    )
    from adversarial_review_state import (  # type: ignore[no-redef]
        continuation_reason,
        has_actionable_findings,
        lifecycle_artifact,
        load_lifecycle_artifact,
    )
    from pr_policy import correction_retry_budget  # type: ignore[no-redef]


ReviewSessions = Callable[..., tuple[dict | None, dict | None]]


def _session_failure_outcome(
    review_packet: Mapping[str, object],
    issue_contract_revision: str,
    cycle: int,
    prior_candidate_identities: list[dict[str, str]],
    review_cycles: list[dict[str, object]],
    error: BaseException | None = None,
) -> dict:
    """Return a bounded handoff without exposing unvalidated provider output."""
    if isinstance(error, ReviewSessionError):
        session_failure = session_failure_diagnostic(error)
    else:
        session_failure = session_failure_diagnostic(
            session_error(
                "isolated session returned an invalid result",
                failure_class="invalid-output",
            )
        )
    reason = (
        f"{session_failure['role']} session failed with "
        f"{session_failure['failure_class']}; human disposition is required before rerun"
    )
    validated_findings = getattr(error, "validated_review_findings", None)
    if validated_findings is not None:
        review_cycles = [
            *review_cycles,
            _review_cycle_outcome(
                cycle,
                candidate_identity(review_packet["candidate"]),
                validated_findings,
                None,
            ),
        ]
    return lifecycle_artifact(
        status="human-handoff",
        risk=review_packet["risk"],
        issue_contract_revision=issue_contract_revision,
        cycle=cycle,
        candidate_identity=candidate_identity(review_packet["candidate"]),
        prior_candidate_identities=prior_candidate_identities,
        review_cycles=review_cycles,
        reason=reason,
        session_failure=session_failure,
    )


def _review_cycle_outcome(
    cycle: int,
    identity: Mapping[str, object],
    reviewer_findings: list[Mapping[str, object]],
    adjudication: Mapping[str, object] | None,
) -> dict[str, object]:
    """Project validated results without provider evidence or remedy instructions."""
    if adjudication is None:
        adjudication_status = "not-needed" if not reviewer_findings else "unavailable"
        dispositions: dict[str, Mapping[str, object]] = {}
    else:
        adjudication_status = "complete"
        dispositions = {
            item["finding_id"]: item for item in adjudication["dispositions"]
        }
    findings = []
    for finding in reviewer_findings:
        decision = dispositions.get(finding["finding_id"])
        findings.append(
            {
                "finding_id": finding["finding_id"],
                "summary": finding["defect_or_invariant"],
                "disposition": None if decision is None else decision["disposition"],
                "basis": None if decision is None else decision["basis"],
            }
        )
    return {
        "cycle": cycle,
        "candidate_identity": dict(identity),
        "adjudication_status": adjudication_status,
        "findings": findings,
    }


def _state_failure_outcome(
    review_packet: Mapping[str, object], reason: str
) -> dict:
    """Fail closed when the caller omits or supplies an invalid artifact."""
    return lifecycle_artifact(
        status="human-handoff",
        risk=review_packet["risk"],
        issue_contract_revision=review_packet["issue_contract"]["revision"],
        cycle=0,
        candidate_identity=candidate_identity(review_packet["candidate"]),
        prior_candidate_identities=[],
        reason=reason,
    )


def run_review_lifecycle(
    packet: Mapping[str, object],
    *,
    state: Mapping[str, object] | None = None,
    initial: bool = False,
    review_sessions: ReviewSessions,
    session_runner: Callable[..., Mapping[str, object]] | None = None,
    codex_executable: str = "codex",
) -> dict:
    """Run one bounded review transition and return its only persisted artifact."""
    review_packet = validate_review_packet(packet)
    revision = review_packet["issue_contract"]["revision"]
    current_candidate = candidate_identity(review_packet["candidate"])
    if initial and state is not None:
        return _state_failure_outcome(
            review_packet,
            "an initial run cannot consume a saved lifecycle artifact",
        )
    if state is None:
        if not initial:
            return _state_failure_outcome(
                review_packet,
                "a saved lifecycle artifact is required to continue review",
            )
        continuation = None
        cycle = 0
        prior_candidate_identities: list[dict[str, str]] = []
        review_cycles: list[dict[str, object]] = []
    else:
        try:
            continuation = load_lifecycle_artifact(state)
        except ReviewContractError:
            return _state_failure_outcome(
                review_packet,
                "saved lifecycle artifact is invalid; human disposition is required before rerun",
            )
        if continuation["status"] != "revalidate-and-rereview":
            return _state_failure_outcome(
                review_packet,
                "saved lifecycle artifact does not authorize another correction cycle",
            )
        reason = continuation_reason(
            continuation,
            issue_contract_revision=revision,
            candidate=review_packet["candidate"],
            risk=review_packet["risk"],
        )
        if reason is not None:
            prior = [
                *continuation["prior_candidate_identities"],
                continuation["candidate_identity"],
            ]
            return lifecycle_artifact(
                status="human-handoff",
                risk=continuation["risk"],
                issue_contract_revision=revision,
                cycle=continuation["cycle"],
                candidate_identity=current_candidate,
                prior_candidate_identities=prior,
                review_cycles=continuation["review_cycles"],
                reason=reason,
            )
        cycle = continuation["cycle"]
        prior_candidate_identities = [
            *continuation["prior_candidate_identities"],
            continuation["candidate_identity"],
        ]
        review_cycles = list(continuation["review_cycles"])

    try:
        adjudication, adjudication_packet = review_sessions(
            review_packet,
            session_runner=session_runner,
            codex_executable=codex_executable,
        )
    except (ReviewContractError, ReviewSessionError) as exc:
        return _session_failure_outcome(
            review_packet,
            revision,
            cycle,
            prior_candidate_identities,
            review_cycles,
            exc,
        )

    reviewer_findings = (
        [] if adjudication_packet is None else adjudication_packet["findings"]
    )
    review_cycles = [
        *review_cycles,
        _review_cycle_outcome(
            cycle, current_candidate, reviewer_findings, adjudication
        ),
    ]
    if adjudication is None:
        return lifecycle_artifact(
            status="complete",
            risk=review_packet["risk"],
            issue_contract_revision=revision,
            cycle=cycle,
            candidate_identity=current_candidate,
            prior_candidate_identities=prior_candidate_identities,
            review_cycles=review_cycles,
        )
    if adjudication["human_handoff"]["required"]:
        return lifecycle_artifact(
            status="human-handoff",
            risk=review_packet["risk"],
            issue_contract_revision=revision,
            cycle=cycle,
            candidate_identity=current_candidate,
            prior_candidate_identities=prior_candidate_identities,
            review_cycles=review_cycles,
            reason=adjudication["human_handoff"]["reason"],
        )

    if not has_actionable_findings(review_cycles[-1]):
        return lifecycle_artifact(
            status="complete",
            risk=review_packet["risk"],
            issue_contract_revision=revision,
            cycle=cycle,
            candidate_identity=current_candidate,
            prior_candidate_identities=prior_candidate_identities,
            review_cycles=review_cycles,
        )
    retry_budget = correction_retry_budget(review_packet["risk"])
    if cycle >= retry_budget:
        return lifecycle_artifact(
            status="human-handoff",
            risk=review_packet["risk"],
            issue_contract_revision=revision,
            cycle=cycle,
            candidate_identity=current_candidate,
            prior_candidate_identities=prior_candidate_identities,
            review_cycles=review_cycles,
            reason=(
                f"correction retry budget {retry_budget} for "
                f"risk:{review_packet['risk']} exhausted"
            ),
        )
    return lifecycle_artifact(
        status="revalidate-and-rereview",
        risk=review_packet["risk"],
        issue_contract_revision=revision,
        cycle=cycle + 1,
        candidate_identity=current_candidate,
        prior_candidate_identities=prior_candidate_identities,
        review_cycles=review_cycles,
    )
