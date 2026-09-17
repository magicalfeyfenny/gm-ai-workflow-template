"""Bound the correction and evidence transitions for adversarial review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

try:
    from .adversarial_review import (
        MAX_CORRECTION_CYCLES,
        ReviewContractError,
        _digest,
        candidate_identity,
        validate_adjudication_packet,
        validate_adjudication_result,
        validate_review_packet,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review import (  # type: ignore[no-redef]
        MAX_CORRECTION_CYCLES,
        ReviewContractError,
        _digest,
        candidate_identity,
        validate_adjudication_packet,
        validate_adjudication_result,
        validate_review_packet,
    )


_CONTENT_FIELDS = ("tree_sha", "diff_sha256")


def _content_key(value: Mapping[str, object]) -> tuple[str, ...]:
    identity = candidate_identity(value)
    return tuple(identity[field] for field in _CONTENT_FIELDS)


def review_loop_decision(
    result: Mapping[str, object],
    packet: Mapping[str, object],
    *,
    cycle: int,
    candidate_changed: bool,
    next_candidate: Mapping[str, object] | None = None,
    previous_candidates: Sequence[Mapping[str, object]] = (),
) -> dict:
    """Decide whether to revalidate, complete, or stop for human disposition."""
    if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle < 0:
        raise ReviewContractError("review correction cycle must be a nonnegative integer")
    adjudication_packet = validate_adjudication_packet(packet)
    adjudication = validate_adjudication_result(result, adjudication_packet)
    if adjudication["human_handoff"]["required"]:
        return {
            "status": "human-handoff",
            "cycle": cycle,
            "corrections": [],
            "reason": adjudication["human_handoff"]["reason"],
        }
    corrections = [
        item["correction"]
        for item in adjudication["dispositions"]
        if item["disposition"] in {"blocker", "patch-now"}
        and item["correction"] is not None
    ]
    if not isinstance(candidate_changed, bool):
        raise ReviewContractError("candidate_changed must be boolean")
    if not candidate_changed and next_candidate is not None:
        return {
            "status": "human-handoff",
            "cycle": cycle,
            "corrections": [],
            "reason": "a next candidate was supplied without a candidate change",
        }
    if not corrections:
        if candidate_changed:
            return {
                "status": "human-handoff",
                "cycle": cycle,
                "corrections": [],
                "reason": "candidate changed after review without an accepted correction",
            }
        return {
            "status": "complete",
            "cycle": cycle,
            "corrections": [],
            "reason": None,
        }
    if not candidate_changed:
        return {
            "status": "human-handoff",
            "cycle": cycle,
            "corrections": [],
            "reason": "an accepted correction did not change the candidate",
        }
    if next_candidate is None:
        return {
            "status": "human-handoff",
            "cycle": cycle,
            "corrections": [],
            "reason": "the corrected candidate identity was not established",
        }
    next_key = _content_key(next_candidate)
    history = {_content_key(candidate) for candidate in previous_candidates}
    history.add(_content_key(adjudication_packet["candidate_identity"]))
    if next_key in history:
        return {
            "status": "human-handoff",
            "cycle": cycle,
            "corrections": [],
            "reason": "candidate correction oscillated to an earlier identity",
        }
    if cycle >= MAX_CORRECTION_CYCLES:
        return {
            "status": "human-handoff",
            "cycle": cycle,
            "corrections": [],
            "reason": f"correction cycle cap {MAX_CORRECTION_CYCLES} reached",
        }
    return {
        "status": "revalidate-and-rereview",
        "cycle": cycle + 1,
        "corrections": corrections,
        "reason": None,
    }


def stage2_evidence_current(
    packet: Mapping[str, object],
    candidate: Mapping[str, object],
    issue_contract_revision: str | None = None,
) -> bool:
    """Return whether Stage 2 still binds the unchanged candidate and revision."""
    try:
        validated = validate_review_packet(packet)
        revision = (
            validated["issue_contract"]["revision"]
            if issue_contract_revision is None
            else _digest(issue_contract_revision, "issue contract revision")
        )
        return (
            revision == validated["issue_contract"]["revision"]
            and _content_key(candidate)
            == _content_key(validated["stage2_evidence"]["candidate_identity"])
        )
    except ReviewContractError:
        return False
