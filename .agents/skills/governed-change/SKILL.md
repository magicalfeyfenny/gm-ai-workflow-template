---
name: governed-change
description: Execute one repository change through issue, branch, validation, draft PR, and allowed merge policy.
---

# Governed change

Use this skill for a direct governed request. A scheduled run also uses it,
with the narrower selection and authority in its automation template.

## Routes

- Start: [Issue authority](../../../GOVERNANCE.md#issue-authority),
  [Branches](../../../GOVERNANCE.md#branches), and
  [Unit of work](../../../GOVERNANCE.md#unit-of-work).
- Asset authority and replacement:
  [Asset completion and authority](../../../GOVERNANCE.md#asset-completion-and-authority).
- Placeholder-backed mixed implementation:
  [Placeholder-backed mixed work](../../../GOVERNANCE.md#placeholder-backed-mixed-work).
- Validation planning, evidence, and publication:
  [Validation coverage allocation](../../../GOVERNANCE.md#validation-coverage-allocation),
  [Manual and live validation availability](../../../GOVERNANCE.md#manual-and-live-validation-availability),
  [Validation evidence](../../../GOVERNANCE.md#validation-evidence), and
  [Milestone commits](../../../GOVERNANCE.md#milestone-commits-and-draft-publication).
- Scheduled continuation:
  [Scheduled continuation](../../../GOVERNANCE.md#scheduled-continuation).
- Completion: [Risk](../../../GOVERNANCE.md#risk),
  [Completion transition](../../../GOVERNANCE.md#completion-transition), and
  the applicable [low-risk](../../../GOVERNANCE.md#low-risk-changes) or
  [manual](../../../GOVERNANCE.md#manual-and-high-risk-changes) path.
- Executable values: only the affected tables in
  [PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml).

For production code, assets, or GameMaker data, also use the
[GameMaker production skill](../gamemaker-production/SKILL.md). If live state
is human-owned, follow
[Human-created changes](../../../GOVERNANCE.md#human-created-changes) and stop.
Read [Releases](../../../GOVERNANCE.md#releases) only for explicitly authorized
release work.

## Issue selection

For a direct request, use or create only the atomic issue or linked issue set
authorized by Issue authority, then execute one atomic implementation issue at
a time. Use or create the minimum issue set necessary to represent the 
requested outcomes. Prefer one vertical implementation issue when multiple 
technical layers are jointly necessary for one outcome. Do not create 
downstream issues merely for potential generalization, hardening, versioning,
characterization, or future extension.

For a scheduled run, follow its template and the
[Scheduled continuation](../../../GOVERNANCE.md#scheduled-continuation) route:
direct-request creation does not apply, and no eligible issue or actionable
continuation means no repository mutation.

Deferred work is not automatically backlog work. Create a follow-up issue
only for an explicit requested outcome, a concrete defect/risk that should be
tracked, or a blocker that cannot remain in the current issue.

For placeholder-backed mixed work, resolve the canonical final-asset follow-up
required by Governance before Stage 2. Record the exact placeholder scope,
replacement point, and issue link in the draft pull request without claiming
that the placeholder satisfies authored-asset acceptance.

## Execute

1. Inspect live tracking and checkout state. Immediately before direct work,
   recheck the issue match, ownership, authority, branch, and PR; for scheduled
   work, apply scheduled continuation before selecting new work and recheck
   every applicable template eligibility condition.
2. Refresh `origin/dev`. For new work, create the governed issue branch. For a
   continuation, use the existing matching issue branch and draft pull request;
   do not recreate the branch.
3. Implement only the issue scope in coherent milestones through any additional
   task route above, allocating automated and manual or live validation through
   the Governance route above. If required manual or live evidence is
   unavailable, follow its availability route and leave completion pending.
4. For each milestone, obtain Stage 1 evidence, commit it, and publish or
   update the draft PR under the milestone rules.
5. After the whole issue is complete, obtain Stage 2 evidence for the unchanged
   candidate, perform the applicable completion transition, and obtain fresh
   Stage 3 evidence.
6. Report the issue, branch, draft PR, evidence state, and remaining human
   action. Leave manual-path readiness and merge to a human.

## Critical stops

These stops repeat Governance because a mutation procedure must expose them:

- Never branch from local `dev`, use a `human/*` branch, or work a
  `human-created` or `work:blocked` PR.
- Do not force-push, invoke a ruleset bypass, or perform unrelated cleanup.
- Do not use automated evidence as a substitute for required manual or live
  observation; preflight interactive desktop validation where practical and
  stop before completion when the required observation is unavailable.
- Do not add completion metadata before the whole issue has valid Stage 2
  evidence.
- Do not downgrade automatically high-risk work or ready or merge a manual-path
  PR.
- Do not merge into `main` or create release builds, tags, releases, or
  publication without explicit human authority.
