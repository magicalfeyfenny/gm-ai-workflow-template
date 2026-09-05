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
  constraints hold. Prefer automated tests, fixtures, validators, deterministic
  runtime checks, and other machine-verifiable evidence whenever the required
  property is mechanically observable. Human observation, manual playtesting,
  experiential review, subjective visual review, or human acceptance may be
  included only when explicit human direction requires that specific judgment.
  Do not infer a need for human or manual validation merely because an outcome
  is player-visible, interactive, visual, runtime-affecting, or high-risk.
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

### Compatibility obligations

Compatibility is required only when an independently established contract or
consumer must continue to accept an older representation.

A compatibility obligation must be supported by evidence that is independent
of the implementation proposed to satisfy it. Valid evidence must either
predate the current governed change or come from explicit current human
direction. Examples include:

- released or published interfaces;
- persisted user data, saves, configuration, or other durable data that must
  continue to load;
- independently maintained consumers that cannot be updated atomically with
  the current change;
- imported or external contracts that the repository does not control; or
- explicit human direction requiring old and new representations to coexist.

Repository history establishes that an older representation existed; it does
not by itself establish that the representation must remain compatible.
Repository-owned code, tests, fixtures, content, and documentation that can be
updated atomically with the current change are ordinary consumers of the
current representation, not independent compatibility consumers.

Evidence created by the current governed change cannot establish the
compatibility obligation that would justify preserving it. Code, tests,
fixtures, documentation, aliases, migration paths, normalization layers,
deprecated representations, or other consumers introduced or modified on the
current issue branch, pull request, or earlier implementation attempt do not
become compatibility evidence merely because later work depends on them.

The same applies to agent-authored intermediate states. When human direction
changes an unreleased internal name or representation during governed work,
implement the newly intended state directly and remove superseded intermediate
machinery unless independent evidence establishes a real compatibility
obligation.

Do not infer a compatibility obligation merely because an identifier is named
stable, canonical, versioned, legacy, public, or otherwise appears
contract-like. Establish the actual consumer or durable boundary.

When no independent compatibility obligation exists, prefer direct
replacement. Update the canonical representation and all repository-owned
consumers together, update tests to the intended current contract, and remove
the superseded representation instead of adding aliases, migration layers,
normalization paths, wrappers, or deprecated forms.

Agent-authored issues must not speculate about compatibility. An Engineering
constraint or Validation requirement for backward compatibility, aliases,
migration, normalization, or legacy support must identify the concrete
independent consumer or durable contract that requires it and cite the
available source evidence. Do not add conditional requirements such as
"preserve a compatibility alias if needed" without that evidence.

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
progress without weakening the issue's acceptance contract. A deterministic
placeholder is scaffolding, not evidence for an acceptance criterion that
explicitly requires final production or authored assets.

This capability check composes with every other scheduled eligibility
condition, including issue atomicity, risk handling, dependency order, and the
fail-closed recheck immediately before repository mutation. It does not replace
or relax any of them.

### Placeholder-backed mixed work

A mixed implementation issue may use deterministic placeholders when final
authored assets are secondary and the current execution environment
lacks the capability to produce them. This is allowed only when the
deterministic placeholder preserves an independently meaningful primary
outcome and the issue's existing acceptance contract permits the final asset
to be deferred. It does not make an asset-primary issue eligible.

Keep every deterministic placeholder explicitly identified as non-production
scaffolding in the implementation and pull-request handoff. Preserve the
intended gameplay, UI, or runtime integration point so the final authored asset
can replace the deterministic placeholder without recreating completed
implementation work.

A deterministic placeholder never satisfies an acceptance criterion that
requires a final authored or production asset. If the current issue still
contains such a criterion, the issue remains incomplete; linking a follow-up
does not make that criterion complete.

Follow-up tracking is required only for concrete remaining asset-production
work. Such work must be explicitly requested by human direction or
independently required by a current product or acceptance contract. An
agent-authored tracking item does not establish that requirement merely by
restating a possible future revision as issue scope.

When the implementation issue can complete independently and concrete,
separable asset-production work remains, resolve its tracking before the
implementation issue completes:

1. Search live tracking for an appropriate canonical asset issue. Link the
   original issue and pull request to that issue, updating it only as needed to
   identify the concrete remaining production work and replacement point.
