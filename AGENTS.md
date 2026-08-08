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

Do not force-push.

Do not merge into `main`.

Do not create release builds, tags, releases, or publication without explicit
human instruction.

## Scope

Keep each change bounded to its issue.

Do not perform unrelated cleanup.

Preserve useful behavior, not obsolete architecture merely because it exists.

## Structure

Give each source file one primary responsibility.

Do not create generic helper, utility, misc, or common dumping grounds.

Respect the source-size limit in PROJECT_POLICY.toml.

Prefer explicit, human-readable code.

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

Before publishing a change, run:

python3.12 tools/ci/check_repo.py --baseline-ref origin/dev
python3.12 -m unittest discover -s tools/tests -p 'test_*.py'
git diff --check

Run relevant GameMaker tests when available.

## Pull requests

Create PRs as drafts.

Apply exactly one:

- risk:low
- risk:high

Low-risk PRs may continue through repository automation.

High-risk PRs stop after validation and publication until a human explicitly
authorizes readiness and merge.

If a PR uses a `human/*` branch or has the `human-created` label, stop. Do not
modify its branch, commits, body, labels, checks, reviews, draft state,
readiness, or merge state. Do not perform review or validation work on it.
Agents must never invoke a ruleset bypass.

After a human-created PR merges, do not presume that nonconformance with
current repository standards is wrong. It may inform desired patterns or
algorithms. Existing violations are treated as the repository baseline and do
not block unrelated agent changes. A bounded repository-standardizing issue
may be created from concrete merged evidence after duplicate search; classify
any resulting change by its actual paths and scope.
