"""Stable schema values for the bounded adversarial review contracts."""

from __future__ import annotations


class ReviewContractError(ValueError):
    """Validation failure with optional bounded output-diagnostic classification."""

    def __init__(
        self,
        message: str,
        *,
        validation_stage: str | None = None,
        diagnostic_code: str | None = None,
        diagnostic_detail_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.validation_stage = validation_stage
        self.diagnostic_code = diagnostic_code
        self.diagnostic_detail_code = diagnostic_detail_code


REVIEW_PACKET_SCHEMA = "adversarial-review-packet:v5"
REVIEW_RESULT_SCHEMA = "adversarial-review-result:v3"
ADJUDICATION_PACKET_SCHEMA = "adversarial-adjudication-packet:v3"
ADJUDICATION_RESULT_SCHEMA = "adversarial-adjudication-result:v4"
SESSION_FAILURE_SCHEMA = "adversarial-review-session-failure:v3"
SESSION_FAILURE_CLASSES = (
    "startup",
    "sandbox",
    "authentication",
    "provider-unclassified",
    "timeout",
    "invalid-output",
)
SESSION_FAILURE_VALIDATION_STAGES = ("parse", "shape", "semantic")
SESSION_FAILURE_DIAGNOSTIC_CODES = (
    "output_json_parse",
    "output_event_stream_encoding",
    "output_read_failure",
    "output_missing_file",
    "output_top_level_shape",
    "output_schema",
    "output_missing_required_field",
    "output_unsupported_field",
    "output_unsupported_value",
    "output_contract_validation",
    "review_candidate_identity_mismatch",
    "review_issue_revision_mismatch",
    "review_finding_contract",
    "review_evidence_reference",
    "adjudication_candidate_identity_mismatch",
    "adjudication_issue_revision_mismatch",
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
)
RISK_TIERS = ("low", "medium", "high")
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
    "required": [
        "schema",
        "issue_contract_revision",
        "candidate_identity",
        "findings",
    ],
    "properties": {
        "schema": {"type": "string", "const": REVIEW_RESULT_SCHEMA},
        "issue_contract_revision": {"type": "string"},
        "candidate_identity": _IDENTITY_OUTPUT_SCHEMA,
        "findings": {"type": "array", "items": _FINDING_OUTPUT_SCHEMA},
    },
}

