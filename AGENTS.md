# Selkie's Moon project instructions

Before modifying the repository, read:

- GOVERNANCE.md
- PROJECT_POLICY.toml

## Git

Never create work from local `dev`.

Normal work begins with:

git fetch origin dev
git switch -c work/<issue>-<slug> origin/dev

Release work uses:

release/<issue>-v<semver>

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

python3 tools/ci/check_repo.py
python3 -m unittest discover -s tools/tests -p 'test_*.py'
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