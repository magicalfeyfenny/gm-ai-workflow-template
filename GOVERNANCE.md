# Governance

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

An in-progress draft PR does not contain a closing line. When the entire issue
is ready for review or automatic merge, add exactly one line:

Closes #<issue>

The issue number must match the branch name. The closing line appears together
with the completion label required by the merge path below.

## Milestone commits and draft publication

Agents may commit to their current issue-scoped branch without separate human
authorization. Create a commit as soon as a coherent milestone is complete and
has received proportionate validation. Do not leave a completed milestone only
in the working tree while waiting for the entire issue to finish.

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

Any change may be voluntarily classified high risk.

Automatically high-risk changes may not be downgraded.

## Low-risk changes

After the entire issue scope is finished and the candidate has received the
required validation, add the closing line and apply `work:complete`. This label
marks issue completion, not the completion of an intermediate milestone.

After required CI passes, a low-risk PR targeting `dev` with `work:complete`
and without `manual-merge` is automatically:

1. marked ready;
2. configured for squash auto-merge.

The successful CI run must attest to the current head and the current
policy-relevant PR metadata, including the exact body and labels. Changing
that metadata requires a new successful run; an older run for the same head
cannot authorize readiness or auto-merge for the newer state.

The `manual-merge` label disables both automatic readiness and auto-merge.

## Manual and high-risk changes

A PR uses the manual completion path when it is high risk or has
`manual-merge`. It receives the same automatic CI verification.

After the entire issue scope is finished and validated, add the closing line
and apply `work:review-ready`. The label means that implementation is done and
the PR is waiting for human review.

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

Editable source assets live under:

assets/source/

Derived runtime assets live under:

assets/runtime/

Every tracked derived runtime asset must be mapped in:

assets/exports.json

Supported pipelines are:

### Vector graphics

Source:
- Inkscape `.svg`

Runtime:
- plain `.svg`

Runtime SVG must not contain Inkscape editor metadata.

### Raster graphics

Source:
- `.kra`

Runtime:
- `.png`

### Music

Sources:
- `.mid` sheet music
- `.logicx` audio project

Runtime:
- `.flac`
- 48 kHz
- stereo

### Sound effects

Source:
- `.logicx` audio project

Runtime:
- `.wav`
- 48 kHz
- stereo

### 3D graphics

Sources:
- `.blend` project
- `.obj` export source
- `.mtl` export source

Runtime:
- `.vbuff`

The OBJ and MTL files are retained intermediate sources.

## GameMaker structured data

Canonical GameMaker-specific structured data lives under:

content/

It uses `.json` directly as both editable source and runtime data.

Examples include:

- story data;
- bullet-pattern data;
- stage and level data;
- encounter data;
- save schemas and defaults;
- cached GameMaker-specific structures.

Canonical JSON is stored once and is not entered in the derived-asset manifest.

## Source structure

A source file has one primary responsibility.

Generic dumping-ground source files named `helper`, `helpers`, `util`, `utils`,
`misc`, or `common` are not allowed.

Source files may not exceed the configured line limit.

When a file approaches the limit, split it by responsibility.

Changing the limit or adding an exception is high risk.

## CI

Required checks:

- PR policy
- Repository policy
- Tests
- Format

GM-Testing-Library (https://github.com/DAndrewBox/GM-Testing-Library) is used as the test framework for all GameMaker projects. When the project is initialized, download the latest release and pin it as the testing framework version -- do not update  it unless specifically instructed by a human.

Game-specific test suites are added to `Tests` as they become available.

CI may enforce exact structured rules.

CI must not interpret arbitrary natural-language prose.

## History

Do not force-push protected branches.

Do not automatically delete branches.

Do not rewrite history merely to simplify it.
