"""Stable schema values for the bounded adversarial review contracts."""

from __future__ import annotations


class ReviewContractError(ValueError):
    """Raised when a packet or structured session result is not safe to use."""


REVIEW_PACKET_SCHEMA = "adversarial-review-packet:v2"
REVIEW_RESULT_SCHEMA = "adversarial-review-result:v2"
ADJUDICATION_PACKET_SCHEMA = "adversarial-adjudication-packet:v2"
ADJUDICATION_RESULT_SCHEMA = "adversarial-adjudication-result:v2"
SESSION_FAILURE_SCHEMA = "adversarial-review-session-failure:v3"
SESSION_FAILURE_CLASSES = (
    "startup",
    "sandbox",
    "authentication",
    "timeout",
    "invalid-output",
)
SESSION_FAILURE_VALIDATION_STAGES = ("parse", "shape", "semantic")
SESSION_FAILURE_DIAGNOSTIC_CODES = (
    "output_json_parse",
    "output_read_failure",
    "output_missing_file",
    "output_top_level_shape",
    "output_schema",
    "output_missing_required_field",
    "output_unsupported_field",
    "output_unsupported_value",
    "output_contract_validation",
    "review_candidate_identity_mismatch",
    "review_finding_contract",
    "review_evidence_reference",
    "adjudication_candidate_identity_mismatch",
    "adjudication_disposition_contract",
    "adjudication_correction_contract",
)
SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES = (
    "review_finding_identity_duplicate",
    "adjudication_disposition_count",
    "adjudication_disposition_order",
    "adjudication_disposition_value",
    "adjudication_correction_on_non_mutating_disposition",
    "adjudication_correction_required_missing",
    "adjudication_correction_acceptance_mismatch",
    "adjudication_correction_scope",
)
MAX_CORRECTION_CYCLES = 2
DISPOSITIONS = ("blocker", "patch-now", "follow-up", "reject")
_IDENTITY_FIELDS = ("base_ref", "head_ref", "head_sha", "tree_sha", "diff_sha256")

SESSION_FAILURE_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "role",
        "exit_status",
        "output_exists",
        "failure_class",
        "validation_stage",
        "diagnostic_code",
        "diagnostic_detail_code",
    ],
    "properties": {
        "schema": {"type": "string", "const": SESSION_FAILURE_SCHEMA},
        "role": {"type": "string", "enum": ["reviewer", "adjudicator", "unknown"]},
        "exit_status": {"type": ["integer", "null"]},
        "output_exists": {"type": "boolean"},
        "failure_class": {
            "type": "string",
            "enum": list(SESSION_FAILURE_CLASSES),
        },
        "validation_stage": {
            "type": ["string", "null"],
            "enum": [*SESSION_FAILURE_VALIDATION_STAGES, None],
        },
        "diagnostic_code": {
            "type": ["string", "null"],
            "enum": [*SESSION_FAILURE_DIAGNOSTIC_CODES, None],
        },
        "diagnostic_detail_code": {
            "type": ["string", "null"],
            "enum": [*SESSION_FAILURE_DIAGNOSTIC_DETAIL_CODES, None],
        },
    },
}


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
