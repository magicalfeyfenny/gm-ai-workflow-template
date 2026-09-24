<Place the closing line here after work:complete or work:review-ready>

## Summary

State the completed outcome and what now works or is possible.

## Validation

What checks were run, if any?

For `risk:medium`, include at least one change-specific machine-verifiable
item using this exact form. Do not list only repository-policy, formatting, or
other generic checks:

`Focused validation: \`<test command or deterministic contract check>\``

For voluntary `risk:high` without an automatic-high trigger, include one or
more recognized structured bases using this exact form:

`High-risk basis: <governance-authority|ci-merge-release|security-credentials|destructive-operation|compatibility-migration|persistence-data-loss|cross-system-blast-radius|exceptional-uncertainty>`

`High-risk rationale: <optional explanatory context>`

Automatic-high triggers already establish the high-risk classification; a
structured basis is still useful context but is not required.

At completion, record the accepted issue revision and marker under
[Issue contract evidence](../GOVERNANCE.md#issue-contract-evidence).

For an interpretive governance correction, include the applicable
[policy correction boundary evidence](../GOVERNANCE.md#policy-correction-boundary-evidence).

## Adversarial review

For a completed governed change, record the candidate identity, disposition
summary, and any actionable handoff. Use the
[adversarial review and adjudication route](../GOVERNANCE.md#adversarial-review-and-adjudication).

## Human gate

For a high-risk or manual-path PR, record the remaining human action under the
applicable [risk and completion path](../GOVERNANCE.md#risk).

## Scope

List all systems or assets that were directly touched or affected, if any.
