---
name: project-steward
description: Audit repository issues and pull requests and create bounded issues from concrete evidence without modifying code.
---

# Project steward

This is an audit and evidence-backed tracking procedure, not an implementation
workflow. Use [Issue authority](../../../GOVERNANCE.md#issue-authority) for
shared issue fields and assignment. When authoring or auditing feature-specific
validation, use
[Validation coverage allocation](../../../GOVERNANCE.md#validation-coverage-allocation)
and [Interactive runtime validation](../../../GOVERNANCE.md#interactive-runtime-validation).
Use
[Human-created changes](../../../GOVERNANCE.md#human-created-changes) when
interpreting human-owned work.
When authoring or auditing asset-production tracking, follow
[Asset completion and authority](../../../GOVERNANCE.md#asset-completion-and-authority)
and
[Placeholder-backed mixed work](../../../GOVERNANCE.md#placeholder-backed-mixed-work).
When authoring or auditing compatibility, migration, alias, normalization, or
legacy requirements, follow
[Compatibility obligations](../../../GOVERNANCE.md#compatibility-obligations).
When auditing GameMaker implementation or runtime asset choices, follow
[Native GameMaker functionality](../../../GOVERNANCE.md#native-gamemaker-functionality)
and [Runtime asset representation](../../../GOVERNANCE.md#runtime-asset-representation).

## Audit procedure

Inspect live issues and PRs, then report only:

- duplicates;
- issues without actionable acceptance criteria;
- PRs without linked issues;
- PRs labeled `work:blocked`;
- persistent CI failures;
- clearly abandoned or superseded tracking.
- obviously over-decomposed issue clusters
- acceptance criteria that prescribe technical machinery without an independent
  outcome, or contain implementation machinery, validation procedures, or 
  routine repository policy instead of independently required outcomes
- stale blocker/dependency language
- tracking whose only purpose is an abstraction that no longer has a consumer
- asset tracking whose only unresolved outcome is human review, approval,
  acceptance, or promotion of an existing authored asset rather than concrete
  remaining asset-production work
- compatibility or migration requirements that do not identify independent
  pre-work evidence for the consumer or durable contract they preserve
- custom substitutes without an established unmet native requirement, native
  facilities disabled or bypassed to preserve those substitutes, and engine
  semantics assumed from repository code or superficial resemblance
- externally authored assets routed to Included Files without a concrete runtime
  reason when an adequate native GameMaker resource would satisfy the contract
- agent-authored manual playtesting, generic gameplay smoke testing, human
  observation, experiential acceptance, readability or feel review, or
  subjective visual-review requirements that lack explicit human direction
  requiring that specific judgment

Create an issue only from:

- a reproducible untracked CI failure;
- an explicit `TODO(ISSUE)` marker;
- an explicit user-authored backlog item; or
- concrete evidence for a bounded repository-compliance issue from a merged
  human-created PR.

Search live tracking for duplicates before creating anything. Add the source
evidence to the shared issue fields and create no more than five issues per
run.

## Critical stops

- Do not modify code, branches, PR state, readiness, merges, releases, or
  publication.
- Do not treat an open human-created PR as a governance defect, and do not
  modify, review, validate, label, ready, or merge it.
- Do not close stale issues automatically or create speculative work.
- Do not create or retain cleanup work solely because custom systems or external
  runtime assets exist. Report unsupported decisions with their evidence and
  current contract context; implementation requires a current requested outcome,
  current issue, or independently established contract that requires a change.
- Do not create, recommend retaining, or treat as actionable tracking solely
  for human review, approval, acceptance, or promotion of an existing authored
  asset. Report it for human disposition without inventing production work or
  closing it automatically.
- Do not create issues to simplify over-decomposed issue clusters, fix
  over-prescribed technical machinery, or repair stale tracking or language
  unless the issue is explicitly requested.
- Do not create or retain manual playtesting, subjective review, human
  observation, experiential acceptance, or generic gameplay smoke requirements
  unless explicit human direction requires that specific judgment.
- Player-visible, runtime-affecting, visual, interactive, or high-risk work
  alone is not evidence that manual or human-observed validation is required.
- Prefer machine-verifiable validation requirements when authoring or auditing
  issues. Missing runner capability and human merge or publication gates do
  not authorize substitute human verification requirements.
