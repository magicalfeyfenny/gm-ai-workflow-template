---
name: project-steward
description: Audit repository issues and pull requests and create bounded issues from concrete evidence without modifying code.
---

# Project steward

This is an audit and evidence-backed tracking procedure, not an implementation
workflow. Use [Issue authority](../../../GOVERNANCE.md#issue-authority) for
shared issue fields and assignment. Use
[Human-created changes](../../../GOVERNANCE.md#human-created-changes) when
interpreting human-owned work.

## Audit procedure

Inspect live issues and PRs, then report only:

- duplicates;
- issues without actionable acceptance criteria;
- PRs without linked issues;
- PRs labeled `work:blocked`;
- persistent CI failures;
- clearly abandoned or superseded tracking.
- obviously over-decomposed issue clusters
- issue acceptance criteria that prescribe technical machinery without an
  independent outcome
- stale blocker/dependency language
- tracking whose only purpose is an abstraction that no longer has a consumer

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
- Do not create issues to simplify over-decomposed issue clusters, fix
  over-prescribed technical machinery, or repair stale tracking or language
  unless the issue is explicitly requested.