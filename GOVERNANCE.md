# Governance

## Authority

This document is the authoritative home for shared repository workflow,
rationale, permissions, and lifecycle rules.
[PROJECT_POLICY.toml](PROJECT_POLICY.toml) is the authoritative home for
configured executable values such as paths, asset formats, limits, and risk
patterns.

[AGENTS.md](AGENTS.md) is a task router and pre-mutation safety summary.
Repository skills own task-specific procedures and unique task constraints;
shared rules link here. The governance overview in [README.md](README.md) is
non-normative navigation. Setup documentation owns setup procedure, not
repository-change lifecycle policy.

Except for a critical stop that must be exposed before mutation, entrypoints
link here instead of restating shared rules. A repeated stop is a safety
reminder, not a second source of authority.

## Issue authority

Every issue created by an agent contains a summary, acceptance criteria,
bounded scope, and expected risk, and is assigned to the current user.
Feature-specific engineering constraints and validation may be included when
they materially clarify the completion contract.

Acceptance criteria describe the minimum product-visible or
integration-visible outcomes required to consider the issue complete. They
state what must be true of the completed outcome, not every property that may
be useful to implement or test.

Classify issue requirements as follows:

- Acceptance criteria describe required observable behavior, capability,
  integration results, or failure behavior. A criterion should normally remain
  valid if the implementation is replaced with a different implementation
  that provides the same outcome.
- Engineering constraints describe implementation properties that must be
  preserved, such as stable identities, determinism, ownership boundaries,
  lifecycle invariants, coordinate systems, compatibility requirements, or
  asset-authority rules.
- Validation describes evidence used to establish that the outcome and its
  constraints hold, such as automated tests and fixtures, representative
  manual or live playtests and captures, or other checks.
- Repository-wide policy requirements are not repeated as issue acceptance
  criteria merely because they apply to the work. The governed validation
  lifecycle and other applicable repository policy remain required without
  being copied into each issue.

An issue may include Engineering constraints and Validation sections when they
clarify feature-specific requirements. Omit those sections when the shared
repository rules and ordinary proportional validation are sufficient.

Do not make a statement an acceptance criterion merely because it is testable.
Prefer outcome requirements over implementation mechanisms. Promote a detail
to explicit acceptance criteria when it defines the requested outcome,
distinguishes a plausible but incorrect implementation, records a known
regression or important failure case, or expresses a requirement that cannot
safely be inferred.

