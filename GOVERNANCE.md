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

A direct human request for governed repository work authorizes the
`governed-change` workflow to find the matching issue or, if none exists,
create one for exactly that requested work. This permission does not authorize
speculative backlog work.

A scheduled Governed Change run selects only an existing eligible issue under
its automation contract. The direct-request permission above does not apply,
and the run must not create a replacement when no issue is eligible.

Project Steward owns evidence-backed issue creation for stewardship audits,
including scheduled audits. Its skill owns the audit-specific evidence and
per-run constraints. In scheduled operation, Project Steward owns issue
creation and does not implement issues.

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

Every agent-governed repository change uses:

1. one GitHub issue;
2. one issue-numbered branch;
3. coherent milestone commits;
4. one draft pull request opened with the first meaningful commit;
5. required CI;
6. merge according to the risk policy.

The issue number must match the branch name and completion metadata.

Keep the change bounded to that issue and do not absorb unrelated cleanup.
Preserve useful behavior, not obsolete architecture merely because it exists.

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

Each asset follows its named pipeline. Editable vector source is an Inkscape
SVG; vector runtime is plain SVG when `plain_runtime_svg` is enabled and
contains no editor metadata. In the music pipeline, `.mid` is sheet music and
`.logicx` is the editable audio project; sound effects also use `.logicx` as
the editable audio project. For 3D assets, `.obj` and `.mtl` are retained
intermediate export sources.

## GameMaker structured data

Canonical GameMaker-specific structured data lives under the `content_root`
configured in [PROJECT_POLICY.toml](PROJECT_POLICY.toml). It uses `.json`
directly as both editable source and runtime data, is stored once, and is not
entered in the derived-asset manifest.

This includes story, bullet-pattern, stage, encounter, save-schema and default,
and cached GameMaker-specific data.

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
or separate failure mode needs them.

Make both the code path and the reason for taking it plain to a human reader.
Prefer direct control flow, concrete names, and explicit data. Establish an
invariant at the appropriate boundary; do not repeatedly check it along a
trusted path without a separate reason.

When necessary complexity or a non-obvious technique remains, explain why at
the narrowest useful boundary with a concise plain-English comment. A design
with many moving parts is maintainable only when the reason for them can be
explained.

Add a concise plain-English comment to every function written or changed by an
agent, and wherever implementation intent would otherwise be unclear. Comments
must accurately describe current behavior and intent without merely restating
the code. A function comment must limit its claims to behavior the function
actually implements. Do not use comments as a wishlist unless planned or
desired behavior is clearly labeled `TODO`.

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

CI may enforce exact structured rules.

CI must not interpret arbitrary natural-language prose.

## History

Do not force-push protected branches.

Do not automatically delete branches.

Do not rewrite history merely to simplify it.
