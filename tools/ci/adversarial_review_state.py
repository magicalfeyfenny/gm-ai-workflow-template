"""Bound correction and evidence transitions for adversarial review."""

from __future__ import annotations

import hashlib
import json
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
    from .adversarial_review_lifecycle_artifact import (
        CONTINUATION_STATE_SCHEMA,
        implementation_action_body,
        history_after_success,
        history_at_handoff,
        recover_implementation_payload,
        validate_adjudication_history,
        validate_pending_implementation_action,
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
    from adversarial_review_lifecycle_artifact import (  # type: ignore[no-redef]
        CONTINUATION_STATE_SCHEMA,
        implementation_action_body,
        history_after_success,
        history_at_handoff,
        recover_implementation_payload,
        validate_adjudication_history,
        validate_pending_implementation_action,
    )


_CONTENT_FIELDS = ("tree_sha", "diff_sha256")
_CANDIDATE_IDENTITY_FIELDS = (
    "base_ref",
    "head_ref",
    "head_sha",
    "tree_sha",
    "diff_sha256",
)
_CONTINUATION_STATE_FIELDS = (
    "schema",
    "state_digest",
    "cycle",
    "candidate_history",
    "accepted_correction",
    "previous_candidate",
    "authorized_locations",
    "issue_contract_revision",
    "adjudication_history",
    "pending_implementation_action",
)


def _content_key(value: Mapping[str, object]) -> tuple[str, ...]:
    identity = candidate_identity(value)
    return tuple(identity[field] for field in _CONTENT_FIELDS)


def _canonical_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identity_snapshot(value: object, subject: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(_CANDIDATE_IDENTITY_FIELDS):
        raise ReviewContractError(
            f"{subject} must contain exactly the candidate identity fields"
        )
    return candidate_identity(value)


def _candidate_snapshot(value: object, subject: str = "candidate") -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ReviewContractError(f"{subject} must be an object")
    if set(value) != set(_CANDIDATE_IDENTITY_FIELDS) | {"diff"}:
        raise ReviewContractError(
            f"{subject} must contain exactly its identity fields and diff"
        )
    identity = candidate_identity(value)
    diff = value.get("diff")
    if not isinstance(diff, str):
        raise ReviewContractError(f"{subject}.diff must be a string")
    return {**identity, "diff": diff}


def _path_list(value: object, subject: str) -> list[str]:
    if not isinstance(value, list):
        raise ReviewContractError(f"{subject} must be a list")
    paths: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or item.startswith("/"):
            raise ReviewContractError(f"{subject} contains an invalid repository path")
        parts = item.split("/")
        if ".." in parts or "" in parts or "\\" in item:
            raise ReviewContractError(f"{subject} contains an invalid repository path")
        paths.append(item)
    return paths


def _initial_lifecycle_state(issue_contract_revision: str) -> dict[str, object]:
    return {
        "cycle": 0,
        "candidate_history": [],
        "accepted_correction": False,
        "previous_candidate": None,
        "authorized_locations": [],
        "issue_contract_revision": _digest(
            issue_contract_revision, "issue contract revision"
        ),
        "adjudication_history": [],
        "pending_implementation_action": None,
    }


def initial_lifecycle_state(issue_contract_revision: str) -> dict[str, object]:
    """Return the internal, explicitly requested first-candidate state."""
    return _initial_lifecycle_state(issue_contract_revision)


def _state_body(
    *,
    cycle: int,
    candidate_history: list[dict[str, str]],
    accepted_correction: bool,
    previous_candidate: dict[str, object],
    authorized_locations: list[str],
    issue_contract_revision: str,
    adjudication_history: list[dict[str, object]],
    pending_implementation_action: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": CONTINUATION_STATE_SCHEMA,
        "cycle": cycle,
        "candidate_history": candidate_history,
        "accepted_correction": accepted_correction,
        "previous_candidate": previous_candidate,
        "authorized_locations": authorized_locations,
        "issue_contract_revision": issue_contract_revision,
        "adjudication_history": adjudication_history,
        "pending_implementation_action": pending_implementation_action,
    }


def validate_continuation_state(value: Mapping[str, object]) -> dict[str, object]:
    """Validate the complete repository-defined state for a correction cycle."""
    if not isinstance(value, Mapping):
        raise ReviewContractError("continuation state must be an object")
    raw = dict(value)
    if set(raw) != set(_CONTINUATION_STATE_FIELDS):
        raise ReviewContractError(
            "continuation state must be complete and contain only repository-defined fields"
        )
    if raw.get("schema") != CONTINUATION_STATE_SCHEMA:
        raise ReviewContractError("unsupported continuation state schema")
    cycle = raw.get("cycle")
    if (
        not isinstance(cycle, int)
        or isinstance(cycle, bool)
        or cycle < 1
        or cycle > MAX_CORRECTION_CYCLES
    ):
        raise ReviewContractError("continuation state cycle is outside the correction cap")
    if raw.get("accepted_correction") is not True:
        raise ReviewContractError(
            "continuation state must record an accepted correction"
        )
    revision = _digest(raw.get("issue_contract_revision"), "issue contract revision")
    history_value = raw.get("candidate_history")
    if not isinstance(history_value, list) or not history_value:
        raise ReviewContractError("continuation state candidate history is incomplete")
    history = [
        _identity_snapshot(item, "continuation state candidate history entry")
        for item in history_value
    ]
    if len(history) != cycle:
        raise ReviewContractError("continuation state history does not match its cycle")
    history_keys = [_content_key(item) for item in history]
    if len(history_keys) != len(set(history_keys)):
        raise ReviewContractError("continuation state candidate history contains a duplicate")
    previous = _candidate_snapshot(
        raw.get("previous_candidate"), "continuation state previous candidate"
    )
    if candidate_identity(previous) != history[-1]:
        raise ReviewContractError(
            "continuation state previous candidate does not match its history"
        )
    authorized = _path_list(
        raw.get("authorized_locations"), "continuation state authorized_locations"
    )
    if authorized != sorted(set(authorized)):
        raise ReviewContractError(
            "continuation state authorized_locations must be unique and sorted"
        )
    adjudication_history = validate_adjudication_history(
        raw.get("adjudication_history"), history, cycle
    )
    pending_action, expected_locations = validate_pending_implementation_action(
        raw.get("pending_implementation_action"), adjudication_history, revision, cycle
    )
    if authorized != expected_locations:
        raise ReviewContractError("continuation state authorized locations differ from its action")
    body = _state_body(
        cycle=cycle,
        candidate_history=history,
        accepted_correction=True,
        previous_candidate=previous,
        authorized_locations=authorized,
        issue_contract_revision=revision,
        adjudication_history=adjudication_history,
        pending_implementation_action=pending_action,
    )
    state_digest = raw.get("state_digest")
    if not isinstance(state_digest, str) or state_digest != _canonical_digest(body):
        raise ReviewContractError("continuation state digest does not match its contents")
    return {**body, "state_digest": state_digest}


def _accepted_corrections(adjudication: Mapping[str, object]) -> list[dict[str, object]]:
    corrections: list[dict[str, object]] = []
    for item in adjudication["dispositions"]:
        if item["correction_accepted"]:
            correction = item["correction"]
            if not isinstance(correction, Mapping):
                raise ReviewContractError("accepted correction is not an object")
            corrections.append(dict(correction))
    return corrections


def _diff_path(line: str, prefix: str) -> str | None:
    value = line[len(prefix) :].rstrip("\r\n")
    value = value.split("\t", 1)[0]
    if value == "/dev/null":
        return None
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value


def _diff_sections(diff: str) -> dict[str, str]:
    """Parse only the candidate's supplied patch; never consult live Git state."""
    lines = diff.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith("diff --git ")]
    if not starts:
        raise ReviewContractError("candidate diff has no parseable file sections")
    sections: dict[str, str] = {}
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        section = "".join(lines[start:end])
        header = lines[start].rstrip("\r\n")
        pair = header[len("diff --git") :].strip().split(" b/", 1)
        if len(pair) != 2 or not pair[0].startswith("a/") or not pair[1]:
            raise ReviewContractError("candidate diff has an invalid file header")
        paths = {pair[0][2:], pair[1]}
        for line in lines[start:end]:
            if line.startswith("--- "):
                path = _diff_path(line, "--- ")
                if path is not None:
                    paths.add(path)
            elif line.startswith("+++ "):
                path = _diff_path(line, "+++ ")
                if path is not None:
                    paths.add(path)
            elif line.startswith("rename from "):
                paths.add(line[len("rename from ") :].rstrip("\r\n"))
            elif line.startswith("rename to "):
                paths.add(line[len("rename to ") :].rstrip("\r\n"))
        for path in paths:
            if not path or path.startswith("/") or "\\" in path:
                raise ReviewContractError("candidate diff contains an invalid repository path")
            if ".." in path.split("/"):
                raise ReviewContractError("candidate diff contains a parent path")
            sections[path] = sections.get(path, "") + section
    return sections


def changed_candidate_paths(
    previous_candidate: Mapping[str, object], current_candidate: Mapping[str, object]
) -> list[str]:
    """Return paths whose supplied patch sections changed between candidates."""
    previous = _candidate_snapshot(previous_candidate, "previous candidate")
    current = _candidate_snapshot(current_candidate, "current candidate")
    previous_sections = _diff_sections(previous["diff"])
    current_sections = _diff_sections(current["diff"])
    return sorted(
        path
        for path in set(previous_sections) | set(current_sections)
        if previous_sections.get(path) != current_sections.get(path)
    )


def continuation_delta_reason(
    state: Mapping[str, object],
    current_candidate: Mapping[str, object],
    issue_contract_revision: str,
) -> str | None:
    """Return a fail-closed reason when a candidate escapes accepted locations."""
    continuation = validate_continuation_state(state)
    revision = _digest(issue_contract_revision, "issue contract revision")
    if continuation["issue_contract_revision"] != revision:
        return "continuation state belongs to a different issue contract revision"
    current = _candidate_snapshot(current_candidate, "current candidate")
    previous = continuation["previous_candidate"]
    if _content_key(current) == _content_key(previous):
        return "the continuation candidate did not change the reviewed candidate"
    history = {
        _content_key(candidate) for candidate in continuation["candidate_history"]
    }
    if _content_key(current) in history:
        return "candidate correction oscillated to an earlier identity"
    try:
        changed_paths = changed_candidate_paths(previous, current)
    except ReviewContractError:
        return "the candidate delta could not be determined safely"
    if not changed_paths:
        return "the continuation candidate changed identity without changing a repository path"
    unauthorized = sorted(
        set(changed_paths) - set(continuation["authorized_locations"])
    )
    if unauthorized:
        return (
            "the corrected candidate changes paths outside accepted correction locations: "
            + ", ".join(unauthorized)
        )
    return None


def build_continuation_state(
    lifecycle: Mapping[str, object],
    current_candidate: Mapping[str, object],
    adjudication: Mapping[str, object],
    transition: Mapping[str, object],
    issue_contract_revision: str,
    adjudication_history: list[dict[str, object]],
) -> dict[str, object]:
    """Build a complete repository-defined state for the next production run."""
    corrections = _accepted_corrections(adjudication)
    if not corrections:
        raise ReviewContractError(
            "cannot emit continuation state without an accepted correction"
        )
    cycle = transition.get("next_cycle")
    if not isinstance(cycle, int) or cycle < 1 or cycle > MAX_CORRECTION_CYCLES:
        raise ReviewContractError("continuation state next cycle exceeds the correction cap")
    current = _candidate_snapshot(current_candidate, "current candidate")
    current_identity = candidate_identity(current)
    prior_history = list(lifecycle.get("candidate_history", []))
    history = [dict(item) for item in prior_history]
    if not history or _content_key(history[-1]) != _content_key(current_identity):
        history.append(current_identity)
    locations: set[str] = set()
    for correction in corrections:
        correction_locations = correction.get("locations")
        locations.update(
            _path_list(correction_locations, "accepted correction locations")
        )
    pending_action = implementation_action_body(
        current,
        adjudication,
        issue_contract_revision,
        cycle,
    )
    body = _state_body(
        cycle=cycle,
        candidate_history=history,
        accepted_correction=True,
        previous_candidate=current,
        authorized_locations=sorted(locations),
        issue_contract_revision=_digest(
            issue_contract_revision, "issue contract revision"
        ),
        adjudication_history=adjudication_history,
        pending_implementation_action=pending_action,
    )
    state = {**body, "state_digest": _canonical_digest(body)}
    return validate_continuation_state(state)


def implementation_payload_from_state(
    state: Mapping[str, object],
) -> dict[str, object]:
    """Build the immediately consumable action envelope from persisted state."""
    validated = validate_continuation_state(state)
    return {
        **validated["pending_implementation_action"],
        "continuation_state_digest": validated["state_digest"],
    }


def load_continuation_state(value: object) -> dict[str, object]:
    """Load a raw state or recover one from its complete saved outcome artifact."""
    if isinstance(value, Mapping) and value.get("schema") == "adversarial-review-outcome:v2":
        recover_implementation_payload(value)
        state = value.get("continuation_state")
    else:
        state = value
    if not isinstance(state, Mapping):
        raise ReviewContractError("continuation artifact must be an object")
    return validate_continuation_state(state)


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


def validate_lifecycle_state(
    value: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Compatibility name for strict continuation-state validation."""
    if value is None:
        raise ReviewContractError(
            "continuation state is required; explicitly request the initial lifecycle"
        )
    return validate_continuation_state(value)


def _handoff_transition(
    cycle: int, reason: str, requirements: list[str] | None = None
) -> dict:
    return {
        "status": "human-handoff",
        "cycle": cycle,
        "corrections": [],
        "reason": reason,
        "requirements": [] if requirements is None else requirements,
        "continuation_state": None,
    }


def review_lifecycle_decision(
    result: Mapping[str, object],
    review_packet: Mapping[str, object],
    adjudication_packet: Mapping[str, object],
    *,
    state: Mapping[str, object] | None = None,
    initial: bool = False,
) -> dict:
    """Apply the deterministic transition to a validated lifecycle state."""
    validated_review = validate_review_packet(review_packet)
    if state is None:
        if not initial:
            raise ReviewContractError(
                "continuation state is required; explicitly request the initial lifecycle"
            )
        lifecycle = _initial_lifecycle_state(
            validated_review["issue_contract"]["revision"]
        )
    else:
        if initial:
            raise ReviewContractError(
                "initial lifecycle cannot also consume continuation state"
            )
        lifecycle = validate_continuation_state(state)
    adjudication = validate_adjudication_result(result, adjudication_packet)
    revision = validated_review["issue_contract"]["revision"]
    if lifecycle["issue_contract_revision"] != revision:
        return _handoff_transition(
            lifecycle["cycle"],
            "continuation state belongs to a different issue contract revision",
            [
                "fresh Stage 2 evidence",
                "fresh complete validated continuation state",
            ],
        )
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
            "continuation_state": None,
        }
    if lifecycle["previous_candidate"] is not None:
        reason = continuation_delta_reason(
            lifecycle, validated_review["candidate"], revision
        )
        if reason is not None:
            return _handoff_transition(lifecycle["cycle"], reason)
    if adjudication["human_handoff"]["required"]:
        transition = _handoff_transition(
            lifecycle["cycle"], adjudication["human_handoff"]["reason"]
        )
        transition["adjudication_history"] = history_at_handoff(
            lifecycle,
            validated_review["candidate"],
            adjudication,
            lifecycle["cycle"],
        )
        transition["implementation_payload"] = None
        return transition
    corrections = _accepted_corrections(adjudication)
    if not corrections:
        history = history_after_success(
            lifecycle,
            validated_review["candidate"],
            adjudication,
            lifecycle["cycle"],
            "no-action",
        )
        return {
            "status": "complete",
            "cycle": lifecycle["cycle"],
            "corrections": [],
            "reason": None,
            "continuation_state": None,
            "implementation_payload": None,
            "adjudication_history": history,
        }
    if lifecycle["cycle"] >= MAX_CORRECTION_CYCLES:
        transition = _handoff_transition(
            lifecycle["cycle"],
            f"correction cycle cap {MAX_CORRECTION_CYCLES} reached",
        )
        transition["implementation_payload"] = None
        transition["adjudication_history"] = history_after_success(
            lifecycle,
            validated_review["candidate"],
            adjudication,
            lifecycle["cycle"],
            "human-handoff",
        )
        return transition
    history = history_after_success(
        lifecycle,
        validated_review["candidate"],
        adjudication,
        lifecycle["cycle"],
        "action-pending",
    )
    transition = {
        "status": "revalidate-and-rereview",
        "cycle": lifecycle["cycle"],
        "next_cycle": lifecycle["cycle"] + 1,
        "corrections": corrections,
        "reason": None,
        "implementation_payload": None,
        "adjudication_history": history,
        "requirements": [
            "apply only the accepted corrections",
            "establish a new exact candidate identity",
            "run fresh Stage 2 evidence",
            "run fresh reviewer and adjudicator sessions",
        ],
        "continuation_state": None,
    }
    transition["continuation_state"] = build_continuation_state(
        lifecycle,
        validated_review["candidate"],
        adjudication,
        transition,
        revision,
        history,
    )
    transition["implementation_payload"] = implementation_payload_from_state(
        transition["continuation_state"]
    )
    return transition
