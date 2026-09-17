"""Run and validate the bounded adversarial review stage.

The review packet and result contracts live here so a session provider cannot
define governance. The default runner starts two fresh, packet-only Codex
processes in read-only sandboxes; it never resumes or forks an implementation
conversation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence


REVIEW_PACKET_SCHEMA = "adversarial-review-packet:v1"
REVIEW_RESULT_SCHEMA = "adversarial-review-result:v1"
ADJUDICATION_PACKET_SCHEMA = "adversarial-adjudication-packet:v1"
ADJUDICATION_RESULT_SCHEMA = "adversarial-adjudication-result:v1"
MAX_CORRECTION_CYCLES = 2
DISPOSITIONS = ("blocker", "patch-now", "follow-up", "reject")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN_KEYS = frozenset(
    {
        "agent_notes",
        "adjudicator_chain_of_thought",
        "chain_of_thought",
        "conversation",
        "conversation_context",
        "implementation_chain_of_thought",
        "implementation_context",
        "implementation_instructions",
        "model",
        "prompt",
        "provider",
        "reviewer_chain_of_thought",
        "scratchpad",
        "session_history",
        "session_id",
        "instructions",
    }
)


class ReviewContractError(ValueError):
    """Raised when a packet or structured session result is not safe to use."""


class ReviewSessionError(RuntimeError):
    """Raised when an isolated reviewer or adjudicator cannot return a result."""


REVIEW_RESULT_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "candidate_identity", "findings"],
    "properties": {
        "schema": {"const": REVIEW_RESULT_SCHEMA},
        "candidate_identity": {"type": "object"},
        "findings": {"type": "array"},
    },
}

ADJUDICATION_RESULT_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "candidate_identity",
        "dispositions",
        "human_handoff",
    ],
    "properties": {
        "schema": {"const": ADJUDICATION_RESULT_SCHEMA},
        "candidate_identity": {"type": "object"},
        "dispositions": {"type": "array"},
        "human_handoff": {"type": "object"},
    },
}


def _mapping(value: object, subject: str) -> dict:
    if not isinstance(value, Mapping):
        raise ReviewContractError(f"{subject} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ReviewContractError(f"{subject} has a non-string field name")
    return dict(value)


def _copy_json(value: object, subject: str) -> object:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ReviewContractError(f"{subject} is not JSON data: {exc}") from exc


def _reject_forbidden_keys(value: object, subject: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                raise ReviewContractError(
                    f"{subject} contains prohibited context field {key!r}"
                )
            _reject_forbidden_keys(nested, f"{subject}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, f"{subject}[{index}]")


def _keys(
    value: Mapping[str, object],
    required: Sequence[str],
    allowed: Sequence[str],
    subject: str,
) -> None:
    actual = set(value)
    missing = sorted(set(required) - actual)
    unexpected = sorted(actual - set(allowed))
    if missing:
        raise ReviewContractError(
            f"{subject} is missing fields: {', '.join(missing)}"
        )
    if unexpected:
        raise ReviewContractError(
            f"{subject} has unsupported fields: {', '.join(unexpected)}"
        )


def _string(value: object, subject: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ReviewContractError(f"{subject} must be a string")
    if not allow_empty and not value.strip():
        raise ReviewContractError(f"{subject} must not be empty")
    return value


def _string_list(value: object, subject: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ReviewContractError(f"{subject} must be a list")
    if not allow_empty and not value:
        raise ReviewContractError(f"{subject} must not be empty")
    result = [_string(item, f"{subject}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ReviewContractError(f"{subject} must not contain duplicates")
    return result


def _digest(value: object, subject: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ReviewContractError(
            f"{subject} must be 64 lowercase hexadecimal characters"
        )
    return value


def _contract(value: object) -> dict:
    raw = _mapping(value, "issue contract")
    if "contract" in raw:
        snapshot = _mapping(raw["contract"], "issue contract.contract")
        revision = raw.get("sha256", raw.get("revision"))
    else:
        snapshot = raw
        revision = raw.get("revision", raw.get("sha256"))

    normalized = {
        "repository": _string(snapshot.get("repository"), "issue contract.repository"),
        "id": _string(snapshot.get("id"), "issue contract.id"),
        "number": snapshot.get("number"),
        "title": _string(snapshot.get("title"), "issue contract.title"),
        "body": _string(
            snapshot.get("body"), "issue contract.body", allow_empty=True
        ),
        "state": snapshot.get("state"),
        "work_blocked": snapshot.get("work_blocked"),
        "open_blocker_ids": _string_list(
            snapshot.get("open_blocker_ids"),
            "issue contract.open_blocker_ids",
            allow_empty=True,
        ),
        "revision": _digest(revision, "issue contract.revision"),
    }
    if (
        not isinstance(normalized["number"], int)
        or isinstance(normalized["number"], bool)
        or normalized["number"] <= 0
    ):
        raise ReviewContractError("issue contract.number must be a positive integer")
    if normalized["state"] != "OPEN":
        raise ReviewContractError("issue contract.state must be OPEN")
    if normalized["work_blocked"] is not False:
        raise ReviewContractError("issue contract.work_blocked must be false")
    if normalized["open_blocker_ids"]:
        raise ReviewContractError("issue contract has unresolved native blockers")
    return normalized


_IDENTITY_FIELDS = ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256")


def _identity(value: object, subject: str = "candidate identity") -> dict:
    raw = _mapping(value, subject)
    _keys(raw, _IDENTITY_FIELDS, _IDENTITY_FIELDS, subject)
    return {
        field: _string(raw[field], f"{subject}.{field}")
        for field in _IDENTITY_FIELDS
    }


def candidate_identity(candidate: Mapping[str, object]) -> dict:
    """Return the exact identity fields from a full candidate or identity object."""
    raw = _mapping(candidate, "candidate")
    if "diff" not in raw:
        return _identity(raw.get("identity", raw))
    diff = _string(raw["diff"], "candidate.diff")
    source = _mapping(raw.get("identity", raw), "candidate.identity")
    source = {
        field: source[field]
        for field in _IDENTITY_FIELDS
        if field in source
    }
    if "diff_sha256" not in source:
        source["diff_sha256"] = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    identity = _identity(source)
    expected = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    if identity["diff_sha256"] != expected:
        raise ReviewContractError("candidate.diff does not match candidate.diff_sha256")
    return identity


def _candidate(value: object) -> dict:
    raw = _mapping(value, "candidate")
    _keys(
        raw,
        ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256", "diff"),
        ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256", "diff"),
        "candidate",
    )
    diff = _string(raw["diff"], "candidate.diff")
    identity = _identity(
        {field: raw[field] for field in _IDENTITY_FIELDS}
    )
    expected = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    if identity["diff_sha256"] != expected:
        raise ReviewContractError("candidate.diff does not match candidate.diff_sha256")
    return {**identity, "diff": diff}


def _governance(value: object) -> dict:
    raw = _mapping(value, "applicable governance")
    _keys(raw, ("sources", "review_doctrine"), ("sources", "review_doctrine"), "applicable governance")
    sources = raw["sources"]
    if not isinstance(sources, list) or not sources:
        raise ReviewContractError("applicable governance.sources must not be empty")
    normalized_sources = []
    for index, source_value in enumerate(sources):
        source = _mapping(source_value, f"applicable governance.sources[{index}]")
        _keys(
            source,
            ("path", "section", "text"),
            ("path", "section", "text"),
            f"applicable governance.sources[{index}]",
        )
        normalized_sources.append(
            {
                "path": _string(source["path"], f"governance source {index}.path"),
                "section": _string(
                    source["section"], f"governance source {index}.section"
                ),
                "text": _string(
                    source["text"], f"governance source {index}.text"
                ),
            }
        )
    return {
        "sources": normalized_sources,
        "review_doctrine": _string(raw["review_doctrine"], "review doctrine"),
    }


def _stage2(value: object, identity: dict, revision: str) -> dict:
    raw = _mapping(value, "Stage 2 evidence")
    _keys(
        raw,
        ("issue_contract_revision", "candidate_identity", "checks"),
        ("issue_contract_revision", "candidate_identity", "checks"),
        "Stage 2 evidence",
    )
    if raw["issue_contract_revision"] != revision:
        raise ReviewContractError("Stage 2 evidence uses a different issue revision")
    if _identity(raw["candidate_identity"], "Stage 2 candidate identity") != identity:
        raise ReviewContractError("Stage 2 evidence uses a different candidate")
    checks = raw["checks"]
    if not isinstance(checks, list) or not checks:
        raise ReviewContractError("Stage 2 evidence.checks must not be empty")
    normalized_checks = []
    for index, check_value in enumerate(checks):
        check = _mapping(check_value, f"Stage 2 evidence.checks[{index}]")
        _keys(
            check,
            ("name", "result", "evidence"),
            ("name", "result", "evidence"),
            f"Stage 2 evidence.checks[{index}]",
        )
        if check["result"] != "passed":
            raise ReviewContractError(
                f"Stage 2 evidence.checks[{index}] must have result passed"
            )
        evidence = check["evidence"]
        if isinstance(evidence, str):
            evidence = [evidence]
        normalized_checks.append(
            {
                "name": _string(check["name"], f"Stage 2 check {index}.name"),
                "result": "passed",
                "evidence": _string_list(
                    evidence, f"Stage 2 check {index}.evidence"
                ),
            }
        )
    return {
        "issue_contract_revision": revision,
        "candidate_identity": identity,
        "checks": normalized_checks,
    }


def _scope(value: object) -> dict:
    raw = _mapping(value, "review scope")
    _keys(raw, ("included", "exclusions"), ("included", "exclusions"), "review scope")
    included = _string_list(raw["included"], "review scope.included")
    exclusions = _string_list(
        raw["exclusions"], "review scope.exclusions", allow_empty=True
    )
    if set(included) & set(exclusions):
        raise ReviewContractError("review scope cannot include and exclude the same item")
    return {"included": included, "exclusions": exclusions}


def build_review_packet(
    issue_contract: Mapping[str, object],
    candidate: Mapping[str, object],
    applicable_governance: Mapping[str, object],
    stage2_evidence: Mapping[str, object],
    scope: Mapping[str, object],
) -> dict:
    """Build the bounded packet supplied to the fresh reviewer session."""
    contract = _contract(issue_contract)
    full_candidate = _candidate(candidate)
    packet = {
        "schema": REVIEW_PACKET_SCHEMA,
        "issue_contract": contract,
        "candidate": full_candidate,
        "applicable_governance": _governance(applicable_governance),
        "stage2_evidence": _stage2(
            stage2_evidence,
            {field: full_candidate[field] for field in _IDENTITY_FIELDS},
            contract["revision"],
        ),
        "scope": _scope(scope),
    }
    return validate_review_packet(packet)


def validate_review_packet(packet: Mapping[str, object]) -> dict:
    """Validate and copy a reviewer packet, rejecting hidden context fields."""
    copied = _copy_json(packet, "review packet")
    _reject_forbidden_keys(copied, "review packet")
    raw = _mapping(copied, "review packet")
    _keys(
        raw,
        (
            "schema",
            "issue_contract",
            "candidate",
            "applicable_governance",
            "stage2_evidence",
            "scope",
        ),
        (
            "schema",
            "issue_contract",
            "candidate",
            "applicable_governance",
            "stage2_evidence",
            "scope",
        ),
        "review packet",
    )
    if raw["schema"] != REVIEW_PACKET_SCHEMA:
        raise ReviewContractError("review packet has an unsupported schema")
    contract = _contract(raw["issue_contract"])
    candidate = _candidate(raw["candidate"])
    identity = {field: candidate[field] for field in _IDENTITY_FIELDS}
    stage2 = _stage2(raw["stage2_evidence"], identity, contract["revision"])
    normalized = {
        "schema": REVIEW_PACKET_SCHEMA,
        "issue_contract": contract,
        "candidate": candidate,
        "applicable_governance": _governance(raw["applicable_governance"]),
        "stage2_evidence": stage2,
        "scope": _scope(raw["scope"]),
    }
    return normalized


_FINDING_REQUIRED = (
    "finding_id",
    "severity",
    "defect_or_invariant",
    "supporting_evidence",
    "contract_or_governance",
)
_FINDING_OPTIONAL = ("affected_location", "confidence", "uncertainty")


def _finding(value: object, index: int) -> dict:
    subject = f"review finding {index}"
    raw = _mapping(value, subject)
    _keys(
        raw,
        _FINDING_REQUIRED,
        _FINDING_REQUIRED + _FINDING_OPTIONAL,
        subject,
    )
    finding = {
        "finding_id": _string(raw["finding_id"], f"{subject}.finding_id"),
        "severity": _string(raw["severity"], f"{subject}.severity"),
        "defect_or_invariant": _string(
            raw["defect_or_invariant"], f"{subject}.defect_or_invariant"
        ),
        "supporting_evidence": _string_list(
            raw["supporting_evidence"], f"{subject}.supporting_evidence"
        ),
        "contract_or_governance": _string(
            raw["contract_or_governance"], f"{subject}.contract_or_governance"
        ),
    }
    if "affected_location" in raw:
        location = raw["affected_location"]
        finding["affected_location"] = (
            None
            if location is None
            else _string(location, f"{subject}.affected_location")
        )
    if "confidence" in raw:
        confidence = raw["confidence"]
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise ReviewContractError(
                f"{subject}.confidence must be a number from 0 through 1"
            )
        finding["confidence"] = confidence
    if "uncertainty" in raw:
        finding["uncertainty"] = _string(
            raw["uncertainty"], f"{subject}.uncertainty"
        )
    return finding


def validate_findings(findings: object) -> list[dict]:
    """Validate findings without adding implementation instructions to them."""
    if not isinstance(findings, list):
        raise ReviewContractError("review findings must be a list")
    normalized = [_finding(value, index) for index, value in enumerate(findings)]
    identities = [finding["finding_id"] for finding in normalized]
    if len(identities) != len(set(identities)):
        raise ReviewContractError("review findings contain duplicate identities")
    return normalized


def validate_review_result(
    result: Mapping[str, object], packet: Mapping[str, object]
) -> dict:
    """Validate reviewer output against the frozen candidate and packet."""
    validated_packet = validate_review_packet(packet)
    copied = _copy_json(result, "review result")
    _reject_forbidden_keys(copied, "review result")
    raw = _mapping(copied, "review result")
    _keys(
        raw,
        ("schema", "candidate_identity", "findings"),
        ("schema", "candidate_identity", "findings"),
        "review result",
    )
    if raw["schema"] != REVIEW_RESULT_SCHEMA:
        raise ReviewContractError("review result has an unsupported schema")
    expected = candidate_identity(validated_packet["candidate"])
    if _identity(raw["candidate_identity"]) != expected:
        raise ReviewContractError("review result targets a different candidate")
    return {
        "schema": REVIEW_RESULT_SCHEMA,
        "candidate_identity": expected,
        "findings": validate_findings(raw["findings"]),
    }


def build_adjudication_packet(
    packet: Mapping[str, object], findings: object
) -> dict:
    """Build the adjudicator packet without the candidate diff or implementation context."""
    review_packet = validate_review_packet(packet)
    normalized_findings = validate_findings(findings)
    adjudication_packet = {
        "schema": ADJUDICATION_PACKET_SCHEMA,
        "issue_contract": review_packet["issue_contract"],
        "candidate_identity": candidate_identity(review_packet["candidate"]),
        "applicable_governance": review_packet["applicable_governance"],
        "evidence": {
            "stage2": review_packet["stage2_evidence"],
            "finding_support": [
                {
                    "finding_id": finding["finding_id"],
                    "supporting_evidence": finding["supporting_evidence"],
                }
                for finding in normalized_findings
            ],
        },
        "findings": normalized_findings,
        "scope": review_packet["scope"],
    }
    return validate_adjudication_packet(adjudication_packet)


def validate_adjudication_packet(packet: Mapping[str, object]) -> dict:
    """Validate the adjudicator input and its evidence boundary."""
    copied = _copy_json(packet, "adjudication packet")
    _reject_forbidden_keys(copied, "adjudication packet")
    raw = _mapping(copied, "adjudication packet")
    _keys(
        raw,
        (
            "schema",
            "issue_contract",
            "candidate_identity",
            "applicable_governance",
            "evidence",
            "findings",
            "scope",
        ),
        (
            "schema",
            "issue_contract",
            "candidate_identity",
            "applicable_governance",
            "evidence",
            "findings",
            "scope",
        ),
        "adjudication packet",
    )
    if raw["schema"] != ADJUDICATION_PACKET_SCHEMA:
        raise ReviewContractError("adjudication packet has an unsupported schema")
    contract = _contract(raw["issue_contract"])
    identity = _identity(raw["candidate_identity"])
    governance = _governance(raw["applicable_governance"])
    scope = _scope(raw["scope"])
    findings = validate_findings(raw["findings"])
    evidence = _mapping(raw["evidence"], "adjudication evidence")
    _keys(
        evidence,
        ("stage2", "finding_support"),
        ("stage2", "finding_support"),
        "adjudication evidence",
    )
    stage2 = _stage2(evidence["stage2"], identity, contract["revision"])
    supports = evidence["finding_support"]
    if not isinstance(supports, list) or len(supports) != len(findings):
        raise ReviewContractError("adjudication evidence must cite every finding")
    normalized_supports = []
    expected_ids = [finding["finding_id"] for finding in findings]
    for index, support_value in enumerate(supports):
        support = _mapping(support_value, f"finding support {index}")
        _keys(
            support,
            ("finding_id", "supporting_evidence"),
            ("finding_id", "supporting_evidence"),
            f"finding support {index}",
        )
        finding_id = _string(support["finding_id"], f"finding support {index}.finding_id")
        if finding_id != expected_ids[index]:
            raise ReviewContractError("adjudication evidence finding order does not match findings")
        normalized_supports.append(
            {
                "finding_id": finding_id,
                "supporting_evidence": _string_list(
                    support["supporting_evidence"],
                    f"finding support {index}.supporting_evidence",
                ),
            }
        )
    return {
        "schema": ADJUDICATION_PACKET_SCHEMA,
        "issue_contract": contract,
        "candidate_identity": identity,
        "applicable_governance": governance,
        "evidence": {"stage2": stage2, "finding_support": normalized_supports},
        "findings": findings,
        "scope": scope,
    }


def _correction(value: object, scope: dict, subject: str) -> dict:
    raw = _mapping(value, subject)
    _keys(raw, ("summary", "locations", "validation"), ("summary", "locations", "validation"), subject)
    locations = _string_list(raw["locations"], f"{subject}.locations")
    allowed = set(scope["included"])
    outside = sorted(set(locations) - allowed)
    if outside:
        raise ReviewContractError(
            f"{subject} leaves the accepted scope: {', '.join(outside)}"
        )
    return {
        "summary": _string(raw["summary"], f"{subject}.summary"),
        "locations": locations,
        "validation": _string_list(raw["validation"], f"{subject}.validation"),
    }


def validate_adjudication_result(
    result: Mapping[str, object], packet: Mapping[str, object]
) -> dict:
    """Validate dispositions and return no raw reviewer findings."""
    adjudication_packet = validate_adjudication_packet(packet)
    copied = _copy_json(result, "adjudication result")
    _reject_forbidden_keys(copied, "adjudication result")
    raw = _mapping(copied, "adjudication result")
    _keys(
        raw,
        ("schema", "candidate_identity", "dispositions", "human_handoff"),
        ("schema", "candidate_identity", "dispositions", "human_handoff"),
        "adjudication result",
    )
    if raw["schema"] != ADJUDICATION_RESULT_SCHEMA:
        raise ReviewContractError("adjudication result has an unsupported schema")
    identity = _identity(raw["candidate_identity"])
    if identity != adjudication_packet["candidate_identity"]:
        raise ReviewContractError("adjudication result targets a different candidate")

    handoff = _mapping(raw["human_handoff"], "adjudication human handoff")
    _keys(handoff, ("required", "reason"), ("required", "reason"), "adjudication human handoff")
    if not isinstance(handoff["required"], bool):
        raise ReviewContractError("adjudication human handoff.required must be boolean")
    reason = handoff["reason"]
    if handoff["required"]:
        reason = _string(reason, "adjudication human handoff.reason")
    elif reason is not None and (not isinstance(reason, str) or reason.strip()):
        raise ReviewContractError("a non-required handoff must have a null or empty reason")

    raw_dispositions = raw["dispositions"]
    if not isinstance(raw_dispositions, list):
        raise ReviewContractError("adjudication dispositions must be a list")
    findings = adjudication_packet["findings"]
    if len(raw_dispositions) != len(findings):
        raise ReviewContractError("every finding must receive exactly one disposition")
    expected_ids = [finding["finding_id"] for finding in findings]
    normalized_dispositions = []
    for index, disposition_value in enumerate(raw_dispositions):
        subject = f"adjudication disposition {index}"
        disposition = _mapping(disposition_value, subject)
        _keys(
            disposition,
            ("finding_id", "disposition", "basis", "correction"),
            ("finding_id", "disposition", "basis", "correction"),
            subject,
        )
        finding_id = _string(disposition["finding_id"], f"{subject}.finding_id")
        if finding_id != expected_ids[index]:
            raise ReviewContractError("adjudication disposition order does not match findings")
        decision = _string(disposition["disposition"], f"{subject}.disposition")
        if decision not in DISPOSITIONS:
            raise ReviewContractError(
                f"{subject}.disposition must be one of {', '.join(DISPOSITIONS)}"
            )
        correction_value = disposition["correction"]
        correction = None
        if decision in {"blocker", "patch-now"}:
            if correction_value is None:
                if decision != "blocker" or not handoff["required"]:
                    raise ReviewContractError(
                        f"{subject} needs a current-pass correction or a human handoff"
                    )
            else:
                correction = _correction(
                    correction_value,
                    adjudication_packet["scope"],
                    f"{subject}.correction",
                )
        elif correction_value is not None:
            raise ReviewContractError(
                f"{subject} cannot change the candidate for {decision}"
            )
        normalized_dispositions.append(
            {
                "finding_id": finding_id,
                "disposition": decision,
                "basis": _string(disposition["basis"], f"{subject}.basis"),
                "correction": correction,
            }
        )
    return {
        "schema": ADJUDICATION_RESULT_SCHEMA,
        "candidate_identity": identity,
        "dispositions": normalized_dispositions,
        "human_handoff": {"required": handoff["required"], "reason": reason},
    }
