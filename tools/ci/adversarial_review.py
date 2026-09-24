"""Define repository-owned contracts for bounded adversarial review.

The review packet and result contracts live here so a session provider cannot
define governance. The concrete fresh-session runner is kept in the sibling
``adversarial_review_session`` module.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

try:
    from .issue_contract import contract_digest
except ImportError:  # pragma: no cover - direct script compatibility
    def contract_digest(contract: dict) -> str:
        """Mirror the repository issue-contract digest for direct execution."""
        encoded = json.dumps(
            contract, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

try:
    from .adversarial_review_contracts import (
        ADJUDICATION_PACKET_SCHEMA,
        ADJUDICATION_RESULT_OUTPUT_SCHEMA,
        ADJUDICATION_RESULT_SCHEMA,
        DISPOSITIONS,
        REVIEW_PACKET_SCHEMA,
        REVIEW_RESULT_OUTPUT_SCHEMA,
        REVIEW_RESULT_SCHEMA,
        RISK_TIERS,
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_OUTPUT_SCHEMA,
        SESSION_FAILURE_SCHEMA,
        ReviewContractError,
        _IDENTITY_FIELDS,
        validate_adjudication_result,
        validate_review_result,
    )
    from .adversarial_review_evidence import (
        evidence_ids,
        packet_sources,
        referenced_evidence,
        validate_source_items,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review_contracts import (  # type: ignore[no-redef]
        ADJUDICATION_PACKET_SCHEMA,
        ADJUDICATION_RESULT_OUTPUT_SCHEMA,
        ADJUDICATION_RESULT_SCHEMA,
        DISPOSITIONS,
        REVIEW_PACKET_SCHEMA,
        REVIEW_RESULT_OUTPUT_SCHEMA,
        REVIEW_RESULT_SCHEMA,
        RISK_TIERS,
        SESSION_FAILURE_CLASSES,
        SESSION_FAILURE_OUTPUT_SCHEMA,
        SESSION_FAILURE_SCHEMA,
        ReviewContractError,
        _IDENTITY_FIELDS,
        validate_adjudication_result,
        validate_review_result,
    )
    from adversarial_review_evidence import (  # type: ignore[no-redef]
        evidence_ids,
        packet_sources,
        referenced_evidence,
        validate_source_items,
    )


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


class ReviewSessionError(RuntimeError):
    """Raised when an isolated reviewer or adjudicator cannot return a result."""

def _mapping(
    value: object, subject: str, *, structured_output: bool = False
) -> dict:
    if not isinstance(value, Mapping):
        raise ReviewContractError(
            f"{subject} must be an object",
            validation_stage="shape" if structured_output else None,
            diagnostic_code="output_top_level_shape" if structured_output else None,
        )
    if any(not isinstance(key, str) for key in value):
        raise ReviewContractError(
            f"{subject} has a non-string field name",
            validation_stage="shape" if structured_output else None,
            diagnostic_code="output_schema" if structured_output else None,
        )
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
    *,
    structured_output: bool = False,
) -> None:
    actual = set(value)
    missing = sorted(set(required) - actual)
    unexpected = sorted(actual - set(allowed))
    if missing:
        raise ReviewContractError(
            f"{subject} is missing fields: {', '.join(missing)}",
            validation_stage="shape" if structured_output else None,
            diagnostic_code=(
                "output_missing_required_field" if structured_output else None
            ),
        )
    if unexpected:
        raise ReviewContractError(
            f"{subject} has unsupported fields: {', '.join(unexpected)}",
            validation_stage="shape" if structured_output else None,
            diagnostic_code="output_unsupported_field" if structured_output else None,
        )


def _string(value: object, subject: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ReviewContractError(f"{subject} must be a string")
    if not allow_empty and not value.strip():
        raise ReviewContractError(f"{subject} must not be empty")
    return value


def _risk(value: object) -> str:
    if value not in RISK_TIERS:
        raise ReviewContractError(
            "review risk must be one of: " + ", ".join(RISK_TIERS)
        )
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
    digest_input = {
        key: normalized[key]
        for key in (
            "repository",
            "id",
            "number",
            "title",
            "body",
            "state",
            "work_blocked",
            "open_blocker_ids",
        )
    }
    if normalized["revision"] != contract_digest(digest_input):
        raise ReviewContractError(
            "issue contract.revision does not match the accepted snapshot"
        )
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
    *,
    risk: str,
) -> dict:
    """Build the bounded packet supplied to the fresh reviewer session."""
    contract = _contract(issue_contract)
    full_candidate = _candidate(candidate)
    governance = _governance(applicable_governance)
    stage2 = _stage2(
        stage2_evidence,
        {field: full_candidate[field] for field in _IDENTITY_FIELDS},
        contract["revision"],
    )
    review_scope = _scope(scope)
    packet = {
        "schema": REVIEW_PACKET_SCHEMA,
        "risk": _risk(risk),
        "issue_contract": {**contract, "evidence_id": "issue_contract"},
        "candidate": {**full_candidate, "evidence_id": "candidate"},
        "applicable_governance": {
            "sources": [
                {**source, "evidence_id": f"governance.{index}"}
                for index, source in enumerate(governance["sources"])
            ],
            "review_doctrine": governance["review_doctrine"],
            "review_doctrine_evidence_id": "governance.doctrine",
        },
        "stage2_evidence": {**stage2, "evidence_id": "stage2_evidence"},
        "scope": {**review_scope, "evidence_id": "scope"},
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
            "risk",
            "issue_contract",
            "candidate",
            "applicable_governance",
            "stage2_evidence",
            "scope",
        ),
        (
            "schema",
            "risk",
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
    risk = _risk(raw["risk"])
    contract_value = _mapping(raw["issue_contract"], "issue contract source")
    if contract_value.pop("evidence_id", None) != "issue_contract":
        raise ReviewContractError("issue contract has an unsupported evidence ID")
    contract = _contract(contract_value)
    candidate_value = _mapping(raw["candidate"], "candidate source")
    if candidate_value.pop("evidence_id", None) != "candidate":
        raise ReviewContractError("candidate has an unsupported evidence ID")
    candidate = _candidate(candidate_value)
    identity = {field: candidate[field] for field in _IDENTITY_FIELDS}
    stage2_value = _mapping(raw["stage2_evidence"], "Stage 2 source")
    if stage2_value.pop("evidence_id", None) != "stage2_evidence":
        raise ReviewContractError("Stage 2 evidence has an unsupported evidence ID")
    stage2 = _stage2(stage2_value, identity, contract["revision"])
    governance_value = _mapping(
        raw["applicable_governance"], "governance source"
    )
    doctrine_id = governance_value.pop("review_doctrine_evidence_id", None)
    if doctrine_id != "governance.doctrine":
        raise ReviewContractError("review doctrine has an unsupported evidence ID")
    raw_sources = governance_value.get("sources")
    if not isinstance(raw_sources, list):
        raise ReviewContractError("applicable governance.sources must be a list")
    normalized_sources = []
    for index, source_value in enumerate(raw_sources):
        source = _mapping(source_value, f"governance source {index}")
        if source.pop("evidence_id", None) != f"governance.{index}":
            raise ReviewContractError(
                f"governance source {index} has an unsupported evidence ID"
            )
        normalized_sources.append(source)
    governance_value["sources"] = normalized_sources
    governance = _governance(governance_value)
    scope_value = _mapping(raw["scope"], "scope source")
    if scope_value.pop("evidence_id", None) != "scope":
        raise ReviewContractError("scope has an unsupported evidence ID")
    scope = _scope(scope_value)
    normalized = {
        "schema": REVIEW_PACKET_SCHEMA,
        "risk": risk,
        "issue_contract": {**contract, "evidence_id": "issue_contract"},
        "candidate": {**candidate, "evidence_id": "candidate"},
        "applicable_governance": {
            "sources": [
                {**source, "evidence_id": f"governance.{index}"}
                for index, source in enumerate(governance["sources"])
            ],
            "review_doctrine": governance["review_doctrine"],
            "review_doctrine_evidence_id": "governance.doctrine",
        },
        "stage2_evidence": {**stage2, "evidence_id": "stage2_evidence"},
        "scope": {**scope, "evidence_id": "scope"},
    }
    evidence_ids(normalized)
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
        if confidence is None:
            finding["confidence"] = None
        elif (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise ReviewContractError(
                f"{subject}.confidence must be a number from 0 through 1"
            )
        else:
            finding["confidence"] = confidence
    if "uncertainty" in raw:
        uncertainty = raw["uncertainty"]
        finding["uncertainty"] = (
            None
            if uncertainty is None
            else _string(uncertainty, f"{subject}.uncertainty")
        )
    return finding


def validate_findings(findings: object) -> list[dict]:
    """Validate findings without adding implementation instructions to them."""
    if not isinstance(findings, list):
        raise ReviewContractError("review findings must be a list")
    normalized = [_finding(value, index) for index, value in enumerate(findings)]
    identities = [finding["finding_id"] for finding in normalized]
    if len(identities) != len(set(identities)):
        raise ReviewContractError(
            "review findings contain duplicate identities",
            validation_stage="semantic",
            diagnostic_code="review_finding_contract",
            diagnostic_detail_code="review_finding_identity_duplicate",
        )
    return normalized


def build_adjudication_packet(
    packet: Mapping[str, object], findings: object
) -> dict:
    """Build the adjudicator packet with only cited, source-backed evidence."""
    review_packet = validate_review_packet(packet)
    normalized_findings = validate_findings(findings)
    authorized_ids = evidence_ids(review_packet)
    for index, finding in enumerate(normalized_findings):
        missing = sorted(set(finding["supporting_evidence"]) - authorized_ids)
        if missing:
            raise ReviewContractError(
                f"review finding {index} cites unsupported evidence IDs: "
                + ", ".join(missing)
            )
    adjudication_packet = {
        "schema": ADJUDICATION_PACKET_SCHEMA,
        "issue_contract_revision": review_packet["issue_contract"]["revision"],
        "candidate_identity": candidate_identity(review_packet["candidate"]),
        "evidence": {
            "source_items": referenced_evidence(
                review_packet, normalized_findings
            ),
        },
        "findings": normalized_findings,
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
            "issue_contract_revision",
            "candidate_identity",
            "evidence",
            "findings",
        ),
        (
            "schema",
            "issue_contract_revision",
            "candidate_identity",
            "evidence",
            "findings",
        ),
        "adjudication packet",
    )
    if raw["schema"] != ADJUDICATION_PACKET_SCHEMA:
        raise ReviewContractError("adjudication packet has an unsupported schema")
    revision = _digest(raw["issue_contract_revision"], "adjudication issue revision")
    identity = _identity(raw["candidate_identity"])
    findings = validate_findings(raw["findings"])
    evidence = _mapping(raw["evidence"], "adjudication evidence")
    _keys(evidence, ("source_items",), ("source_items",), "adjudication evidence")
    source_items = validate_source_items(
        evidence["source_items"], "adjudication evidence.source_items", allow_empty=True
    )
    source_ids = {item["evidence_id"] for item in source_items}
    cited_ids = {
        evidence_id
        for finding in findings
        for evidence_id in finding["supporting_evidence"]
    }
    missing = sorted(cited_ids - source_ids)
    extra = sorted(source_ids - cited_ids)
    if missing:
        raise ReviewContractError(
            "adjudication packet omits cited source evidence: " + ", ".join(missing)
        )
    if extra:
        raise ReviewContractError(
            "adjudication packet contains uncited source evidence: " + ", ".join(extra)
        )
    return {
        "schema": ADJUDICATION_PACKET_SCHEMA,
        "issue_contract_revision": revision,
        "candidate_identity": identity,
        "evidence": {"source_items": source_items},
        "findings": findings,
    }
