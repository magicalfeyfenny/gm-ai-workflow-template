"""Build and validate the small source-evidence catalog used by adjudication."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

try:
    from .adversarial_review_contracts import ReviewContractError
except ImportError:  # pragma: no cover - direct script compatibility
    from adversarial_review_contracts import ReviewContractError  # type: ignore[no-redef]


_EVIDENCE_FIELDS = ("evidence_id", "kind", "source", "text")
_EVIDENCE_KINDS = {
    "candidate-diff",
    "candidate-identity",
    "issue-contract",
    "governance",
    "stage2",
    "scope",
}
_EVIDENCE_ID = re.compile(r"[a-z][a-z0-9_.-]*\Z")


def _mapping(value: object, subject: str) -> dict:
    if not isinstance(value, Mapping):
        raise ReviewContractError(f"{subject} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ReviewContractError(f"{subject} has a non-string field name")
    return dict(value)


def _keys(value: Mapping[str, object], subject: str) -> None:
    actual = set(value)
    missing = sorted(set(_EVIDENCE_FIELDS) - actual)
    unexpected = sorted(actual - set(_EVIDENCE_FIELDS))
    if missing:
        raise ReviewContractError(f"{subject} is missing fields: {', '.join(missing)}")
    if unexpected:
        raise ReviewContractError(
            f"{subject} has unsupported fields: {', '.join(unexpected)}"
        )


def _string(value: object, subject: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewContractError(f"{subject} must be a non-empty string")
    return value


def validate_evidence_catalog(
    value: object,
    subject: str = "evidence catalog",
    *,
    allow_empty: bool = False,
) -> list[dict]:
    if not isinstance(value, list) or (not allow_empty and not value):
        requirement = "list" if allow_empty else "non-empty list"
        raise ReviewContractError(f"{subject} must be a {requirement}")
    normalized = []
    identifiers = set()
    for index, item_value in enumerate(value):
        item = _mapping(item_value, f"{subject}[{index}]")
        _keys(item, f"{subject}[{index}]")
        evidence_id = _string(item["evidence_id"], f"{subject}[{index}].evidence_id")
        if _EVIDENCE_ID.fullmatch(evidence_id) is None:
            raise ReviewContractError(
                f"{subject}[{index}].evidence_id is not a stable evidence ID"
            )
        if evidence_id in identifiers:
            raise ReviewContractError(f"{subject} contains duplicate evidence IDs")
        identifiers.add(evidence_id)
        kind = _string(item["kind"], f"{subject}[{index}].kind")
        if kind not in _EVIDENCE_KINDS:
            raise ReviewContractError(f"{subject}[{index}] has an unsupported evidence kind")
        normalized.append(
            {
                "evidence_id": evidence_id,
                "kind": kind,
                "source": _string(item["source"], f"{subject}[{index}].source"),
                "text": item["text"]
                if isinstance(item["text"], str)
                else _string(item["text"], f"{subject}[{index}].text"),
            }
        )
    return normalized


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def build_evidence_catalog(
    contract: Mapping[str, object],
    candidate: Mapping[str, object],
    governance: Mapping[str, object],
    stage2: Mapping[str, object],
    scope: Mapping[str, object],
) -> list[dict]:
    """Materialize only source text already admitted to the review packet."""
    catalog = [
        {
            "evidence_id": "candidate.diff",
            "kind": "candidate-diff",
            "source": "candidate.diff",
            "text": _string(candidate["diff"], "candidate.diff"),
        },
        {
            "evidence_id": "candidate.identity",
            "kind": "candidate-identity",
            "source": "candidate.identity",
            "text": _json_text(
                {
                    key: candidate[key]
                    for key in ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256")
                }
            ),
        },
        {
            "evidence_id": "issue_contract.body",
            "kind": "issue-contract",
            "source": "issue_contract.body",
            "text": contract["body"],
        },
        {
            "evidence_id": "issue_contract.snapshot",
            "kind": "issue-contract",
            "source": "issue_contract.snapshot",
            "text": _json_text(contract),
        },
    ]
    for index, source in enumerate(governance["sources"]):
        catalog.append(
            {
                "evidence_id": f"governance.{index}",
                "kind": "governance",
                "source": f"{source['path']}#{source['section']}",
                "text": _string(source["text"], f"governance source {index}.text"),
            }
        )
    catalog.append(
        {
            "evidence_id": "governance.doctrine",
            "kind": "governance",
            "source": "governance.review_doctrine",
            "text": _string(governance["review_doctrine"], "review doctrine"),
        }
    )
    for index, check in enumerate(stage2["checks"]):
        catalog.append(
            {
                "evidence_id": f"stage2.{index}",
                "kind": "stage2",
                "source": f"stage2.checks[{index}].{check['name']}",
                "text": "\n".join(["result=passed", *check["evidence"]]),
            }
        )
    catalog.append(
        {
            "evidence_id": "scope.boundary",
            "kind": "scope",
            "source": "scope.included-and-exclusions",
            "text": _json_text(scope),
        }
    )
    return validate_evidence_catalog(catalog)


def referenced_evidence(
    catalog: Sequence[Mapping[str, object]], findings: Sequence[Mapping[str, object]]
) -> list[dict]:
    """Return exactly the source items cited by findings, in catalog order."""
    normalized = validate_evidence_catalog(list(catalog))
    by_id = {item["evidence_id"]: item for item in normalized}
    referenced = {
        evidence_id
        for finding in findings
        for evidence_id in finding["supporting_evidence"]
    }
    unknown = sorted(referenced - set(by_id))
    if unknown:
        raise ReviewContractError(
            "findings cite evidence absent from the authorized catalog: "
            + ", ".join(unknown)
        )
    return [item for item in normalized if item["evidence_id"] in referenced]


def evidence_ids(catalog: Sequence[Mapping[str, object]]) -> set[str]:
    return {item["evidence_id"] for item in validate_evidence_catalog(list(catalog))}
