"""Bound validated adjudication history and implementation-action artifacts."""

from __future__ import annotations

from collections.abc import Mapping

try:
    from .adversarial_review import DISPOSITIONS, ReviewContractError, _digest, candidate_identity
    from .adversarial_review_contracts import ADJUDICATION_RESULT_SCHEMA
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review import (  # type: ignore[no-redef]
        DISPOSITIONS,
        ReviewContractError,
        _digest,
        candidate_identity,
    )
    from adversarial_review_contracts import (  # type: ignore[no-redef]
        ADJUDICATION_RESULT_SCHEMA,
    )


CONTINUATION_STATE_SCHEMA = "adversarial-review-continuation:v3"
IMPLEMENTATION_ACTION_SCHEMA = "adversarial-review-implementation-action:v2"
MAX_ADJUDICATION_HISTORY_BYTES = 256 * 1024
_IDENTITY_FIELDS = ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256")
_HISTORY_FIELDS = ("candidate_identity", "cycle", "dispositions", "correction_status")
_DISPOSITION_FIELDS = (
    "finding_id",
    "disposition",
    "basis",
    "correction_accepted",
    "correction",
)
_ACTION_FIELDS = (
    "schema",
    "candidate_identity",
    "issue_contract_revision",
    "correction_cycle",
    "corrections",
)
_ACTION_CORRECTION_FIELDS = ("finding_id", "disposition", "basis", "correction")
_CORRECTION_FIELDS = ("summary", "validation")
_HISTORY_STATUSES = (
    "action-pending",
    "next-cycle-adjudicated",
    "no-action",
    "human-handoff",
)