2. If no appropriate issue exists, create exactly one narrow follow-up assigned
   to the current user. Reference the original issue and pull request, own only
   the concrete unresolved asset production and its asset-specific validation,
   and exclude implementation scope already completed with the placeholder.
3. Record the canonical follow-up link and the exact deterministic-placeholder
   scope and replacement point in the original pull-request handoff.

When concrete remaining production meets this rule, its required follow-up is
part of completing the selected mixed issue, not permission to generate a
general backlog. A scheduled execution may create it only after claiming that
issue and only under the rules above. The follow-up uses the normal
issue-authority, dependency, and risk rules for its own scope.

### Scheduled continuation

Before selecting a new issue, a scheduled Governed Change run checks for an
existing incomplete governed change owned by the current automation user. A
valid continuation has an open issue assigned to that user, its matching
issue-numbered `work/<issue>-<slug>` branch, and its draft pull request. The
issue and pull request must still pass the normal ownership, dependency,
blocker, and human-authority checks. The capability check still applies to any
remaining primary non-degradable deliverable; an unavailable environment
needed only for required interactive evidence is handled by
[Interactive runtime validation](#interactive-runtime-validation) and does not
invalidate the continuation. A human-created
branch or pull request and a `work:blocked` change are never continuations.
The draft pull request must not already have a completion line or completion
label; a `work:complete` or `work:review-ready` pull request follows its normal
completion path instead of being resumed as incomplete work.

When a valid continuation exists, resume its next incomplete implementation or
validation milestone on that branch and draft pull request before selecting
new work only when the current environment can make meaningful progress on at
least one remaining implementation or validation milestone. A continuation
that can only wait for unavailable required runtime evidence, an unavailable
interactive environment, or explicitly required human action is pending rather
than actionable; leave it pending and allow the run to select at most one new
eligible issue. Do not repeatedly retry an unavailable GUI or alter the pending
continuation just to make progress appear possible.
A continuation is pending for unavailable interactive validation only when
that interactive validation is independently required by explicit human
direction or by a concrete machine-verifiable runtime requirement permitted
under Interactive runtime validation. Do not treat an agent-authored generic
smoke test, subjective review, experiential acceptance, or human-observation
requirement as a valid completion blocker.

A continuation does not make an asset-primary issue eligible when its remaining
primary deliverable still needs an unavailable capability. When the required
environment becomes available, or the required human action is resolved, the
continuation becomes actionable and takes priority again. Resume the missing
required check and then follow the ordinary completion transition.

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
2. `authored-placeholder` is a legitimately authored asset with authorial or
   source commitment that has not yet been explicitly accepted as the final
   production asset. It does not mean the asset is known to require revision,
   replacement, refinement, redraw, regeneration, or later completion work.
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

Asset completion status is state. Only concrete requested work belongs in the
backlog. The absence of `final` status alone does not establish deferred work,
and possible future revision is not deferred work. An `authored-placeholder`
may remain at that level indefinitely. Human authority may later accept it
unchanged, request changes, replace it, or continue leaving it undecided.
Authorized agent work may create and integrate an asset as
`authored-placeholder` without seeking an immediate human decision about
`final` status; that undecided status does not make otherwise-complete asset
production unfinished.

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

Promoting an `authored-placeholder` to `final` through human acceptance is an
authority transition, not an implementation or asset-production deliverable.
Human authorial authority may promote the existing asset unchanged, without
modifying or replacing it and without creating an implementation issue.

Agents must not create or retain an issue, dependency, blocker, sprint
obligation, or asset-production task merely because an `authored-placeholder`
might be changed later or has not been promoted to `final`. They must not claim
or continue such tracking. In particular, agents must not create or retain an
issue when its only unresolved outcome is human review, approval, acceptance,
or promotion of an existing authored asset. Create or retain asset-production
tracking only when concrete further asset work is explicitly requested by
human direction or independently required by a current product or acceptance
contract.

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

Prefer automated validation whenever the required property is
machine-verifiable.

Numeric, combinatorial, deterministic, structural, state-transition,
integration, rendering, interaction, persistence, packaging, and other
mechanically observable behavior should normally be established through
automated tests, fixtures, validators, deterministic runtime checks, or
equivalent machine-verifiable evidence.

Manual playtesting, human experiential review, subjective visual review, human
observation, and human acceptance are not default validation methods. Agents
must not add them to an issue, pull request, validation plan, blocker, handoff,
or completion requirement unless explicit human direction requires that
specific human judgment.

Player-visible behavior does not by itself require manual validation. Prefer
automated runtime, rendering, snapshot, deterministic interaction, or other
machine-verifiable evidence where practical.

Agent-authored issue text, validation plans, pull-request handoffs, tests, or
intermediate implementation decisions cannot bootstrap a requirement for
human observation or experiential acceptance that was not already present in
explicit human direction requiring that specific judgment.

Preservation requirements do not imply exhaustive retesting of preserved
behavior. Validation should target plausible regressions introduced by the
actual change. A requirement to preserve existing behavior does not by itself
require manually re-observing all of that behavior.

Do not require a generic gameplay smoke test merely because repository files,
runtime code, GameMaker resources, assets, packaging, configuration, or
governance files changed. Every validation action must establish a specific
claim materially connected to the implemented delta.

Interactive execution is appropriate only when it has a concrete
machine-verifiable purpose that cannot be established adequately through
ordinary static or automated evidence.

### Interactive runtime validation

Launching the game is exceptional validation, not a default completion stage.

Agents may launch the GameMaker runtime only for a concrete machine-verifiable
purpose, including:

- executing GameMaker-hosted automated test suites such as GMTL;
- bounded deterministic UI or interaction smoke tests whose expected results
  are mechanically observable;
- explicitly scoped performance profiling or runtime measurement; or
- another specific runtime-only validation explicitly required by human
  direction.

Do not launch the game for generic "does it still run", "does gameplay still
work", broad regression smoke testing, player-experience review, readability
review, feel testing, subjective visual-quality judgment, or other
experiential validation.

Human manual playtesting, experiential judgment, visual approval, or
subjective acceptance must never be inferred from player visibility, issue
risk, changed runtime files, changed resources, changed assets, or absence of
stronger automated evidence. Such human judgment is required only when
explicitly requested by the human author.

If an explicitly required interactive machine-verifiable validation cannot run
because the necessary environment is unavailable, record that environment
limitation and follow the issue's actual completion contract. Do not invent a
human-observation blocker as a substitute.

An issue must not remain incomplete solely because a generic gameplay smoke
run or unrequested human observation has not occurred.

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

Human review, merge, promotion, and publication gates allocate authority; they
do not create additional human observation or experiential verification work.

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
4. receives a human-authorized release-candidate build;
5. verifies the candidate source tree, build identity, artifact contents, and
   artifact digests against the release contract;
6. is manually merged into `main`;
7. is tagged from the resulting `main` commit;
8. receives its final build from that tag;
9. is manually published.

Record the source commit and tree, build provenance, and artifact digests for
the release candidate and final tagged build. Verify packaging and integrity
with concrete machine-verifiable evidence. Experiential release testing is
required only when explicit human direction requests that specific judgment.

Tags, release builds, merges into `main`, and publication are never automatic.

After the first release, `main` changes only through release PRs.

## Native GameMaker functionality

Before designing, retaining, repairing, extending, or replacing custom
repository-owned machinery for behavior GameMaker may provide, determine
whether applicable native functionality satisfies the current product and
engineering contract. This requirement applies to existing implementations
as well as new work.

### Establish engine semantics

When an implementation decision depends on a named GameMaker feature or
engine abstraction, establish its actual semantics before deciding to preserve
or redesign a custom substitute. Inspect the applicable native contract or
documentation for the project's engine version and targets, or establish the
behavior through direct, relevant engine evidence. Record the source and the
conclusion at the implementation decision boundary. Runtime evidence follows
[Validation coverage allocation](#validation-coverage-allocation) and
[Interactive runtime validation](#interactive-runtime-validation).

This applies, for example, to nine-slice sprites, scaling, tilemaps, sequences,
surfaces, cameras, animation, collision, particles, audio, paths, fonts,
resource loading, and buffer APIs. The examples are not an exhaustive list.
Function names, comments, the number or arrangement of helper calls, and
superficial resemblance to a feature do not establish the engine contract.
Repository precedent is evidence of what exists, not authority over what
GameMaker means.

### Custom implementation requirements

If native functionality satisfies the required outcome, use it. Do not
introduce redundant custom machinery. Remove or simplify redundant machinery
when that cleanup is within the authorized outcome. Do not disable, bypass,
or degrade a native facility merely to preserve a custom implementation whose
independent necessity has not been established.

A custom implementation requires a concrete current requirement the native
facility cannot satisfy. Identify the unmet requirement and the evidence for
the limitation. Behavior, determinism, portability, runtime data access,
tooling, performance, compatibility, integration, authoring workflow, or
another current contract boundary can justify the custom path. A compatibility
claim also follows [Compatibility obligations](#compatibility-obligations).

Existing code, history, architectural precedent, tests written around the
custom mechanism, and the fact that it already works are insufficient evidence
of necessity. Update repository-owned consumers atomically when the authorized
outcome replaces their mechanism. Native functionality is the default when
sufficient; a demonstrated unmet requirement remains a valid exception.

### Native adoption scope

Apply the decision to current requested work and independently established
contracts. Existing custom systems or external runtime assets alone do not
authorize cleanup, an implementation issue, or a retained backlog obligation.
An audit may report an unsupported decision without inventing implementation
work. A current requested outcome, current issue, or independently established
contract must actually require the change.

## Derived assets

The `[assets]` and `[assets.pipelines.*]` tables in
[PROJECT_POLICY.toml](PROJECT_POLICY.toml) define the executable roots,
manifest path, supported source and runtime formats, and audio parameters.

### Runtime asset representation

Distinguish the editable authoring source, the exported artifact, and its
runtime GameMaker representation. External authorship does not imply external
runtime loading. An external editable source may export an artifact that is
integrated into a native GameMaker resource; the artifact may live directly
inside that resource without a duplicate staging copy.

Use an appropriate native GameMaker runtime resource when it adequately
represents the asset under the current contract. Typical destinations include
Sprite resources for sprite images, Sound resources for audio, Font resources
for fonts, Sprite and Tile Set resources for tile graphics, and Sequence
resources for applicable sequence content. Preserve a useful canonical
editable source outside GameMaker when the authoring workflow calls for it.
Assets authored directly in GameMaker need no artificial external source.

Included Files require an actual file-based runtime contract or content that
no appropriate native resource adequately represents. Examples include JSON
game data, custom model or buffer data such as `.vbuff`, runtime-enumerated
content, user-modifiable or mod data, and other formats requiring file access.
These examples do not restrict valid files to particular extensions. Record
the concrete runtime reason; being externally generated, manifest-listed, or
part of an export pipeline is insufficient. A supported export format does
not by itself justify a runtime representation.

Apply [Native GameMaker functionality](#native-gamemaker-functionality) to
resource and loader choices, including its semantics, exception, and scope
rules. Keep source authority, ownership, provenance, completion metadata, and
applicable storage requirements independent of runtime representation.

### Export topology

Each derived asset follows its named pipeline and one entry in the configured
canonical export manifest. Pipeline `source_roots` permit editable-source
locations, including directory-backed source packages. Pipeline
`runtime_roots` are dedicated file-export locations: every tracked runtime
asset there needs manifest coverage. Pipeline `native_resource_roots` are
shared GameMaker locations: validate manifest-owned outputs without treating
unrelated native resources as derived exports.

The manifest's `sources` identify editable sources and `runtime` identifies
the exported artifacts at their runtime destinations. Each entry declares one
`destination`: `native-resource` names the tracked `.yy` resource containing
its outputs; `included-file` records a nonempty `file_contract` reason for
runtime file access. This declaration does not replace GameMaker resource
metadata or prove that the stated reason is sufficient. Verify the actual
resource or packaging relationships changed by the work. See the
[manifest examples](assets/example_manifest_entry.txt).

Allowed source and runtime extensions are alternatives. Require companion
formats only through a pipeline's explicit `required_source_extensions` or
`required_runtime_extensions` when its actual contract requires them.
Preserve existence, tracking, unique runtime ownership, export coverage, and
completion metadata. Directory sources require tracked existing descendants;
recognize valid nested LFS pointers as storage representations rather than
parsing them as literal asset content. Materialized content remains subject to
applicable content checks; pointer presence alone does not prove export
fidelity or packaging.

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

For renames, representation changes, and replacement of internal paths, follow
[Compatibility obligations](#compatibility-obligations). Do not preserve a
superseded internal representation merely because repository-owned consumers
or tests currently reference it when they can be updated atomically with the
change.

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
