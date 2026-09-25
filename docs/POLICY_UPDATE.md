# Update policy in an adopted repository

Use this procedure when a repository with evidence-backed earlier adoption of
this framework takes a newer upstream governance or policy revision. First
adoption in an ungoverned brownfield, first adoption with independent existing
governance, and ambiguous states start at the
[adoption comparison procedure](ADOPTION.md#establish-the-framework-comparison)
under [Framework adoption lineage](../GOVERNANCE.md#framework-adoption-lineage).
[Policy updates](../GOVERNANCE.md#policy-updates)
owns the update contract; the existing
[governed-change lifecycle](../.agents/skills/governed-change/SKILL.md) owns the
implementation, evidence stages, and publication authority.

## Establish the bounded comparison

1. Find the previous adoption or update PR and its recorded upstream revision.
   Resolve that revision to an exact commit SHA in the upstream repository.
   Identify the new upstream revision by its exact commit SHA as well; retain
   the repository identity and the prior adoption evidence in this update PR.
   A local tracking branch or an old template file alone does not establish
   which upstream revision the project adopted. If the prior revision cannot
   be established, record the evidence gap and resolve that baseline before
   claiming a complete old-to-new comparison.
2. Compare those upstream commits for the policy outcome authorized by the
   issue. Identify the changed rule or executable value and its upstream
   source paths or sections. Start with that policy boundary and follow its
   actual downstream consumers. Do not start by treating every difference
   between the project and template as work.
3. Record each affected repository-owned consumer, why it encodes or enforces
   the changed policy, and the required action. Depending on the rule, consumers
   can include instructions, issue forms, PR templates, skills, scheduled
   prompts, configuration, validators, CI, or tests. These are places to inspect
   when relevant, not a mandatory inventory for every update. A surface can
   already satisfy the new rule; record that evidence without changing it.
4. Identify any intentional project-specific difference encountered within the
   comparison. Cite its independent project contract or explicit human
   direction and explain how the update preserves it. Textual differences,
   historical template behavior, and the existence of local code alone do not
   establish a preservation obligation; apply
   [Compatibility obligations](../GOVERNANCE.md#compatibility-obligations).
   Note unrelated differences already encountered as excluded scope without
   expanding the search into a cleanup inventory.
5. Update the changed policy and all affected consumers together. Select checks
   that establish their intended behavior under
   [Validation coverage allocation](../GOVERNANCE.md#validation-coverage-allocation).
   Keep the revision comparison, consumer decisions, preserved differences,
   and resulting evidence in the adoption/update PR.

When the changed policy has no downstream consumer, record which policy was
compared and the evidence for that conclusion. An empty consumer list alone
does not explain the conclusion. No consumer means no manufactured file edit,
migration, or follow-up obligation. The PR evidence can record the assessed
policy revision without claiming that the project copied every upstream file.

## Shared semantics and inherited concerns

For an update of an earlier evidence-backed adoption, the newly selected
immutable upstream commit defines the shared semantics to reconcile. Review
whether the local candidate adopts that behavior faithfully and whether each
difference has independent project-specific authority. Do not redesign or
strengthen the selected upstream policy as part of a downstream update.

A defect already present unchanged in the selected upstream revision is an
upstream concern, not an actionable downstream correction by itself. Report it
for upstream disposition when useful. Treat a downstream adaptation defect or
a violation of an independent local requirement as actionable. Do not require
byte-for-byte identity where an authorized adaptation or another justified
local consumer differs.

Issue authority is repository-local: this downstream issue authorizes
mutations only in the repository that owns it. A downstream reconciliation
may report an inherited upstream concern for human disposition, but as part of
that issue do not create, modify, claim, or execute upstream issues, branches,
pull requests, files, or other work. The existence of a related upstream issue
does not grant cross-repository authority. Cross-repository work requires
separate explicit human direction naming the target repository and the work to
perform. The update PR should identify intentional local differences and
their authority, and can note inherited upstream concerns without turning
them into downstream remediation scope.

## Reuse adoption evidence only where relevant

The brownfield planner's [existing evidence](ADOPTION.md#read-the-evidence) can
support a policy update when branch identity, protection, tracking, or other
observed state matters to the selected rule. Its report remains read-only;
proposed settings or ruleset changes do not become authorized update scope.

A bounded policy update does not require a new recovery-lineage selection,
release-verification sweep, bootstrap, or application of every planner proposal.
Use the fuller [adoption and recovery route](ADOPTION.md) when the actual task
requires that evidence. Refresh any reused observations that the proposed
change depends on before mutation.

## PR evidence layout

Use the existing PR Summary, Scope, and Validation sections, or copy the layout
below into that PR. This is an optional presentation, not a new metadata schema
or separate registry. Link existing evidence rather than generating policy
snapshots or a synchronization database.

```text
Upstream repository:
Previously adopted upstream commit SHA:
Prior adoption/update PR or other adoption evidence:
New upstream commit SHA:
Changed policy boundary and upstream source paths/sections:

Affected consumers:
- Path or section:
  Connection to the changed policy:
  Action (updated, or already satisfies the new rule with evidence):
  Validation and result:

Intentional project-specific differences:
- Difference, independent authority, and preservation decision:

Unrelated differences encountered and excluded from scope:

If no downstream consumer exists:
- Compared policy, relevant inspection, and reason no consumer is affected:
```

Omit inapplicable rows or state that none were found within the bounded
comparison. Do not turn omitted or unrelated surfaces into a standing backlog.
