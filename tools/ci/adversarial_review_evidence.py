"""Resolve cited evidence directly from the canonical review packet."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

try:
    from .adversarial_review_contracts import ReviewContractError
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review_contracts import ReviewContractError  # type: ignore[no-redef]


_SOURCE_ID = re.compile(r"[a-z][a-z0-9_.-]*\Z")
_SOURCE_ITEM_FIELDS = {"evidence_id", "source", "text"}


def _mapping(value: object, subject: str) -> dict:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise ReviewContractError(f"{subject} must be an object")
    return dict(value)


def _evidence_id(value: object, subject: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or _SOURCE_ID.fullmatch(value) is None
    ):
        raise ReviewContractError(f"{subject} must be a stable evidence ID")
    return value


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def validate_source_items(
    value: object,
    subject: str = "adjudication sources",
    *,
    allow_empty: bool = False,
) -> list[dict[str, str]]:
    if not isinstance(value, list) or (not allow_empty and not value):
        requirement = "list" if allow_empty else "non-empty list"
        raise ReviewContractError(f"{subject} must be a {requirement}")
    normalized = []
    identifiers: set[str] = set()
    for index, raw_value in enumerate(value):
        item = _mapping(raw_value, f"{subject}[{index}]")
        if set(item) != _SOURCE_ITEM_FIELDS:
            raise ReviewContractError(
                f"{subject}[{index}] has unsupported or missing fields"
            )
        evidence_id = _evidence_id(
            item["evidence_id"], f"{subject}[{index}].evidence_id"
        )
        if evidence_id in identifiers:
            raise ReviewContractError(f"{subject} contains duplicate evidence IDs")
        identifiers.add(evidence_id)
        source = item["source"]
        text = item["text"]
        if not isinstance(source, str) or not source.strip():
            raise ReviewContractError(f"{subject}[{index}].source must be non-empty")
        if not isinstance(text, str):
            raise ReviewContractError(f"{subject}[{index}].text must be a string")
        normalized.append(
            {"evidence_id": evidence_id, "source": source, "text": text}
        )
    return normalized


def evidence_ids(packet: Mapping[str, object]) -> set[str]:
    contract = _mapping(packet["issue_contract"], "issue contract source")
    candidate = _mapping(packet["candidate"], "candidate source")
    governance = _mapping(
        packet["applicable_governance"], "governance source"
    )
    stage2 = _mapping(packet["stage2_evidence"], "Stage 2 source")
    scope = _mapping(packet["scope"], "scope source")
    sources = governance.get("sources")
    if not isinstance(sources, list):
        raise ReviewContractError("governance sources must be a list")
    identifiers = {
        _evidence_id(contract.get("evidence_id"), "issue contract.evidence_id"),
        _evidence_id(candidate.get("evidence_id"), "candidate.evidence_id"),
        _evidence_id(
            governance.get("review_doctrine_evidence_id"),
            "governance.review_doctrine_evidence_id",
        ),
        _evidence_id(stage2.get("evidence_id"), "Stage 2 evidence.evidence_id"),
        _evidence_id(scope.get("evidence_id"), "scope.evidence_id"),
    }
    identifiers.update(
        _evidence_id(
            _mapping(source, f"governance.sources[{index}]").get("evidence_id"),
            f"governance.sources[{index}].evidence_id",
        )
        for index, source in enumerate(sources)
    )
    if len(identifiers) != len(sources) + 5:
        raise ReviewContractError("review packet contains duplicate evidence IDs")
    return identifiers


def packet_sources(packet: Mapping[str, object]) -> list[dict[str, str]]:
    """Return source views without copying them into the reviewer packet."""
    identifiers = evidence_ids(packet)
    contract = _mapping(packet["issue_contract"], "issue contract source")
    candidate = _mapping(packet["candidate"], "candidate source")
    governance = _mapping(
        packet["applicable_governance"], "governance source"
    )
    stage2 = _mapping(packet["stage2_evidence"], "Stage 2 source")
    scope = _mapping(packet["scope"], "scope source")

    def content(source: Mapping[str, object], id_field: str = "evidence_id") -> dict:
        return {key: value for key, value in source.items() if key != id_field}

    sources = [
        {
            "evidence_id": contract["evidence_id"],
            "source": "accepted issue contract",
            "text": _json_text(content(contract)),
        },
        {
            "evidence_id": candidate["evidence_id"],
            "source": "reviewed candidate",
            "text": _json_text(content(candidate)),
        },
    ]
    for index, source_value in enumerate(governance["sources"]):
        source = _mapping(source_value, f"governance.sources[{index}]")
        sources.append(
            {
                "evidence_id": source["evidence_id"],
                "source": f"{source['path']}#{source['section']}",
                "text": source["text"],
            }
        )
    sources.append(
        {
            "evidence_id": governance["review_doctrine_evidence_id"],
            "source": "governance review doctrine",
            "text": governance["review_doctrine"],
        }
    )
    sources.extend(
        [
            {
                "evidence_id": stage2["evidence_id"],
                "source": "Stage 2 evidence",
                "text": _json_text(content(stage2)),
            },
            {
                "evidence_id": scope["evidence_id"],
                "source": "review scope",
                "text": _json_text(content(scope)),
            },
        ]
    )
    normalized = validate_source_items(sources)
    if {item["evidence_id"] for item in normalized} != identifiers:
        raise ReviewContractError("review packet source IDs are inconsistent")
    return normalized


def referenced_evidence(
    packet: Mapping[str, object], findings: Sequence[Mapping[str, object]]
) -> list[dict[str, str]]:
    """Resolve only cited source objects from their canonical packet locations."""
    sources = packet_sources(packet)
    by_id = {item["evidence_id"]: item for item in sources}
    referenced = {
        evidence_id
        for finding in findings
        for evidence_id in finding["supporting_evidence"]
    }
    unknown = sorted(referenced - set(by_id))
    if unknown:
        raise ReviewContractError(
            "findings cite evidence absent from the review packet: "
            + ", ".join(unknown)
        )
    return [item for item in sources if item["evidence_id"] in referenced]
