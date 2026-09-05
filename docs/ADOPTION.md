# Plan adoption or recovery of an existing repository

Start from an available local clone and GitHub read access. Use Python 3.12,
Git, and authenticated GitHub CLI (`gh`). Git LFS improves local object
availability evidence. The planning tool does not require administrator write
access; unavailable protected metadata is reported in the plan.

Run the tool from a trusted copy of the template, pointing `--root` at the
existing repository. Neither copying the template into the repository nor
running its bootstrap is necessary:

```sh
python3.12 tools/setup_github.py adopt-existing --plan \
  --repo OWNER/REPOSITORY --root /absolute/path/to/existing-repository
```

`adopt-existing` defaults to planning even without `--plan`. It only issues
GitHub GET requests and reads local Git evidence. It does not fetch, check out,
unarchive, install LFS, modify content or refs, configure settings, edit tracking,
or apply its proposals. Its JSON report goes to stdout. If saving evidence,
redirect stdout to a chosen path outside the repository so that your output
redirection does not change repository content.

The [generated-repository setup](SETUP.md#configure-github) remains a separate
mutating operation and retains its protection against moving an existing
`main`.

## Read the evidence

The report separates observations, missing evidence, unresolved decisions, and
proposed operations:

- `remote` records archive/default-branch state, settings, live `main`, `dev`,
  and default-branch commit/tree identities; their comparisons; labels; open
  issues and PRs; published releases and tag identities; inherited and custom
  rulesets; active branch rules; and classic branch protection. Inventories
  are paginated. A failed inventory read is unavailable rather than an empty
  inventory. A protection 404 cannot always distinguish absence from lack of
  access, so it stays an evidence limitation.
- `local` records relevant refs, object/commit/tree identities, ancestry and
  divergent or unrelated histories, available reflog evidence, replace refs,
  tracked LFS configuration, pointer metadata, and local LFS object availability.
  Missing objects and shallow history limit what can be established. Local
  tracking refs remain separate from the observed live branch identities.
- `release_verification` records source-tree comparison and artifact evidence
  separately from commit provenance. A successful tree comparison does not
  establish that any artifact was built from that source.
- `proposed_mutations` contains concrete HTTP methods, endpoints, payloads,
  and prior values for adopting the template's configured settings, labels,
  and named rulesets. These are proposals to assess, not a runnable apply queue.
  Existing custom and inherited protection is retained as evidence. Replacing
  a differing named ruleset requires a decision about its current differences.
  Additional custom labels and rulesets are not proposed for deletion.
- `unavailable_evidence` and `unresolved_decisions` identify what the available
  snapshot cannot settle. Missing branch anchors need an explicit branch plan;
  there are no implicit branch creation, movement, or deletion proposals.

Review [active branch rules](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch)
alongside ruleset details and classic protection. Active branch rules include
applicable rules from higher levels; inactive/evaluation rulesets remain useful
configuration evidence but do not establish active required checks.

## Select a recovery lineage

Use explicit refs or commit IDs for relevant preserved histories. The tool
does not select a canonical lineage automatically:

```sh
python3.12 tools/setup_github.py adopt-existing \
  --repo OWNER/REPOSITORY --root /absolute/path/to/existing-repository \
  --ref refs/heads/preserved-history \
  --lineage refs/heads/selected-history \
  --lineage-reason 'This preserved tree contains the intended game source.' \
  --recover-outcome 'Recover the requested game implementation on dev.'
```

Record the actual evidence supporting that choice and each intended repository
outcome. Repeat `--ref` or `--recover-outcome` as needed. A selected ref must
resolve locally; its commit and tree are preserved in the report. Divergence
alone is not evidence of rewriting. Record independent evidence such as prior
published commit IDs, saved observations, or reflog transitions, and state its
limits. Do not merge incompatible histories wholesale merely to preserve both.

Before separately authorized destructive cleanup, retain the report outside
the affected repository, the selection rationale, and enough original objects
and supporting evidence to explain the choice. Identify exact preservation and
cleanup targets in that separately reviewed recovery plan. This planner does
not implement a recovery/apply engine or assign existing differences to a
cleanup backlog. [Issue authority](../GOVERNANCE.md#issue-authority) governs any
subsequent bounded work.

## Verify an existing release source state

The default selects the uniquely latest published stable release by publication
time and compares its Git tree with the observed live `main` commit. The commit
must be locally available; the planner does not fetch missing objects. Use an
explicit tag and candidate source ref when the recovery contract identifies
another anchor:

```sh
python3.12 tools/setup_github.py adopt-existing \
  --repo OWNER/REPOSITORY --root /absolute/path/to/existing-repository \
  --release-tag v1.0.0 --candidate-ref refs/heads/recovered-release
```

An explicitly selected tag may identify a published prerelease. Draft releases,
missing anchors, ambiguous selection, and mismatched local/live tag objects
cannot produce a successful verification. Annotated and lightweight tags are
resolved to commits and trees. Different commits with identical trees pass the
source-state invariant; different trees fail. Commit identity and ancestry
remain evidence, with no extra equality requirement inferred from them.
`target_commitish` is not an immutable release anchor.

The comparison implements the existing [main source-state contract](../GOVERNANCE.md#branches)
and keeps source identity separate from [release provenance and artifact evidence](../GOVERNANCE.md#releases).
It verifies an observed tag, not whether that tag was ever moved before the
available observations.

Pass `--artifacts /absolute/path/to/evidence.json` when local artifact evidence
is available or required by the actual release contract. For example:

```json
[
  {
    "name": "game.zip",
    "path": "/absolute/path/to/game.zip",
    "sha256": "replace-with-the-contract-sha256-digest",
    "required": true
  }
]
```

`sha256` can be omitted when the matching published release asset has a usable
GitHub SHA256 digest. The tool records available
[release asset digest metadata](https://docs.github.com/en/rest/releases/releases)
even without a local artifact. A recorded digest alone does not claim local
byte verification. Required artifact evidence needs a readable local file and
an expected digest; absence prevents successful verification. Optional missing
historical evidence remains identified as unavailable. Mismatched available
digests fail. Use absolute artifact paths; no artifacts are downloaded.

Exit status 0 means the release verification passed and the GitHub observations
were available. Status 1 means the report was produced with incomplete or
failed verification/evidence; status 2 indicates invalid arguments or input.
Inspect unresolved decisions and local evidence limitations even with status 0.
No exit status grants apply, unarchive, ref mutation, release, or publication
authority. Refresh observations before any separately authorized application.
