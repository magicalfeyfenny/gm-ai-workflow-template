"""Stable schema values for the bounded adversarial review contracts."""

from __future__ import annotations


class ReviewContractError(ValueError):
    """Raised when a packet or structured session result is not safe to use."""


REVIEW_PACKET_SCHEMA = "adversarial-review-packet:v2"
REVIEW_RESULT_SCHEMA = "adversarial-review-result:v2"
ADJUDICATION_PACKET_SCHEMA = "adversarial-adjudication-packet:v2"
ADJUDICATION_RESULT_SCHEMA = "adversarial-adjudication-result:v2"
MAX_CORRECTION_CYCLES = 2
DISPOSITIONS = ("blocker", "patch-now", "follow-up", "reject")
_IDENTITY_FIELDS = ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256")


_IDENTITY_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_IDENTITY_FIELDS),
    "properties": {field: {"type": "string"} for field in _IDENTITY_FIELDS},
}

_FINDING_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "finding_id",
        "severity",
        "defect_or_invariant",
        "supporting_evidence",
        "contract_or_governance",
        "affected_location",
        "confidence",
        "uncertainty",
    ],
    "properties": {
        "finding_id": {"type": "string"},
        "severity": {"type": "string"},
        "defect_or_invariant": {"type": "string"},
        "supporting_evidence": {"type": "array", "items": {"type": "string"}},
        "contract_or_governance": {"type": "string"},
        "affected_location": {"type": ["string", "null"]},
        "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "uncertainty": {"type": ["string", "null"]},
    },
}

REVIEW_RESULT_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "candidate_identity", "findings"],
    "properties": {
        "schema": {"type": "string", "const": REVIEW_RESULT_SCHEMA},
        "candidate_identity": _IDENTITY_OUTPUT_SCHEMA,
        "findings": {"type": "array", "items": _FINDING_OUTPUT_SCHEMA},
    },
}

_CORRECTION_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "locations", "validation"],
    "properties": {
        "summary": {"type": "string"},
        "locations": {"type": "array", "items": {"type": "string"}},
        "validation": {"type": "array", "items": {"type": "string"}},
    },
}

_DISPOSITION_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "finding_id",
        "disposition",
        "basis",
        "correction",
        "correction_accepted",
    ],
    "properties": {
        "finding_id": {"type": "string"},
        "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
        "basis": {"type": "string"},
        "correction": {"anyOf": [{"type": "null"}, _CORRECTION_OUTPUT_SCHEMA]},
        "correction_accepted": {"type": "boolean"},
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
        "schema": {"type": "string", "const": ADJUDICATION_RESULT_SCHEMA},
        "candidate_identity": _IDENTITY_OUTPUT_SCHEMA,
        "dispositions": {"type": "array", "items": _DISPOSITION_OUTPUT_SCHEMA},
        "human_handoff": {
            "type": "object",
            "additionalProperties": False,
            "required": ["required", "reason"],
            "properties": {
                "required": {"type": "boolean"},
                "reason": {"type": ["string", "null"]},
            },
        },
    },
}
