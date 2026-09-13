# Plan adoption or recovery of an existing repository

Start by establishing the [framework comparison](#establish-the-framework-comparison)
under [Framework adoption lineage](../GOVERNANCE.md#framework-adoption-lineage).
An evidence-backed earlier adoption uses the
[bounded policy-update procedure](POLICY_UPDATE.md). Use this planner for
relevant state or recovery questions identified there.

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
  and default-branch commit/tree identities; their comparisons; labels; distinct
  open issue and PR inventories; release metadata and the selected release's
  tag identity and asset inventory; inherited and custom rulesets; active branch
  rules; and classic branch protection. Inventories
  are paginated. A failed inventory read is unavailable rather than an empty
  inventory. A protection 404 cannot always distinguish absence from lack of
  access, so it stays an evidence limitation.
- `local` records relevant refs, object/commit/tree identities, ancestry and
  divergent or unrelated histories, available reflog evidence, replace refs,
  tracked LFS configuration, pointer metadata, and local LFS object availability.
  Missing objects and shallow history limit what can be established. Local
  tracking refs remain separate from the observed live branch identities.
  Ancestry and tree/LFS inspection cover `main`, `dev`, the default branch,
  explicit `--ref` selections, the selected lineage, the candidate source, and
  the selected release tag. Historical release metadata alone does not add
  ancestry comparisons, tree scans, or tag/asset API lookups. Missing or
  ambiguous release selection does not trigger historical tag inspection.
- `release_verification` records source-tree comparison and artifact evidence
  separately from commit provenance. A successful tree comparison does not
  establish that any artifact was built from that source.
- `proposed_mutations` contains concrete HTTP methods, endpoints, payloads,
  and prior values for adopting the template's configured settings, labels,
  and named rulesets. These are proposals to assess, not a runnable apply queue.
  Existing custom and inherited protection is retained as evidence. Replacing
  a differing named ruleset requires a decision about its current differences.
  Additional custom labels and rulesets are not proposed for deletion.
  A proposed default-branch change is withheld while its live target branch is
  missing or cannot be verified; independent settings changes remain proposed.
- `unavailable_evidence` and `unresolved_decisions` identify what the available
  snapshot cannot settle. Missing branch anchors need an explicit branch plan;
  there are no implicit branch creation, movement, or deletion proposals.

Review [active branch rules](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch)
alongside ruleset details and classic protection. Active branch rules include
applicable rules from higher levels; inactive/evaluation rulesets remain useful
configuration evidence but do not establish active required checks.

## Establish the framework comparison

Apply [Framework adoption lineage](../GOVERNANCE.md#framework-adoption-lineage)
before editing the target. Record the exact pre-adoption target commit and
incoming upstream repository and commit in the adoption PR. Inspect relevant
history, prior adoption/update evidence, existing instructions, Governance,
policy/checkers, CI, and project contracts within the adoption boundary.
Explain evidence limitations instead of treating unavailable history as empty.
The planner supplies observations; it does not classify framework lineage or
interpret the authority of existing prose.

Select the corresponding comparison in that PR:

| State token | Procedure |
| --- | --- |
| `ungoverned` | Record the evidence establishing first adoption in an ungoverned brownfield. Validate against the actual pre-adoption commit using the current candidate rules. |
| `independent` | Record the evidence establishing independent existing governance and reconcile its relevant authority with incoming rules before editing. State the conflicts, overlaps, gaps, superseded wording, and intentional differences, their authority, and their dispositions. Then validate first adoption against the actual pre-adoption commit. |
| `update` | Use the [existing old-to-new comparison](POLICY_UPDATE.md#establish-the-bounded-comparison), including the real prior upstream revision and adoption evidence. Repository-policy checks retain historical checker/policy enforcement. |
| `ambiguous` | Record the available evidence and unresolved comparison/authority question. Resolve it under Governance before selecting a first-adoption or update basis; repository-policy validation rejects this state. |

For independent governance, reconcile repository-owned consumers of affected
rules, including paths or wording that differ from the template. Record
preservation, supersession, or already-satisfied decisions and the resulting
evidence in the PR. Retain useful historical material with its historical role
clearly identified. Validate concrete preserved project constraints with their
existing checks or bounded fixtures where mechanically observable. A nonempty
explanation alone does not establish that the candidate preserves them.

### Pass the comparison to validation

Use one optional fenced `framework-adoption` JSON block in the existing PR
body. This is a declaration for that PR, not persistent repository policy or
an adoption registry. For example, after completing independent-governance
characterization, replace the placeholders with the actual evidence:

````text
```framework-adoption
{
  "state": "independent",
  "baseline": "FULL_IMMUTABLE_PRE_ADOPTION_TARGET_COMMIT",
  "evidence": "Inspected history and authority references; incoming upstream repository and immutable revision; evidence that this is first adoption of this framework.",
  "authority_disposition": "Relevant independent constraints and authority; conflict/overlap/gap decisions; preserved differences and superseded wording with supporting authority and validation."
}
```
````

`state`, `baseline`, and nonempty `evidence` are required in an explicit
declaration. `independent` additionally requires `authority_disposition`.
The baseline must be a full immutable commit ID resolving to the exact
`--baseline-ref` target. A malformed, duplicate, stale, or ambiguous declaration
fails closed. Similar filenames or missing checker files never select a mode.
Without a declaration, or with `update`, the existing historical comparison
remains in force; missing required historical machinery remains a failure.

Save the actual proposed PR body outside the target repository and pass it to
the ordinary repository-policy check during first-adoption local validation:

```sh
python3.12 tools/ci/check_repo.py --baseline-ref origin/dev \
  --pr-body-file /absolute/path/to/adoption-pr-body.md
```

For a committed candidate, add `--candidate-ref FULL_CANDIDATE_COMMIT`.
The existing CI workflow passes its event through `--event-path`; the checker
reads the same PR-body declaration and verifies the event base commit against
the selected baseline. Use the actual base rather than an invented framework
snapshot. Updating this declaration changes the PR body and therefore requires
fresh [Stage 3 evidence](../GOVERNANCE.md#stage-3-hosted-pr-evidence).

The first-adoption comparison evaluates actual pre-adoption files under
candidate rules supplied in memory, reuses semantic source and storage
non-worsening checks, and separately checks current candidate coherence.
It never installs checker/policy files into historical state. It measures
repository-policy behavior; it cannot prove an evidence narrative's truth or
interpret independent authority. Complete the semantic reconciliation and
other applicable [validation stages](../GOVERNANCE.md#validation-evidence),
[issue-contract evidence](../GOVERNANCE.md#issue-contract-evidence), and
[risk path](../GOVERNANCE.md#risk) in the same adoption PR. This procedure does
not turn the planner's release-verification result into an adoption-completion
claim.

## Select a recovery lineage

Recovery `--lineage` selects canonical source history. It does not classify
framework adoption or establish a prior adopted upstream revision.

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