def _identity_snapshot(value: object, subject: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(_IDENTITY_FIELDS):
        raise ReviewContractError(f"{subject} must contain exactly the candidate identity fields")
    return candidate_identity(value)


def _validated_correction(value: object, subject: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(_CORRECTION_FIELDS):
        raise ReviewContractError(f"{subject} must contain exactly the correction fields")
    summary = value.get("summary")
    validation = value.get("validation")
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewContractError(f"{subject}.summary must be a non-empty string")
    if not isinstance(validation, list) or not validation or any(
        not isinstance(item, str) or not item.strip() for item in validation
    ):
        raise ReviewContractError(f"{subject}.validation must be a non-empty string list")
    return {"summary": summary, "validation": list(validation)}


def history_entry(
    candidate: Mapping[str, object],
    adjudication: Mapping[str, object],
    cycle: int,
    correction_status: str,
) -> dict[str, object]:
    """Project validated adjudication into the repository-owned summary schema."""
    return {
        "candidate_identity": candidate_identity(candidate),
        "cycle": cycle,
        "dispositions": [
            {
                "finding_id": item["finding_id"],
                "disposition": item["disposition"],
                "basis": item["basis"],
                "correction_accepted": item["correction_accepted"],
                "correction": item["correction"],
            }
            for item in adjudication["dispositions"]
        ],
        "correction_status": correction_status,
    }


def history_after_success(
    lifecycle: Mapping[str, object],
    candidate: Mapping[str, object],
    adjudication: Mapping[str, object],
    cycle: int,
    correction_status: str,
) -> list[dict[str, object]]:
    history = [dict(item) for item in lifecycle["adjudication_history"]]
    for item in history:
        if item["correction_status"] == "action-pending":
            item["correction_status"] = "next-cycle-adjudicated"
    history.append(history_entry(candidate, adjudication, cycle, correction_status))
    if history_size(history) > MAX_ADJUDICATION_HISTORY_BYTES:
        raise ReviewContractError("adjudication history exceeds its size bound")
    return history


def history_at_handoff(
    lifecycle: Mapping[str, object],
    candidate: Mapping[str, object],
    adjudication: Mapping[str, object],
    cycle: int,
) -> list[dict[str, object]]:
    history = [dict(item) for item in lifecycle["adjudication_history"]]
    for item in history:
        if item["correction_status"] == "action-pending":
            item["correction_status"] = "next-cycle-adjudicated"
    history.append(history_entry(candidate, adjudication, cycle, "human-handoff"))
    if history_size(history) > MAX_ADJUDICATION_HISTORY_BYTES:
        raise ReviewContractError("adjudication history exceeds its size bound")
    return history


def history_size(history: list[dict[str, object]]) -> int:
    import json

    return len(
        json.dumps(history, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def validate_adjudication_history(
    value: object,
    candidate_history: list[dict[str, str]],
    cycle: int,
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) != cycle:
        raise ReviewContractError("continuation state adjudication history is incomplete")
    history: list[dict[str, object]] = []
    for index, raw_entry in enumerate(value):
        subject = f"continuation state adjudication history entry {index}"
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != set(_HISTORY_FIELDS):
            raise ReviewContractError(f"{subject} has unsupported or missing fields")
        identity = _identity_snapshot(
            raw_entry.get("candidate_identity"), f"{subject}.candidate_identity"
        )
        entry_cycle = raw_entry.get("cycle")
        if (
            not isinstance(entry_cycle, int)
            or isinstance(entry_cycle, bool)
            or entry_cycle != index
        ):
            raise ReviewContractError(f"{subject}.cycle is out of sequence")
        if identity != candidate_history[index]:
            raise ReviewContractError(
                "adjudication history candidate does not match lifecycle history"
            )
        status = raw_entry.get("correction_status")
        if status not in _HISTORY_STATUSES:
            raise ReviewContractError(f"{subject}.correction_status is unsupported")
        rows = raw_entry.get("dispositions")
        if not isinstance(rows, list):
            raise ReviewContractError(f"{subject}.dispositions must be a list")
        dispositions: list[dict[str, object]] = []
        finding_ids: set[str] = set()
        has_action = False
        for row_index, raw in enumerate(rows):
            row_subject = f"{subject}.dispositions[{row_index}]"
            if not isinstance(raw, Mapping) or set(raw) != set(_DISPOSITION_FIELDS):
                raise ReviewContractError(f"{row_subject} has unsupported or missing fields")
            finding_id = raw.get("finding_id")
            disposition = raw.get("disposition")
            basis = raw.get("basis")
            accepted = raw.get("correction_accepted")
            if (
                not isinstance(finding_id, str)
                or not finding_id.strip()
                or finding_id in finding_ids
            ):
                raise ReviewContractError(f"{row_subject}.finding_id is invalid or duplicated")
            if disposition not in DISPOSITIONS:
                raise ReviewContractError(f"{row_subject}.disposition is unsupported")
            if (
                not isinstance(basis, str)
                or not basis.strip()
                or not isinstance(accepted, bool)
            ):
                raise ReviewContractError(
                    f"{row_subject} has invalid validated disposition fields"
                )
            correction = raw.get("correction")
            if correction is None:
                if accepted or disposition in {"blocker", "patch-now"}:
                    raise ReviewContractError(f"{row_subject} is missing its accepted correction")
            else:
                correction = _validated_correction(correction, f"{row_subject}.correction")
                if not accepted or disposition not in {"blocker", "patch-now"}:
                    raise ReviewContractError(
                        f"{row_subject} has a correction for a non-action disposition"
                    )
                has_action = True
            finding_ids.add(finding_id)
            dispositions.append(
                {
                    "finding_id": finding_id,
                    "disposition": disposition,
                    "basis": basis,
                    "correction_accepted": accepted,
                    "correction": correction,
                }
            )
        if has_action and status not in {"action-pending", "next-cycle-adjudicated"}:
            raise ReviewContractError(
                f"{subject}.correction_status disagrees with its dispositions"
            )
        if not has_action and status != "no-action":
            raise ReviewContractError(
                f"{subject}.correction_status disagrees with its dispositions"
            )
        expected_status = "action-pending" if has_action and index == cycle - 1 else (
            "next-cycle-adjudicated" if has_action else "no-action"
        )
        if status != expected_status:
            raise ReviewContractError(
                f"{subject}.correction_status is inconsistent with its cycle"
            )
        history.append(
            {
                "candidate_identity": identity,
                "cycle": entry_cycle,
                "dispositions": dispositions,
                "correction_status": status,
            }
        )
    if history_size(history) > MAX_ADJUDICATION_HISTORY_BYTES:
        raise ReviewContractError("continuation state adjudication history exceeds its size bound")
    return history


def implementation_action_body(
    candidate: Mapping[str, object],
    adjudication: Mapping[str, object],
    issue_contract_revision: str,
    correction_cycle: int,
) -> dict[str, object]:
    corrections = [
        {
            "finding_id": item["finding_id"],
            "disposition": item["disposition"],
            "basis": item["basis"],
            "correction": item["correction"],
        }
        for item in adjudication["dispositions"]
        if item["correction_accepted"]
    ]
    if not corrections:
        raise ReviewContractError(
            "cannot create an implementation action without accepted corrections"
        )
    return {
        "schema": IMPLEMENTATION_ACTION_SCHEMA,
        "candidate_identity": candidate_identity(candidate),
        "issue_contract_revision": _digest(issue_contract_revision, "issue contract revision"),
        "correction_cycle": correction_cycle,
        "corrections": corrections,
    }


def validate_pending_implementation_action(
    value: object,
    adjudication_history: list[dict[str, object]],
    issue_contract_revision: str,
    cycle: int,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(_ACTION_FIELDS):
        raise ReviewContractError("continuation state implementation action is incomplete")
    if value.get("schema") != IMPLEMENTATION_ACTION_SCHEMA:
        raise ReviewContractError("continuation state implementation action schema is unsupported")
    identity = _identity_snapshot(
        value.get("candidate_identity"), "implementation action candidate_identity"
    )
    revision = _digest(value.get("issue_contract_revision"), "implementation action issue revision")
    action_cycle = value.get("correction_cycle")
    if (
        identity != adjudication_history[-1]["candidate_identity"]
        or revision != issue_contract_revision
        or not isinstance(action_cycle, int)
        or isinstance(action_cycle, bool)
        or action_cycle != cycle
    ):
        raise ReviewContractError("continuation state implementation action binding is invalid")
    expected = [
        {
            "finding_id": row["finding_id"],
            "disposition": row["disposition"],
            "basis": row["basis"],
            "correction": row["correction"],
        }
        for row in adjudication_history[-1]["dispositions"]
        if row["correction_accepted"]
    ]
    if not expected or value.get("corrections") != expected:
        raise ReviewContractError("implementation action differs from validated adjudication")
    return {
        "schema": IMPLEMENTATION_ACTION_SCHEMA,
        "candidate_identity": identity,
        "issue_contract_revision": revision,
        "correction_cycle": action_cycle,
        "corrections": expected,
    }


def validate_implementation_payload(
    payload: Mapping[str, object], state: Mapping[str, object]
) -> dict[str, object]:
    """Recover only the action bound to a fully validated continuation artifact."""
    try:
        from .adversarial_review_state import validate_continuation_state
    except ImportError:  # pragma: no cover - direct script compatibility
        from adversarial_review_state import validate_continuation_state

    continuation = validate_continuation_state(state)
    if not isinstance(payload, Mapping) or set(payload) != set(_ACTION_FIELDS) | {
        "continuation_state_digest"
    }:
        raise ReviewContractError("implementation payload has unsupported or missing fields")
    if payload.get("continuation_state_digest") != continuation["state_digest"]:
        raise ReviewContractError("implementation payload is not bound to this continuation state")
    expected = {
        **continuation["pending_implementation_action"],
        "continuation_state_digest": continuation["state_digest"],
    }
    if dict(payload) != expected:
        raise ReviewContractError(
            "implementation payload differs from validated continuation state"
        )
    return expected


def _validated_outcome_adjudication_entry(
    outcome: Mapping[str, object], action: Mapping[str, object]
) -> dict[str, object]:
    """Use the separately retained validated adjudication as the action source."""
    adjudication = outcome.get("adjudication")
    expected_fields = {"schema", "candidate_identity", "dispositions", "human_handoff"}
    if not isinstance(adjudication, Mapping) or set(adjudication) != expected_fields:
        raise ReviewContractError("lifecycle outcome is missing its validated adjudication")
    if adjudication.get("schema") != ADJUDICATION_RESULT_SCHEMA:
        raise ReviewContractError("lifecycle outcome adjudication schema is unsupported")
    identity = _identity_snapshot(
        adjudication.get("candidate_identity"),
        "lifecycle outcome adjudication candidate_identity",
    )
    if identity != action.get("candidate_identity"):
        raise ReviewContractError("lifecycle outcome adjudication targets a different candidate")
    handoff = adjudication.get("human_handoff")
    if (
        not isinstance(handoff, Mapping)
        or set(handoff) != {"required", "reason"}
        or handoff.get("required") is not False
        or handoff.get("reason") is not None
    ):
        raise ReviewContractError("lifecycle outcome adjudication is not an actionable result")
    correction_cycle = action.get("correction_cycle")
    if (
        not isinstance(correction_cycle, int)
        or isinstance(correction_cycle, bool)
        or correction_cycle < 1
    ):
        raise ReviewContractError("implementation action correction cycle is invalid")
    try:
        entry = history_entry(
            identity,
            adjudication,
            correction_cycle - 1,
            "action-pending",
        )
    except (KeyError, TypeError) as exc:
        raise ReviewContractError("lifecycle outcome adjudication is incomplete") from exc
    # History validation indexes entries from zero, while a recovered action
    # may refer to a later absolute correction cycle. Validate the isolated
    # entry at index zero, then restore its bound lifecycle index for the
    # comparison with the persisted continuation history.
    validation_entry = {**entry, "cycle": 0}
    validated_entry = validate_adjudication_history(
        [validation_entry], [identity], cycle=1
    )[0]
    validated_entry["cycle"] = correction_cycle - 1
    return validated_entry


def recover_implementation_payload(outcome: Mapping[str, object]) -> dict[str, object]:
    """Extract a validated action from a saved lifecycle outcome artifact."""
    if (
        not isinstance(outcome, Mapping)
        or outcome.get("schema") != "adversarial-review-outcome:v2"
    ):
        raise ReviewContractError("lifecycle outcome schema is unsupported")
    transition = outcome.get("transition")
    if not isinstance(transition, Mapping) or transition.get("status") != "revalidate-and-rereview":
        raise ReviewContractError("lifecycle outcome does not require an implementation action")
    state = outcome.get("continuation_state")
    if not isinstance(state, Mapping):
        raise ReviewContractError("lifecycle outcome is missing its continuation artifact")
    payload = outcome.get("implementation_payload")
    if not isinstance(payload, Mapping):
        raise ReviewContractError("lifecycle outcome is missing its implementation payload")
    action = validate_implementation_payload(payload, state)
    source_entry = _validated_outcome_adjudication_entry(outcome, action)
    state_history = state.get("adjudication_history")
    if (
        not isinstance(state_history, list)
        or not state_history
        or state_history[-1] != source_entry
    ):
        raise ReviewContractError(
            "implementation action differs from the separately validated adjudication"
        )
    if (
        outcome.get("candidate_identity") != action["candidate_identity"]
        or transition.get("next_cycle") != action["correction_cycle"]
        or transition.get("adjudication_history") != state["adjudication_history"]
        or outcome.get("adjudication_history") != state["adjudication_history"]
        or transition.get("implementation_payload") != action
        or transition.get("continuation_state") != state
        or transition.get("corrections")
        != [item["correction"] for item in action["corrections"]]
    ):
        raise ReviewContractError("lifecycle outcome action bindings are inconsistent")
    return action
