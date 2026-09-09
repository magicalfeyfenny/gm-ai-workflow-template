# Extend the required Tests check

[Governance](../GOVERNANCE.md#ci) owns the CI requirements. This document owns
the project extension procedure for [the CI workflow](../.github/workflows/ci.yml).

The `template-tests` job runs the template's Python unittest suite. The `tests`
job publishes the stable required check name `Tests` and evaluates its required
constituent jobs with [aggregate_tests.py](../tools/ci/aggregate_tests.py).
An empty template requires only `template-tests`; no GameMaker runner,
credentials, or build infrastructure is needed.

## Result contract

The aggregate job declares the same job IDs in two places:

- `needs` tells GitHub which jobs to wait for and makes their results available.
- `REQUIRED_TEST_JOBS` is a JSON array declaring every required constituent.
  It must be nonempty, contain unique IDs, and include `template-tests`.

The evaluator receives GitHub's dependency results through
`TEST_JOB_RESULTS: ${{ toJSON(needs) }}`. The result keys must exactly match the
declared required IDs. Every constituent must have `result: success`.

| Constituent evidence | Aggregate outcome |
| --- | --- |
| Every declared job succeeds with no reported evidence limitation | Success |
| Any job fails, is cancelled, or is skipped | Failure |
| Any job reports an `evidence_limitation` | Failure |
| A required result is missing, or an undeclared result appears | Failure |
| Configuration or result data is empty, malformed, or unsupported | Failure |

The aggregate uses `if: ${{ always() }}` so dependency failure or skipping
does not prevent the decision job from running. This follows GitHub's
[dependency semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds).
Cancellation of the entire run can still prevent execution or cancel the
aggregate; that produces no successful `Tests` evidence. `always()` is a
scheduling condition, not permission to treat incomplete evidence as passing.

The evaluator uses Python's standard library. The template test job
also installs the pinned dependencies in
[tools/tests/requirements.txt](../tools/tests/requirements.txt) to inspect
workflow structure semantically. Follow the
[local setup commands](SETUP.md#validate-the-generated-repository) before
running those tests.

## Add a project suite

Add a small, explicitly named job to the existing `CI` workflow, then add its
ID to both aggregate declarations. Keep `template-tests` and the aggregate
name `Tests`. No branch-protection status rename is needed.

For a project that already provides `tools/run_project_tests.py`, add the
following `project-tests` job under `jobs` and replace the existing `tests`
job with the version shown. The other jobs remain in the workflow.

```yaml
  project-tests:
    name: Project tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.12"
      - name: Run project suite
        run: python3 tools/run_project_tests.py

  tests:
    name: Tests
    if: ${{ always() }}
    needs: [template-tests, project-tests]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    env:
      REQUIRED_TEST_JOBS: '["template-tests", "project-tests"]'
      TEST_JOB_RESULTS: ${{ toJSON(needs) }}
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.12"
      - name: Evaluate required test jobs
        run: python3 tools/ci/aggregate_tests.py
```

Replace the project command and runner with the project's actual automated
suite and execution environment. The command must exit unsuccessfully when
required execution or evidence is absent. GameMaker/GMTL, deterministic
runtime checks, and packaging or build validation use the same constituent
contract; adding a build check does not authorize publishing its output.

Keep constituent checkouts on the same PR candidate as `template-tests` and
the aggregate. The example uses the existing workflow's default checkout,
which selects the PR merge candidate. Preserve the `pull_request` trigger,
read permissions, PR metadata capture, and separate governed merge workflow.
Do not move candidate test execution into a privileged merge workflow.

All external Actions references must use verified immutable full commit SHAs,
with readable version comments. Verify each SHA in the action's own upstream
repository, as described in GitHub's
[secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions).
Update the pin and comment together when an action update is authorized.

## Keep required evidence complete

Every dependency listed in the aggregate is required. Do not add optional
entries to its dependency list or enable `continue-on-error` for a required
job or step. A required suite must actually run and pass: a conditional step
that skips the suite while the surrounding job succeeds is not valid evidence.
Do not hide missing prerequisites with a successful fallback command.

This extension contract uses ordinary, fixed, individually named jobs for
independent required obligations. The aggregate sees one result per directly
declared dependency, as defined by GitHub's
[needs context](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#needs-context).
It does not inspect individual matrix members or jobs inside a reusable
workflow. Matrix and reusable-workflow aggregation are outside this small
extension contract; split independent obligations into ordinary named jobs.

If a licensed toolchain, runner, credentials, or other execution support is
unavailable, report an automated execution/evidence limitation and fail the
required job. This leaves `Tests` unsuccessful; it does not create a human
playtesting requirement or substitute human observation for automated evidence.
A runner that cannot start may leave a job pending until timeout or
cancellation, also without successful evidence. Provisioning runners and
credentials is project-specific setup outside this template.

A project job may expose an optional `evidence_limitation` output from its
failing prerequisite step to explain the limitation in the aggregate's
diagnostics. A nonempty limitation also rejects a nominally successful result;
omit it or leave it empty when execution succeeds. For example, assign the
step `id: prerequisites`, declare
`outputs.evidence_limitation: ${{ steps.prerequisites.outputs.evidence_limitation }}`
on the job, and have the unavailable-capability branch emit:

```sh
echo 'evidence_limitation=Required project toolchain is unavailable' >> "$GITHUB_OUTPUT"
echo 'Required project toolchain is unavailable' >&2
exit 1
```

The message must describe the missing capability without exposing credentials.
An absent diagnostic output never excuses a failed, cancelled, skipped, or
missing required result.

## Validate an extension

Run the template unittest suite, including the workflow contract and aggregate
result fixtures, using the local setup commands linked above. Exercise each
added suite's failure and unavailable-capability paths and verify that it
cannot report success without executing its required checks. After publishing
the candidate PR, verify fresh `Tests` evidence alongside the unchanged
required PR policy, Repository policy, and Format checks. The governed
[validation stages](../GOVERNANCE.md#validation-evidence) still apply.

## Issue contract attestation

[Issue contract evidence](../GOVERNANCE.md#issue-contract-evidence) owns the
completion rule. Before Stage 2, read the governing issue with the existing
GitHub CLI login or a token with issue read access:

```sh
python3.12 -m tools.ci.issue_contract \
  --repository OWNER/REPO --issue-number NUMBER
```

The JSON output contains the canonical contract, its `sha256`, and an
`acceptance_marker`. Reconcile the displayed contract with the authorized work
and preserve its revision with the PR's validation evidence. Re-run the command
before the completion transition. If the revision still matches that evidence,
copy the exact marker into the PR body alongside the existing closing line and
completion label. The marker has this fixed protocol grammar:

```text
<!-- issue-contract:v1 #NUMBER sha256:LOWERCASE_SHA256 -->
```

`pr_metadata.py capture` re-fetches the issue for completed agent-governed PRs
and refuses to attest a different revision, a missing marker, a closed issue,
or unresolved blockers. It does not require issue evidence for intermediate
milestones or human-created changes. Native dependencies come from GitHub's
[issue relationships](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies),
with complete paginated reads; dependency prose is retained within the issue
body without interpreting it as a separate dependency graph.

The existing `pr-metadata-RUN-ATTEMPT` artifact now uses schema version 2 and
includes `issue_contract` (`number` and `sha256`, or null for exempt states).
Old schema artifacts cannot establish this binding and require fresh CI.
Rerunning CI alone cannot accept an issue change: first reconcile the changed
contract and its evidence, then replace the marker. Unchanged mechanical
results may remain useful as described in Governance. Comments and reactions
do not change the revision; harmless edits to title/body may change it without
constituting a semantic defect.

For a manual handoff, download the final run's metadata artifact and save a
fresh structured PR read using `gh pr view --json
number,baseRefName,headRefName,headRepository,headRefOid,body,labels`. Then run:

```sh
python3.12 tools/ci/pr_metadata.py compare \
  --attestation-path PATH/TO/pr-metadata.json \
  --current-pr-path PATH/TO/current-pr.json \
  --repository OWNER/REPO --pull-request-number PR_NUMBER \
  --head-sha HEAD_SHA --run-id RUN_ID --run-attempt RUN_ATTEMPT
```

Comparison re-fetches the governing issue. Exit 0 means the live PR and issue
match; exit 3 means stale evidence; invalid, missing, or unavailable evidence
fails closed. Optional `capture --issue-path` and `compare
--current-issue-path` inputs support synthetic fixtures; a saved fixture is not
a live completion check. Low-risk automation uses its read token to re-fetch
the issue in both existing PR/file windows, including after readiness. These
reads reject issue drift and revoke a pending merge request when the PR still
matches the attested metadata. Older runs leave newer PR metadata alone. These
checks do not continuously invalidate GitHub check badges or watch an already
queued native merge; recheck the issue before a later manual action.
