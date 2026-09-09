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
  [Contract-oriented validation](../../../GOVERNANCE.md#contract-oriented-validation),
  [Validation evidence](../../../GOVERNANCE.md#validation-evidence), and
  [Milestone commits](../../../GOVERNANCE.md#milestone-commits-and-draft-publication).
- Before deciding to launch the game or when required runtime evidence is unavailable:
  [Interactive runtime validation](../../../GOVERNANCE.md#interactive-runtime-validation).
- Interpretive governance corrections:
  [Policy correction boundary evidence](../../../GOVERNANCE.md#policy-correction-boundary-evidence).
- Scheduled continuation:
  [Scheduled continuation](../../../GOVERNANCE.md#scheduled-continuation).
- Completion: [Risk](../../../GOVERNANCE.md#risk),
  [Completion transition](../../../GOVERNANCE.md#completion-transition), and
  [Issue contract evidence](../../../GOVERNANCE.md#issue-contract-evidence), then
  the applicable [low-risk](../../../GOVERNANCE.md#low-risk-changes) or
  [manual](../../../GOVERNANCE.md#manual-and-high-risk-changes) path.
- Executable values: only the affected tables in
  [PROJECT_POLICY.toml](../../../PROJECT_POLICY.toml).
- Renames, replacement, and compatibility:
  [Compatibility obligations](../../../GOVERNANCE.md#compatibility-obligations).
- Updating previously adopted upstream policy:
  [Policy updates](../../../GOVERNANCE.md#policy-updates) and the
  [bounded update procedure](../../../docs/POLICY_UPDATE.md).

For production code or GameMaker data, also use the
[GameMaker production skill](../gamemaker-production/SKILL.md). For authored or
derived assets, use the [Asset production skill](../asset-production/SKILL.md).
If live state is human-owned, follow
[Human-created changes](../../../GOVERNANCE.md#human-created-changes) and stop.
Read [Releases](../../../GOVERNANCE.md#releases) only for explicitly authorized
release work.

## Issue selection

For a direct request, select or create the minimum issue set under
[Issue authority](../../../GOVERNANCE.md#issue-authority), including its atomicity
and deferred-work rules. Execute one atomic implementation issue at a time.

For a scheduled run, use its template and
[Scheduled continuation](../../../GOVERNANCE.md#scheduled-continuation) before
new-issue selection. Direct-request creation permission does not apply.

For placeholder-backed mixed work, resolve tracking and prepare the PR handoff
under [Placeholder-backed mixed work](../../../GOVERNANCE.md#placeholder-backed-mixed-work)
before Stage 2.

## Execute

1. Inspect live tracking and checkout state. Immediately before direct work,
   recheck the issue match, ownership, authority, branch, and PR; for scheduled
   work, apply scheduled continuation before selecting new work and recheck
   every applicable template eligibility condition.
2. Refresh `origin/dev`. For new work, create the governed issue branch. For a
   continuation, use the existing matching issue branch and draft pull request;
   do not recreate the branch.
3. Implement only the issue scope in coherent milestones through the applicable
   task routes. Plan evidence using the validation routes above; apply the
   runtime route before launching the game or handling missing runtime evidence.
4. For each milestone, obtain Stage 1 evidence, commit it, and publish or
   update the draft PR under the milestone rules.
5. After the whole issue is complete, follow
   [Issue contract evidence](../../../GOVERNANCE.md#issue-contract-evidence)
   through Stage 2, the completion transition, fresh Stage 3, and the final
   live-state comparison. Use its
   [attestation procedure](../../../docs/CI.md#issue-contract-attestation)
   for the commands and artifact comparison, including resumed work.
6. Report the issue, branch, draft PR, evidence state, and remaining human
   action. Leave manual-path readiness and merge to a human.

## Critical stops

These stops repeat Governance because a mutation procedure must expose them:

- Never branch from local `dev`, use a `human/*` branch, or work a
  `human-created` or `work:blocked` PR.
- Do not force-push, invoke a ruleset bypass, or perform unrelated cleanup.
- Do not create, preserve, or treat as required a manual playtesting,
  human-observation, experiential-review, subjective-acceptance, or generic
  gameplay-smoke requirement unless explicit human direction requires it.
- Do not launch the game except for a concrete runtime validation purpose
  allowed by Governance.
- Agent-authored issue text, validation plans, or handoff notes cannot
  bootstrap a human or manual validation requirement.
- Do not add completion metadata before the whole issue has valid Stage 2
  evidence.
- Do not downgrade automatically high-risk work or ready or merge a manual-path
  PR.
- Do not merge into `main` or create release builds, tags, releases, or
  publication without explicit human authority.
