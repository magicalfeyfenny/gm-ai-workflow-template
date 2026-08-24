# GameMaker project instructions

Before modifying the repository, read:

- GOVERNANCE.md
- PROJECT_POLICY.toml

## Tooling

Repository tooling requires Python 3.12 or later.

Use `python3.12` for repository policy and test commands.

## Git

Never create work from local `dev`.

Normal work begins with:

git fetch origin dev
git switch -c work/<issue>-<slug> origin/dev

Release work uses:

release/<issue>-v<semver>

The `human/` branch namespace is reserved for humans. Agents must never create,
switch to, push to, or modify a `human/*` branch.

Agents may commit freely to their current issue-scoped branch. Commit each
coherent milestone as soon as Stage 1 milestone evidence from GOVERNANCE.md
passes. Push the first meaningful commit and create its draft PR immediately,
including for high-risk work. Continue pushing later milestone commits to that
draft PR. Commit and draft publication do not grant readiness or merge
authority. An in-progress draft omits the `Closes #<issue>` line.

Do not force-push.

Do not merge into `main`.

Do not create release builds, tags, releases, or publication without explicit
human instruction.

## Scope

Keep each change bounded to its issue.

Do not perform unrelated cleanup.

Preserve useful behavior, not obsolete architecture merely because it exists.

## Production code and structure

Give each source file one primary responsibility.

Do not create generic helper, utility, misc, or common dumping grounds.

Respect the source-size limit in PROJECT_POLICY.toml.

For repository-owned production code you write or change, use the simplest
design that reasonably satisfies current requirements. Follow established
project and language conventions. Use descriptive names and visible control
flow. Do not add pass-through layers, indirection, duplicate state,
configuration, repeated validation, or speculative flexibility without a
concrete need.

Make both the code path and its reason plain to a human reader. Establish an
invariant at the appropriate boundary instead of repeatedly checking it along
a trusted path. Explain necessary complexity or non-obvious techniques at the
narrowest useful boundary with a concise plain-English comment.

Add a concise plain-English comment to every function you write or change, and
wherever intent would otherwise be unclear. Comments must accurately describe
current behavior and intent without merely restating the code. Limit claims to
what the code actually does. Do not use comments as a wishlist unless the
planned behavior is clearly labeled `TODO`.

These style and simplicity requirements do not apply to imported library
source. Preserve libraries under the imported-library policy in
GOVERNANCE.md instead of restyling or simplifying them.

## Asset pipelines

Editable source assets belong under assets/source.

Derived runtime assets belong under assets/runtime.

Update assets/exports.json for every derived runtime asset.

Use:

Vector:
- Inkscape `.svg` source
- plain `.svg` runtime

Raster:
- `.kra` source
- `.png` runtime

Music:
- `.mid` sheet-music source
- `.logicx` project source
- `.flac` runtime at 48 kHz stereo

Sound effects:
- `.logicx` project source
- `.wav` runtime at 48 kHz stereo

3D:
- `.blend` project source
- `.obj` and `.mtl` export sources
- `.vbuff` runtime

## Structured GameMaker data

Canonical runtime GameMaker data lives under content/ as `.json`.

The same JSON is both editable source and runtime data.

Do not duplicate it into assets/source or assets/runtime.

## Validation

Follow the three validation evidence stages and invalidation rules in
GOVERNANCE.md. Use only the evidence required for the current stage. Relevant
GameMaker tests remain required when available.

## Pull requests

Create PRs as drafts.

Apply exactly one:

- risk:low
- risk:high

Low-risk PRs may continue through repository automation.

After the entire low-risk issue scope is finished and Stage 2 whole-issue local
evidence is valid, add exactly one `Closes #<issue>` line and apply
`work:complete`. Do not apply it to an intermediate milestone. For a low-risk
PR without `manual-merge`, repository automation then marks it ready and
configures squash auto-merge after Stage 3 hosted PR evidence passes.

High-risk PRs may be committed, pushed, and published as drafts without
separate permission. When high-risk or `manual-merge` work is finished and
Stage 2 whole-issue local evidence is valid, add exactly one `Closes #<issue>`
line and apply `work:review-ready`. Obtain Stage 3 hosted PR evidence, then wait
for human review, readiness, and merge.

`work:blocked` retains the former `blocked` behavior. Do not work the PR or add
a closing line or completion label until its blockers are resolved.

If a PR uses a `human/*` branch or has the `human-created` label, stop. Do not
modify its branch, commits, body, labels, checks, reviews, draft state,
readiness, or merge state. Do not perform review or validation work on it.
Agents must never invoke a ruleset bypass.

After a human-created PR merges, do not presume that nonconformance with
current repository standards is wrong. It may inform desired patterns or
algorithms. Existing violations are treated as the repository baseline and do
not block unrelated agent changes. Human-authored work may be followed by a
bounded repository-compliance issue that normalizes structure, validation,
assets, tests, and repository conventions without changing intended behavior.
Use the normal risk policy.
