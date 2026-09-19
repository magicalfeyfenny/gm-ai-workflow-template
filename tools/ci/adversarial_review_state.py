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
_LIFECYCLE_STATE_FIELDS = (
    "cycle",
    "candidate_changed",
    "accepted_correction",
    "expected_candidate",
    "previous_candidates",
    "issue_contract_revision",
)


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


def validate_lifecycle_state(value: Mapping[str, object] | None = None) -> dict:
    """Validate the small state handoff consumed by the production CLI route."""
    raw = {} if value is None else dict(value)
    unexpected = sorted(set(raw) - set(_LIFECYCLE_STATE_FIELDS))
    if unexpected:
        raise ReviewContractError(
            "review lifecycle state has unsupported fields: " + ", ".join(unexpected)
        )
    cycle = raw.get("cycle", 0)
    if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle < 0:
        raise ReviewContractError("review lifecycle state cycle must be nonnegative")
    candidate_changed = raw.get("candidate_changed", False)
    accepted_correction = raw.get("accepted_correction", False)
    if not isinstance(candidate_changed, bool):
        raise ReviewContractError("review lifecycle state candidate_changed must be boolean")
    if not isinstance(accepted_correction, bool):
        raise ReviewContractError(
            "review lifecycle state accepted_correction must be boolean"
        )
    expected_value = raw.get("expected_candidate")
    expected = None if expected_value is None else candidate_identity(expected_value)
    previous_value = raw.get("previous_candidates", [])
    if not isinstance(previous_value, list):
        raise ReviewContractError(
            "review lifecycle state previous_candidates must be a list"
        )
    previous = [candidate_identity(item) for item in previous_value]
    revision_value = raw.get("issue_contract_revision")
    revision = (
        None
        if revision_value is None
        else _digest(revision_value, "review lifecycle state issue_contract_revision")
    )
    if accepted_correction and expected is None:
        raise ReviewContractError(
            "an accepted correction needs an expected exact candidate identity"
        )
    return {
        "cycle": cycle,
        "candidate_changed": candidate_changed,
        "accepted_correction": accepted_correction,
        "expected_candidate": expected,
        "previous_candidates": previous,
        "issue_contract_revision": revision,
    }


def review_lifecycle_decision(
    result: Mapping[str, object],
    review_packet: Mapping[str, object],
    adjudication_packet: Mapping[str, object],
    *,
    state: Mapping[str, object] | None = None,
) -> dict:
    """Apply the deterministic transition to the production review outcome."""
    lifecycle = validate_lifecycle_state(state)
    validated_review = validate_review_packet(review_packet)
    adjudication = validate_adjudication_result(result, adjudication_packet)
    if not stage2_evidence_current(
        validated_review,
        validated_review["candidate"],
        lifecycle["issue_contract_revision"],
    ):
        return {
            "status": "revalidate",
            "cycle": lifecycle["cycle"],
            "corrections": [],
            "reason": "Stage 2 evidence is stale or uses a different issue revision",
            "requirements": ["fresh Stage 2 evidence", "fresh exact candidate"],
        }
    current_identity = candidate_identity(validated_review["candidate"])
    if lifecycle["accepted_correction"]:
        if lifecycle["expected_candidate"] != current_identity:
            return {
                "status": "revalidate",
                "cycle": lifecycle["cycle"],
                "corrections": [],
                "reason": "the reviewed candidate does not match the expected correction candidate",
                "requirements": ["establish the exact corrected candidate identity"],
            }
        if not lifecycle["candidate_changed"]:
            return review_loop_decision(
                adjudication,
                adjudication_packet,
                cycle=lifecycle["cycle"],
                candidate_changed=False,
                next_candidate=current_identity,
                previous_candidates=lifecycle["previous_candidates"],
            )
        if _content_key(current_identity) in {
            _content_key(candidate) for candidate in lifecycle["previous_candidates"]
        }:
            return {
                "status": "human-handoff",
                "cycle": lifecycle["cycle"],
                "corrections": [],
                "reason": "candidate correction oscillated to an earlier identity",
                "requirements": [],
            }
    elif lifecycle["candidate_changed"]:
        return review_loop_decision(
            adjudication,
            adjudication_packet,
            cycle=lifecycle["cycle"],
            candidate_changed=True,
            next_candidate=current_identity,
            previous_candidates=lifecycle["previous_candidates"],
        )
    elif lifecycle["expected_candidate"] is not None:
        return {
            "status": "human-handoff",
            "cycle": lifecycle["cycle"],
            "corrections": [],
            "reason": "an expected corrected candidate was supplied without an accepted correction",
            "requirements": [],
        }

    if adjudication["human_handoff"]["required"]:
        return {
            "status": "human-handoff",
            "cycle": lifecycle["cycle"],
            "corrections": [],
            "reason": adjudication["human_handoff"]["reason"],
            "requirements": [],
        }
    corrections = [
        item["correction"]
        for item in adjudication["dispositions"]
        if item["correction_accepted"]
    ]
    if not corrections:
        return review_loop_decision(
            adjudication,
            adjudication_packet,
            cycle=lifecycle["cycle"],
            candidate_changed=False,
        )
    if lifecycle["cycle"] >= MAX_CORRECTION_CYCLES:
        return {
            "status": "human-handoff",
            "cycle": lifecycle["cycle"],
            "corrections": [],
            "reason": f"correction cycle cap {MAX_CORRECTION_CYCLES} reached",
            "requirements": [],
        }
    return {
        "status": "revalidate-and-rereview",
        "cycle": lifecycle["cycle"],
        "next_cycle": lifecycle["cycle"] + 1,
        "corrections": corrections,
        "reason": None,
        "requirements": [
            "apply only the accepted corrections",
            "establish a new exact candidate identity",
            "run fresh Stage 2 evidence",
            "run fresh reviewer and adjudicator sessions",
        ],
    }