Prefer concise outcome criteria over exhaustive permutations. Merge
equivalent lifecycle states and edge cases unless their differences create
distinct behavior or a known feature-specific risk. Keep validation plans out
of acceptance criteria and allocate their evidence under
[Validation coverage allocation](#validation-coverage-allocation).

An implementation issue defines one coherent, independently meaningful outcome
with one acceptance contract. Atomicity is measured by the product or
repository outcome, not by technical implementation layers.

Prefer one vertical issue containing the data, runtime behavior, integration,
tests, and documentation needed to deliver that outcome. Technical separability
alone is not a reason to split.

Split work when outcomes can be meaningfully accepted, deferred, prioritized,
shipped, rolled back, or reviewed independently, or when they require
materially different authority or risk handling. Separate schemas, validators,
adapters, runtime consumers, tests, documentation, or other implementation
layers are not independently meaningful merely because they can be implemented
separately.

Create the minimum issue set needed for the requested outcome. Do not
pre-expand speculative downstream work into a backlog.

A direct human request for governed repository work authorizes the
`governed-change` workflow to find or create only the atomic implementation
issue or linked atomic issue set needed for exactly that requested work. A
coordinating parent may be included only when useful for tracking. This
permission does not authorize speculative backlog work.

A scheduled Governed Change run selects only an existing eligible issue under
its automation contract. The direct-request permission above does not apply,
and the run must not create a replacement when no issue is eligible.

Project Steward owns evidence-backed issue creation for stewardship audits,
including scheduled audits. Its skill owns the audit-specific evidence and
per-run constraints. In scheduled operation, Project Steward owns issue
creation and does not implement issues.

### Scheduled claim eligibility

The scheduled Governed Change automation owns selection and claim decisions
for existing implementation issues. Project Steward continues to own audit,
tracking, and evidence-backed issue creation; it does not claim or execute
issues. Skills route scheduled work to the Governed Change automation template
instead of defining separate claim policies.

Before claiming an issue, compare its primary non-degradable deliverable with
the capabilities available in the current execution environment. The primary
non-degradable deliverable is the outcome that makes the issue independently
meaningful and cannot be deferred, substituted, or reduced without violating
its acceptance contract. The issue is eligible only when the environment has
the capabilities required to complete that deliverable. If capability is
unknown, fail closed and leave the issue available for a later capable run.

The ability to create, encode, convert, or procedurally construct a file in the
required runtime or source format does not by itself establish the capability
to author the requested asset. Eligibility depends on the environment being
capable of producing the asset form and quality required by the issue’s
acceptance contract.

When final authored assets are that deliverable, the issue is
ineligible if the environment lacks the required asset-authoring capability.
Eligibility is based on capability, not on a named runner, provider, model, or
generation mechanism.

Broader implementation work remains eligible when authored assets are
incidental and deterministic placeholders preserve meaningful implementation
progress without weakening the issue's acceptance contract. A placeholder is
scaffolding, not evidence for an acceptance criterion that explicitly requires
final production or authored assets.

This capability check composes with every other scheduled eligibility
condition, including issue atomicity, risk handling, dependency order, and the
fail-closed recheck immediately before repository mutation. It does not replace
or relax any of them.

### Placeholder-backed mixed work

A mixed implementation issue may use deterministic placeholders when final
authored assets are secondary and the current execution environment
lacks the capability to produce them. This is allowed only when the placeholder
preserves an independently meaningful primary outcome and the issue's existing
acceptance contract permits the final asset to be deferred. It does not make an
asset-primary issue eligible.

Keep every placeholder explicitly identified as non-production scaffolding in
the implementation and pull-request handoff. Preserve the intended gameplay,
UI, or runtime integration point so the final authored asset can replace the
placeholder without recreating completed implementation work.

A placeholder never satisfies an acceptance criterion that requires a final
authored or production asset. If the current issue still contains such a
criterion, the issue remains incomplete; linking a follow-up does not make that
criterion complete.

When the implementation issue can complete independently and only the
separable final-asset deliverable remains, resolve its tracking before the
implementation issue completes:

1. Search live tracking for an appropriate canonical asset issue. Link the
   original issue and pull request to that issue, updating it only as needed to
   identify the remaining authored-asset deliverable and replacement point.
2. If no appropriate issue exists, create exactly one narrow follow-up assigned
   to the current user. Reference the original issue and pull request, own only
   the unresolved authored-asset replacement and its asset-specific validation,
   and exclude implementation scope already completed with the placeholder.
3. Record the canonical follow-up link and the exact placeholder scope and
   replacement point in the original pull-request handoff.

This required follow-up is part of completing the selected mixed issue, not
permission to generate a general backlog. A scheduled execution may create it
only after claiming that issue and only under the rules above. The follow-up
uses the normal issue-authority, dependency, and risk rules for its own scope.

### Scheduled continuation

Before selecting a new issue, a scheduled Governed Change run checks for an
existing incomplete governed change owned by the current automation user. A
valid continuation has an open issue assigned to that user, its matching
issue-numbered `work/<issue>-<slug>` branch, and its draft pull request. The
issue and pull request must still pass the normal ownership, dependency,
blocker, and human-authority checks. The capability check still applies to any
remaining primary non-degradable deliverable; an unavailable environment
needed only for required manual or live evidence is handled by the validation
availability rule and does not invalidate the continuation. A human-created
branch or pull request and a `work:blocked` change are never continuations.
The draft pull request must not already have a completion line or completion
label; a `work:complete` or `work:review-ready` pull request follows its normal
completion path instead of being resumed as incomplete work.

When a valid continuation exists, resume its next incomplete implementation or
validation milestone on that branch and draft pull request before selecting
new work only when the current environment can make meaningful progress on at
least one remaining implementation or validation milestone. A continuation
that can only wait for unavailable manual or live evidence, an unavailable
interactive desktop, or required human action is pending rather than
actionable; leave it pending and allow the run to select at most one new
eligible issue. Do not repeatedly retry an unavailable GUI or alter the
pending continuation just to make progress appear possible.

A continuation does not make an asset-primary issue eligible when its remaining
primary deliverable still needs an unavailable capability. When the required
environment becomes available, or the required human action is resolved, the
continuation becomes actionable and takes priority again. Resume the missing
manual or live observation and then follow the ordinary completion transition.

Do not create a replacement issue for a pending continuation. If no actionable
continuation exists, the run may select at most one new eligible issue under
the ordinary scheduled claim rules.

## Asset completion and authority

These rules apply to repository-owned authored assets across visual, audio, 3D,
and animation work, including assets kept in source files, runtime outputs, or
engine-native resources.

### Completion levels

Asset completion levels are ordered by completion commitment:

1. `deterministic-placeholder` is reproducible scaffolding that is explicitly
   non-production.
2. `authored-placeholder` has authorial or source commitment but has not been
   accepted as the final production asset.
3. `final` is an asset explicitly accepted as final by human authorial
   authority.

Authorship, source authority, provenance, and completion level are independent.
An editable source, a named author, or a human-authored asset does not by
itself make an asset final, and a generated file does not become a permitted
deterministic placeholder merely because it is simple or easy to reproduce.
The level records completion and replacement authority; it is not a judgment
based on asset quality alone.

When this policy is adopted, repository-owned sprites and other authored
visual, audio, 3D, and animation assets already present are
`authored-placeholder` by default unless human authority explicitly marks them
as another level. Agents must not infer `deterministic-placeholder` from age,
simplicity, low detail, temporary appearance, or missing provenance.

### Replacement and promotion

When the current issue authorizes work on an asset, normal agent work may
replace a non-final asset only with an asset at the same or a higher completion
level. An agent must not replace an asset with a lower level; in particular,
`deterministic-placeholder` must not replace `authored-placeholder`.

Agents must not replace, overwrite, restyle, or regenerate a `final` asset
without explicit human authorization, even when the proposed result appears
more polished or technically superior. Promotion to `final` is human-authority
only. Asset quality alone does not promote an asset, and an
`authored-placeholder` remains a placeholder until human authority explicitly
accepts it as final.

## Branches

`dev` is the default integration branch.

`main` is release-only.

At repository bootstrap, `main` may point to the initial pre-release bootstrap
commit. After the first release, the tree at `main` must match the source tree
used for the most recent release.

Normal work branches:

work/<issue>-<slug>

Release branches:

release/<issue>-v<semver>

Human-created branches:

human/<slug>

The `human/` namespace is reserved for work created and controlled by a human.

Every agent-governed work or release branch starts from current `origin/dev`.

Never branch from a local `dev`.

## Unit of work

Each atomic implementation issue independently uses:

1. one GitHub issue;
2. one issue-numbered branch;
3. coherent milestone commits;
4. one draft pull request opened with the first meaningful commit;
5. required CI;
6. merge according to the risk policy.

The issue number must match the branch name and completion metadata.

A coordinating parent does not use an implementation branch or pull request;
it tracks its atomic sub-issues. Dependencies may order sub-issues but do not
combine their scopes.

Keep the change bounded to that issue and do not absorb unrelated cleanup.
Preserve useful behavior, not obsolete architecture merely because it exists.

### Contract-oriented validation

Tests and automated policy checks should validate required behavior, structure,
and repository contracts rather than incidental wording or representation.

Prefer assertions about semantic requirements over exact prose, formatting,
field order, counts, serialized text, or other incidental representation.

Exact-representation assertions are appropriate only when that exact
representation is explicitly part of the contract, such as a documented
compatibility interface, protocol grammar, required identifier, checksum, or
other externally fixed value. Do not infer that representation is contractual
merely because code, tests, tools, or automation consume it.

When a semantic assertion can establish the governed requirement, use the
semantic assertion.

A wording, formatting, ordering, or representation change that preserves the
intended contract should not require unrelated test changes merely to satisfy
stale textual expectations.

### Validation coverage allocation

Allocate validation coverage according to risk, contract relevance, and what
each form of evidence can establish. Automated and manual or live validation
have complementary responsibilities; neither is a blanket substitute for the
other.

When numeric, combinatorial, deterministic, or state-transition behavior is
contract-relevant and practical to assert mechanically, prefer automated
validation for the exhaustive relevant state space. Automated invariant
coverage should replace manual repetition of every ship, difficulty, rank,
state, or similar machine-testable combination. Do not require exhaustive
automated matrices when the combinations are meaningless, intractable,
redundant, or outside the contract.

Use manual or live validation to sample a small, risk-appropriate set of cases
for qualities that automated assertions cannot adequately establish. Check
representative player-visible behavior and integration, visual readability and
accessibility, timing and feel, interaction, and tool or engine behavior. As
applicable, sample baseline, typical or midpoint, edge, and highest-pressure
cases. These are selection dimensions, not a universal checklist or fixed
sample count. Preserve additional manual coverage for known cross-state risks
or any genuinely visual, interactive, timing-sensitive, accessibility,
readability, integration, or tool and engine outcome that remains unproven
mechanically.

Issue acceptance criteria state required outcomes. Feature-specific validation
plans choose this allocation and record the evidence needed without expanding
the criteria into a large coverage matrix. Manual or live samples may traverse
states already covered by automation to judge different qualities, but they do
not need to repeat the complete machine-tested state space.

This allocation operates inside the existing validation stages. It does not
remove required Stage 1 checks or the full Stage 2 suite, weaken Stage 3 hosted
evidence, change risk classification, or replace required human review.

### Manual and live validation availability

Automated evidence and manual or live evidence establish different facts. Do
not use automated tests, headless checks, or source inspection as a substitute
for required manual or live observation.

For GUI or GameMaker validation, preflight interactive desktop availability
where practical. If the desktop or required interactive tool is unavailable,
record that environment blocker and avoid repeated GUI launch attempts.

When required manual or live evidence is unavailable after practical preflight,
the agent may continue coherent implementation work and collect the automated
evidence that is available. It may commit, push, and update the draft pull
request, but it must stop before adding completion metadata or claiming the
issue complete. The handoff must identify the exact missing observation and
the environment condition that prevented it. The missing evidence remains
required and must be obtained before the ordinary completion transition.

## Validation evidence

Agent-governed work uses three separate repository-change validation stages.
Evidence from one stage does not replace another.

### Stage 1: milestone evidence

Before each coherent milestone commit, run narrow, proportionate checks for
the files and behavior changed by that milestone. Include relevant GameMaker
tests when available. This evidence supports the milestone commit and draft
publication only; it does not establish that the whole issue is complete.

### Stage 2: whole-issue local evidence

After the entire issue scope is complete, run the following on one unchanged
repository-content candidate before adding completion metadata or making a
final handoff:

- `python3.12 tools/ci/check_repo.py --baseline-ref origin/dev`;
- relevant tests, including relevant GameMaker tests when available;
- `python3.12 -m unittest discover -s tools/tests -p 'test_*.py'`;
- `git diff --check`.

This evidence applies to the exact candidate tree that was checked. Committing
that same tree does not invalidate it. A later repository-content change
requires affected Stage 1 checks again and, if Stage 2 had already passed, the
complete Stage 2 suite on the new candidate. Do not repeat Stage 2 while the
candidate tree remains unchanged.

### Stage 3: hosted PR evidence

After the final head, body, and labels are in place, all required checks under
CI must pass for that exact head and the attested policy-relevant PR metadata.
Missing, failed, invalid, or stale evidence does not satisfy this stage.

A head change invalidates Stage 3. Changing only the PR body or labels leaves
local evidence valid but invalidates Stage 3, so obtain fresh hosted evidence
without rerunning the local suite.

No validation stage changes risk classification or grants completion,
readiness, review, merge, release, or publication authority. Those actions
remain governed by the paths below.

## Milestone commits and draft publication

Agents may commit to their current issue-scoped branch without separate human
authorization. Create a commit as soon as a coherent milestone is complete and
has received Stage 1 milestone evidence. Do not leave a completed milestone
only in the working tree while waiting for the entire issue to finish.

Push the first meaningful milestone commit and open its draft PR immediately.
This permission applies to low- and high-risk work. Continue committing and
pushing later coherent milestones to the same draft PR.

A commit, push, or draft PR does not grant readiness or merge authority.
High-risk and `manual-merge` PRs remain manual under the rules below.

`work:blocked` retains the former `blocked` behavior: the PR cannot be worked
until its blockers are resolved. While it is present, omit the closing line and
both completion labels.

## Human-created changes

A same-repository PR from `human/<slug>` is automatically labeled:

- `human-created`;
- `manual-merge`.

A human may also apply `human-created` to identify human work that did not use
the reserved branch prefix.

Human-created PRs are exempt from the agent-governed issue, branch, closure,
draft, risk-label, and passing-check procedures. Checks may still run, but
their results are informational. A repository administrator manually merges
the PR by selecting GitHub's pull-request ruleset bypass.

Ruleset bypass is actor-based rather than label-based. It may be used only for
a `human-created` PR. It does not permit direct pushes to protected branches.

Agents must not create, modify, review, validate, label, mark ready, merge, or
otherwise work a human-created branch or PR.

After a human-created change merges, divergence from current repository
standards is not automatically a defect. The result may inform desired patterns
or algorithms. Existing policy violations are treated as the repository
baseline and do not block unrelated agent changes.

Human-authored work may be followed by a bounded repository-compliance issue.
That issue may normalize structure, validation, assets, tests, and repository
conventions without changing intended behavior. It uses the normal risk policy.

This exception does not automate release builds, tags, releases, or
publication.

## Risk

Every agent-governed PR has exactly one label:

- `risk:low`
- `risk:high`

Each atomic implementation issue states its own expected risk. Its PR is
classified from that issue's scope and the PR's actual changes and
circumstances. A coordinating parent's risk does not determine a sub-issue's
risk, and risk does not propagate between sub-issues.

A PR is automatically high risk if:

- it targets `main`;
- it changes a high-risk path from `PROJECT_POLICY.toml`;
- it exceeds the configured changed-file limit;
- it exceeds the configured changed-line limit.

Automatic high risk is exceptional. Configured path rules cover
authority-bearing governance, repository setup, CI and merge enforcement, and
asset-pipeline tooling. Ordinary production code, project metadata, structured
content, and source or runtime assets are not high risk merely because of their
domain. The size limits are backstops for genuinely massive structural changes,
not ordinary production scope.

Any change may be voluntarily classified high risk when its concrete behavior
or circumstances warrant human review. Consider blast radius, irreversibility,
security or compatibility risk, cross-system coupling, and unusual uncertainty
instead of using the file's domain as a proxy.

Automatically high-risk changes may not be downgraded.

## Completion transition

After the entire issue scope is finished and Stage 2 whole-issue local evidence
is valid, add exactly one `Closes #<issue>` line and the completion label
required by the applicable path below. The issue number must match the branch.
Use exactly one completion label; `work:complete` and `work:review-ready` must
not coexist. Do not add completion metadata to an intermediate milestone.

Obtain Stage 3 hosted PR evidence for the final head and completion metadata
before automation or final handoff.

## Low-risk changes

The low-risk completion label is `work:complete`.

After Stage 3 passes, a low-risk PR targeting `dev` with `work:complete` and
without `manual-merge` is automatically:

1. marked ready;
2. configured for squash auto-merge.

The `manual-merge` label disables both automatic readiness and auto-merge.

## Manual and high-risk changes

A PR uses the manual completion path when it is high risk or has
`manual-merge`. Its completion label is `work:review-ready`, meaning that
implementation is done and the PR is waiting for human review.

Manual-path PRs are never automatically marked ready or merged.

A high-risk PR is still committed, pushed, and published as a draft without
separate authorization.

A human must review the result, mark the PR ready, and merge it.

## Releases

All changes to `main` are high risk and manual.

A release:

1. starts from current `origin/dev`;
2. uses `release/<issue>-v<semver>`;
3. receives required CI;
4. receives a manually initiated release-candidate build;
5. is manually verified;
6. is manually merged into `main`;
7. is tagged from the resulting `main` commit;
8. receives its final build from that tag;
9. is manually published.

Tags, release builds, merges into `main`, and publication are never automatic.

After the first release, `main` changes only through release PRs.

## Derived assets

The `[assets]` and `[assets.pipelines.*]` tables in
[PROJECT_POLICY.toml](PROJECT_POLICY.toml) define the executable roots,
manifest path, supported source and runtime formats, and audio parameters.

Editable assets belong under the configured source root. Generated or
exported assets belong under the configured runtime root, and every tracked
derived runtime asset is mapped in the configured export manifest.

Each asset follows its named pipeline.

## GameMaker structured data

When file-backed structured content is justified by the project, store its
canonical representation once under the configured content root. Do not
introduce structured content merely because a concept can be represented as
data. Prefer GameMaker-native resources, placed instances, instance variables,
sequences, rooms, layers, and ordinary GML when they provide the simpler
authoring and runtime model.

Structured content should have one canonical representation. Validation
should exist at actual authoring, compatibility, or trust boundaries rather
than being duplicated along trusted internal paths.

## Production code

These requirements apply to repository-owned production code written or
changed by an agent. They do not apply to pinned, read-only imported-library
source. Preserve libraries under the imported-library policy below instead of
modifying them to match repository style.

Follow established project conventions and the language's ordinary style. Use
consistent formatting, descriptive names, and visible control flow.

Use the simplest design that reasonably satisfies current requirements, with
no more moving parts than the behavior needs. Do not add pass-through layers,
indirection, duplicate state, configuration, duplicated validation, or
speculative flexibility unless a current requirement, distinct trust boundary,
or separate failure mode needs them and cannot reasonably use any simpler or
already-existing design.

Make both the code path and the reason for taking it plain to a human reader.
Prefer direct control flow, concrete names, and explicit data. Establish an
invariant at the appropriate boundary; do not repeatedly check it along a
trusted path without a separate reason.

When necessary complexity or a non-obvious technique remains, explain why at
the narrowest useful boundary with a concise plain-English comment. A design
with many moving parts is maintainable only when the reason for them can be
explained.

Add a concise plain-English comment to public contracts, engine-lifecycle
assumptions, non-obvious intent, invariants, and necessary complexity. Comments
must accurately describe current behavior and intent without merely restating
the code. A function comment must limit its claims to behavior the function
actually implements. Do not use comments as a wishlist. Do not add comments
that merely restate obvious code.

Assume that "plain-English" means short, direct language understandable to a
middle-school reader when the subject permits it. Use technical or more complex
language only when it makes an important distinction clearer or more precise.
Unnecessary linguistic complexity is obfuscation, just as unnecessary
implementation complexity is, and must be avoided unless it is necessary and
justified by the outcome it serves.

## Source structure

A repository-owned source file has one primary responsibility.

Repository-owned source files may not use a stem listed in
`structure.forbidden_generic_stems` in
[PROJECT_POLICY.toml](PROJECT_POLICY.toml).

Repository-owned source files may not exceed the configured line limit. When a
file approaches the limit, split it by responsibility.

Pinned, read-only imported-library source is an exception. To preserve its
upstream bytes, list only the necessary exact repository-relative file paths in
`structure.large_file_exceptions` in `PROJECT_POLICY.toml`. Each listed file
bypasses every source-structure check, including the line limit, forbidden
generic-name check, and UTF-8 check.

Exception entries match files exactly. Globs, directory entries, path prefixes,
and library-like names do not exempt any other file. Do not use an exception
for repository-owned source or infer one merely from a file's location or name.
The setting does not bypass checks outside source-structure validation.

Changing the limit or adding an exception is high risk. Keep each imported
library pinned and read-only; update its version and exception paths together
as separate governed work.

## CI

Required checks:

- PR policy
- Repository policy
- Tests
- Format

[GM-Testing-Library](https://github.com/DAndrewBox/GM-Testing-Library) is the
test framework for GameMaker projects. When initializing a project, download
and pin its latest release. Do not update that pinned version without specific
human instruction.

Game-specific test suites are added to `Tests` as they become available.

Tests should protect contracts, not incidental representations. Do not use
exact-text, exact-order, or exact-count assertions when a semantic assertion
can establish the same requirement, unless the exact representation is itself
part of the contract.

CI may enforce exact structured rules when that exact structure is itself part
of the contract. Do not infer that a representation is contractual merely
because a test, tool, or automation consumes it.

CI must not interpret arbitrary natural-language prose.

CI must not interpret arbitrary natural-language prose.

## History

Do not force-push protected branches.

Do not automatically delete branches.

Do not rewrite history merely to simplify it.