_CORRECTION_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": {
        "summary": {"type": "string"},
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
        "issue_contract_revision",
        "candidate_identity",
        "dispositions",
        "human_handoff",
    ],
    "properties": {
        "schema": {"type": "string", "const": ADJUDICATION_RESULT_SCHEMA},
        "issue_contract_revision": {"type": "string"},
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


def _review_runtime():
    """Load packet primitives after the review module has finished importing."""
    try:
        from . import adversarial_review as review
    except ImportError:  # pragma: no cover - direct script compatibility
        import adversarial_review as review  # type: ignore[no-redef]
    return review


def _tag_output_error(
    error: ReviewContractError,
    *,
    stage: str = "semantic",
    code: str = "output_contract_validation",
) -> ReviewContractError:
    if error.validation_stage is None:
        error.validation_stage = stage
        error.diagnostic_code = code
    return error


def validate_review_result(
    result: Mapping[str, object], packet: Mapping[str, object]
) -> dict:
    """Validate reviewer output against the frozen candidate and packet."""
    review = _review_runtime()
    validated_packet = review.validate_review_packet(packet)
    try:
        copied = review._copy_json(result, "review result")
        review._reject_forbidden_keys(copied, "review result")
        raw = review._mapping(copied, "review result", structured_output=True)
        fields = ("schema", "issue_contract_revision", "candidate_identity", "findings")
        review._keys(raw, fields, fields, "review result", structured_output=True)
        if raw["schema"] != REVIEW_RESULT_SCHEMA:
            raise ReviewContractError(
                "review result has an unsupported schema",
                validation_stage="shape",
                diagnostic_code="output_unsupported_value",
            )
        revision = validated_packet["issue_contract"]["revision"]
        if raw["issue_contract_revision"] != revision:
            raise ReviewContractError(
                "review result targets a different issue contract revision",
                validation_stage="semantic",
                diagnostic_code="review_issue_revision_mismatch",
            )
        expected = review.candidate_identity(validated_packet["candidate"])
        if review._identity(raw["candidate_identity"]) != expected:
            raise ReviewContractError(
                "review result targets a different candidate",
                validation_stage="semantic",
                diagnostic_code="review_candidate_identity_mismatch",
            )
        findings = review.validate_findings(raw["findings"])
        authorized_ids = review.evidence_ids(validated_packet)
        for index, finding in enumerate(findings):
            missing = sorted(set(finding["supporting_evidence"]) - authorized_ids)
            if missing:
                raise ReviewContractError(
                    f"review finding {index} cites unsupported evidence IDs: "
                    + ", ".join(missing),
                    validation_stage="semantic",
                    diagnostic_code="review_evidence_reference",
                )
        return {
            "schema": REVIEW_RESULT_SCHEMA,
            "issue_contract_revision": revision,
            "candidate_identity": expected,
            "findings": findings,
        }
    except ReviewContractError as exc:
        _tag_output_error(exc)
        raise


def _correction(value: object, subject: str, review) -> dict:
    raw = review._mapping(value, subject)
    review._keys(raw, ("summary",), ("summary",), subject, structured_output=True)
    return {"summary": review._string(raw["summary"], f"{subject}.summary")}


def validate_adjudication_result(
    result: Mapping[str, object], packet: Mapping[str, object]
) -> dict:
    """Validate dispositions and return no raw reviewer findings."""
    review = _review_runtime()
    adjudication_packet = review.validate_adjudication_packet(packet)
    try:
        copied = review._copy_json(result, "adjudication result")
        review._reject_forbidden_keys(copied, "adjudication result")
        raw = review._mapping(copied, "adjudication result", structured_output=True)
        fields = (
            "schema", "issue_contract_revision", "candidate_identity",
            "dispositions", "human_handoff",
        )
        review._keys(raw, fields, fields, "adjudication result", structured_output=True)
        if raw["schema"] != ADJUDICATION_RESULT_SCHEMA:
            raise ReviewContractError(
                "adjudication result has an unsupported schema",
                validation_stage="shape",
                diagnostic_code="output_unsupported_value",
            )
        revision = adjudication_packet["issue_contract_revision"]
        if raw["issue_contract_revision"] != revision:
            raise ReviewContractError(
                "adjudication result targets a different issue contract revision",
                validation_stage="semantic",
                diagnostic_code="adjudication_issue_revision_mismatch",
            )
        identity = review._identity(raw["candidate_identity"])
        if identity != adjudication_packet["candidate_identity"]:
            raise ReviewContractError(
                "adjudication result targets a different candidate",
                validation_stage="semantic",
                diagnostic_code="adjudication_candidate_identity_mismatch",
            )

        handoff = review._mapping(raw["human_handoff"], "adjudication human handoff")
        handoff_fields = ("required", "reason")
        review._keys(handoff, handoff_fields, handoff_fields, "adjudication human handoff")
        if not isinstance(handoff["required"], bool):
            raise ReviewContractError("adjudication human handoff.required must be boolean")
        reason = handoff["reason"]
        if handoff["required"]:
            reason = review._string(reason, "adjudication human handoff.reason")
        elif reason is not None and (not isinstance(reason, str) or reason.strip()):
            raise ReviewContractError("a non-required handoff must have a null or empty reason")

        raw_dispositions = raw["dispositions"]
        if not isinstance(raw_dispositions, list):
            raise ReviewContractError("adjudication dispositions must be a list")
        findings = adjudication_packet["findings"]
        if len(raw_dispositions) != len(findings):
            raise ReviewContractError(
                "every finding must receive exactly one disposition",
                validation_stage="semantic",
                diagnostic_code="adjudication_disposition_contract",
                diagnostic_detail_code="adjudication_disposition_count",
            )

        expected_ids = [finding["finding_id"] for finding in findings]
        normalized_dispositions = []
        disposition_fields = (
            "finding_id", "disposition", "basis", "correction", "correction_accepted",
        )
        for index, value in enumerate(raw_dispositions):
            subject = f"adjudication disposition {index}"
            disposition = review._mapping(value, subject)
            review._keys(disposition, disposition_fields, disposition_fields, subject)
            finding_id = review._string(disposition["finding_id"], f"{subject}.finding_id")
            if finding_id != expected_ids[index]:
                raise ReviewContractError(
                    "adjudication disposition order does not match findings",
                    validation_stage="semantic",
                    diagnostic_code="adjudication_disposition_contract",
                    diagnostic_detail_code="adjudication_disposition_order",
                )
            decision = review._string(disposition["disposition"], f"{subject}.disposition")
            if decision not in DISPOSITIONS:
                raise ReviewContractError(
                    f"{subject}.disposition must be one of {', '.join(DISPOSITIONS)}",
                    validation_stage="semantic",
                    diagnostic_code="adjudication_disposition_contract",
                    diagnostic_detail_code="adjudication_disposition_value",
                )
            correction_value = disposition["correction"]
            correction = None
            if decision in {"blocker", "patch-now"}:
                if correction_value is None:
                    if decision != "blocker" or not handoff["required"]:
                        raise ReviewContractError(
                            f"{subject} needs a current-pass correction or a human handoff",
                            validation_stage="semantic",
                            diagnostic_code="adjudication_correction_contract",
                            diagnostic_detail_code="adjudication_correction_required_missing",
                        )
                else:
                    correction = _correction(correction_value, f"{subject}.correction", review)
            elif correction_value is not None:
                raise ReviewContractError(
                    f"{subject} cannot change the candidate for {decision}",
                    validation_stage="semantic",
                    diagnostic_code="adjudication_correction_contract",
                    diagnostic_detail_code="adjudication_correction_on_non_mutating_disposition",
                )
            accepted = disposition["correction_accepted"]
            if not isinstance(accepted, bool):
                raise ReviewContractError(f"{subject}.correction_accepted must be boolean")
            if accepted != (correction is not None):
                raise ReviewContractError(
                    f"{subject}.correction_accepted does not match correction",
                    validation_stage="semantic",
                    diagnostic_code="adjudication_correction_contract",
                    diagnostic_detail_code="adjudication_correction_acceptance_mismatch",
                )
            normalized_dispositions.append({
                "finding_id": finding_id,
                "disposition": decision,
                "basis": review._string(disposition["basis"], f"{subject}.basis"),
                "correction": correction,
                "correction_accepted": accepted,
            })
        return {
            "schema": ADJUDICATION_RESULT_SCHEMA,
            "issue_contract_revision": revision,
            "candidate_identity": identity,
            "dispositions": normalized_dispositions,
            "human_handoff": {"required": handoff["required"], "reason": reason},
        }
    except ReviewContractError as exc:
        _tag_output_error(exc)
        raise
