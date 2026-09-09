# Task-local governance context audit — 2026-09-09

This is dated, non-normative evidence for [Issue #104](https://github.com/magicalfeyfenny/gm-ai-workflow-template/issues/104).
It is not an instruction entrypoint, policy summary, loading registry, or ongoing
word budget. [Governance](../../GOVERNANCE.md#authority) remains the shared
normative authority; [PROJECT_POLICY.toml](../../PROJECT_POLICY.toml) owns
configured executable values.

## Baseline and issue boundary

Before: `27b2243b31fbb29c1a0c04b3c9614610be4b1f57`, current upstream `dev` after
#98/#101, #99/#102, and #100/#103 merged. Those policies were settled inputs.
After: `f73e859b589baafc0abf253b7f1e7d4cd1e7671f`, the routing milestone in
[PR #105](https://github.com/magicalfeyfenny/gm-ai-workflow-template/pull/105).
The subsequent report commit does not change the measured surfaces.

One High-risk issue is sufficient. Heading boundaries, explicit task routes,
skill deduplication, structural checks, and this report jointly deliver one
observable outcome: less unrelated policy to read and reconcile for the same
task. They do not have independently useful acceptance boundaries here. No
additional optimization or substantive correction issue was needed.

## Method and limits

Count whitespace-delimited words (`len(text.split())`) in manually traced task
routes. Read whole entrypoints and selected skills. A selected Markdown section
includes its heading and descendants until the next peer or ancestor heading;
a TOML table runs until the next table. Union overlapping selections within a
file, so a direct child link does not count its text twice. Counts include
Markdown notation, link destinations, comments, and command examples.

Follow conditional routes only when the scenario needs them. Do not recursively
load every hyperlink. For example, a CI-extension link does not make extension
instructions necessary for a task that only runs existing tests. The baseline
skills explicitly routed production code through compatibility and all governed
work through runtime validation; after this change those full sections are
conditional. Contract-oriented validation remains an explicit common route.
Fresh setup still reads inventory authority, which its procedure links directly.

These are reproducible context-surface estimates, not observed model token usage
or a claim that every agent reads the same way. They exclude implementation
source, external engine documentation, assets, live tracker payloads, tool output,
global personal instructions, and this report. Such task evidence remains
necessary when applicable; this pass does not claim to reduce it. Words are
sufficient for comparison; no tokenizer or repository-size acceptance gate is
introduced.

Whole-file entrypoint reads model a common skill/document loading pattern. An
agent already taking only a parent heading's own paragraphs would avoid much of
the incidental descendant cost before this change. A brownfield reader that
stops at SETUP's early redirect also avoids most of that file. The direct routes
still remove that decision/detour, but the table's full-file savings are not
promised for those readers. Explicit file/section boundaries make selective
reading practical without requiring an agent to infer which descendants belong.

## Representative routes and results

All routes start at `AGENTS.md` and read Governance's Authority section. A
completed implementation additionally follows the governed-change skill through
issue selection, branch/unit of work, validation planning, all three evidence
stages, risk, completion, the applicable low/manual path, CI requirements, and
`docs/CI.md#issue-contract-attestation`. Only affected policy tables are read.

| Scenario | Before words | After words | Reduction |
| --- | ---: | ---: | ---: |
| Ordinary low-risk GameMaker implementation | 8,171 | 5,679 | 30.5% |
| Authored raster asset change | 9,255 | 6,065 | 34.5% |
| High-risk governance routing change | 6,803 | 4,444 | 34.7% |
| Stewardship audit | 4,626 | 2,614 | 43.5% |
| Fresh generated-repository setup | 2,771 | 2,555 | 7.8% |
| Brownfield characterization | 3,245 | 1,888 | 41.8% |
| Scoped performance implementation | 8,171 | 5,881 | 28.0% |

- **Ordinary code:** bounded gameplay behavior change, with no asset work,
  representation replacement, or runtime launch needed. AGENTS → governed-change
  + gamemaker-production → Production code, Source structure, native engine
  decision, and shared lifecycle. Reads `[structure]` and `[risk]`. The native
  decision's relevant engine evidence is additional task evidence, outside this
  governance-only estimate.
- **Asset:** authorized non-final raster asset edit, with no gameplay code,
  deterministic scaffolding, or runtime launch needed. Before, AGENTS/governed-change
  → gamemaker-production → asset-production. After, both enter asset-production
  directly. Derived assets still includes runtime representation and export
  topology; asset completion/authority and native GameMaker decisions remain
  required. Reads `[assets]`, `[assets.pipelines.raster]`, and `[risk]`.
- **Policy:** routing-only governance change with structural tests, using the
  manual/high-risk completion path, Source structure, `[structure]`, and `[risk]`.
  An interpretive correction would additionally select Policy correction boundary
  evidence; this mechanical scenario does not require an artificial neighboring
  case. The authoritative distinction remains available and unchanged.
- **Stewardship:** live tracking/ownership and ordinary acceptance/validation
  audit, including unjustified manual or generic-smoke requirements. AGENTS →
  project-steward → Issue authority, Human-created changes, validation allocation,
  and runtime validation. No asset, compatibility, or native-engine dispute is
  present. This is a direct audit; a scheduled audit also reads its existing
  automation prompt.
- **Fresh setup:** generated repository, no imported-library exception,
  production-suite extension, or recovery. AGENTS → SETUP → Authority, Inventory
  authority, Human-created changes for bypass limits, and Candidate storage.
  Links describing installed lifecycle labels do not initiate implementation.
- **Brownfield:** read-only characterization including existing-release evidence.
  Before, AGENTS → SETUP → ADOPTION. After, AGENTS → ADOPTION directly. Reads
  Branches and Releases for source/tree, provenance, and artifact evidence. It
  does not initiate separately authorized application, bootstrap, or policy update.
- **Performance:** scoped GameMaker performance implementation follows the code
  route plus Interactive runtime validation for its concrete measurement purpose.
  No separate diagnostic/performance procedure exists or is needed. Before, the
  same runtime section was already loaded for ordinary code; after, this route
  deliberately retains its 202-word specialized obligation.

## Why the routes shrink

The baseline parent headings accidentally included these specialist sections:

| Baseline selection | Words including descendants | Own words | Incidental descendants |
| --- | ---: | ---: | --- |
| Authority | 453 | 106 | Inventory authority; Policy updates |
| Issue authority | 2,026 | 619 | Compatibility; scheduled claims; mixed placeholders; scheduled continuation |
| Unit of work | 911 | 104 | Contract validation; allocation; policy correction; runtime validation |
| Validation coverage allocation | 481 | 242 | Policy correction boundary evidence |

These specialists are now sibling sections in the same Governance document,
with the same anchors and text. No normative modules were introduced. The
coupled Asset completion, Native GameMaker, Derived assets, Validation evidence,
and Completion transition subsections remain together. In particular, removing
a redundant asset-skill link did not remove runtime representation or export
topology from the Derived assets read.

A paragraph defining when deferred work warrants a follow-up moved verbatim
from governed-change to Issue authority. Issue authority therefore gains 34
words while unrelated descendant policies stop being loaded with it.

The following are manually identified decision families, not parser-derived
semantic scores. Each row identifies actual before/after reconciliation points;
remaining procedural detail and short critical-stop reminders are intentional.

| Decision family / affected routes | Before: copies or overlapping decisions encountered | After: resolution and retained guidance |
| --- | --- | --- |
| Scope and deferred work — code, asset, policy, performance | Issue authority; governed Issue selection's repeated atomicity explanation and separately located follow-up rule; Unit of work; AGENTS scope stop | Detailed selection resolves to Issue authority, including the relocated rule. The skill routes there; unit/branch mechanics and the stop remain. |
| Validation and runtime purpose — code, asset, policy, performance, stewardship | Governance allocation/runtime; governed Execute 3 and stops; GameMaker default 10; stewardship's last three validation stops | Removed governed and GameMaker explanatory copies and stewardship's two trailing explanations. Allocation and applicable runtime decisions resolve to Governance; concise pre-mutation stops remain. Ordinary code/asset/policy no longer load the full runtime section. |
| Native sufficiency — code, asset, performance | Native GameMaker; GameMaker Production procedure and default 1; asset source/runtime explanation | Native GameMaker owns the decision and evidence. Skills link to it; IDE and authoring guidance remain. Asset work no longer loads unrelated gameplay defaults. |
| Asset state versus work — asset; asset-specific stewardship | Asset completion/authority; mixed-work section accidentally under Issue authority; governed Issue selection; three asset-skill explanations; steward stop | Removed skill explanations; retained conditional authoritative routes and concrete PR-handoff procedure. Steward reports approval-only tracking for human disposition through Replacement and promotion. |
| Source/export/runtime — asset | Derived assets plus asset default 2; additional transitive GameMaker native guidance | Derived assets owns the distinction. Asset skill retains practical source-format, editing, conversion, and export-verification guidance. |
| Issue revision and evidence — completed code, asset, policy, performance | Governance stages and Issue contract evidence; governed Execute 5's detailed repetition; CI command procedure | Skill routes to Issue contract evidence and directly to the CI attestation commands. Stage-specific authority and executable command details remain in their existing locations. |
| Compatibility — ordinary code/performance versus replacement work | Unconditional production-code route plus conditional prose in Production code and production defaults; also nested under Issue authority | Replacement/rename/representation work still routes explicitly to compatibility. Unrelated behavior edits no longer read its full definition. No compatibility rule was weakened. |
| Authority and startup choice — setup/brownfield | Authority also loads upstream policy-update procedure; brownfield goes through generated setup before adoption | Shared Authority is local. Setup still reaches its inventory/bypass/storage obligations. Existing adoption directly reaches ADOPTION, while bounded updates retain their separate existing route. |

The ordinary-code route removes scope, validation, native, and issue-evidence
explanatory copies; assets remove those plus asset-state and source/runtime
copies and the entire GameMaker detour. Stewardship removes repeated validation
explanations and links native/asset stops to their governing decisions. Setup
and brownfield retain their procedural explanations; their improvement is
routing locality rather than deduplicating useful specialization.

## Preservation evidence and scope limits

A mechanical comparison of the two Governance versions, ignoring heading depth
and removing the one verbatim relocated paragraph, found identical body text.
All existing anchors remain. This establishes the bounded textual relocation;
it is audit evidence, not an ongoing exact-prose test.

The preserved body includes authority versus evidence, inherited state versus
new obligations, compatibility evidence, completion levels and human promotion,
native sufficiency and demonstrated exceptions, explicit direction for human
experiential validation, issue-contract revision binding, policy-update consumer
propagation, and legitimate neighboring cases for interpretive corrections.
Critical mutation stops in AGENTS and governed-change remain. Steward-specific
evidence sources, per-run limits, reporting boundaries, and non-mutation stops
remain. Unique GameMaker production and asset-authoring guidance remains.

SETUP, ADOPTION, POLICY_UPDATE, CI procedures, scheduled prompts, issue/PR
contracts, executable policy, validators, and runtime code are unchanged. The
brownfield planner retains characterization before separately authorized action;
a bounded policy update still does not require a recovery or release sweep.
No examples, history, or archaeology were moved merely to shrink Governance:
they were not the main source of accidental context in these routes.

The focused routing suite passes 14 tests. New checks establish heading
containment boundaries, direct asset/adoption/attestation routes, and retained
coupled asset obligations. They do not parse policy semantics, freeze exact
wording/order/heading depth, impose word budgets, or prove future agent obedience.
Existing checks continue to cover specialized authority links.

Governance's total grows from 7,916 to 7,950 words. That descriptive increase
coexists with smaller representative routes; neither total Governance nor total
repository words is a pass/fail criterion. This report adds historical evidence
outside every measured hot route. The retained Human-created changes section
still includes checker-baseline detail not always needed by stewardship; no
further optimization obligation is inferred from that observation.

## Exact selections for reproduction

The following tables record inclusive line ranges at the immutable commits
above. A `+` joins disjoint ranges within one file; each selected line is counted
once. Full-file reads are also recorded as ranges. These tables are dated
measurement inputs, not a maintained policy index or task-loading instruction.

To reproduce any cell, use Python 3.12 with its commit, path, and ranges, then
sum the file results for the route. For example, the baseline Authority section:

```python
import subprocess

commit = "27b2243b31fbb29c1a0c04b3c9614610be4b1f57"
path = "GOVERNANCE.md"
ranges = [(3, 65)]
lines = subprocess.check_output(
    ["git", "show", f"{commit}:{path}"], text=True,
).splitlines(keepends=True)
selected = {i for start, end in ranges for i in range(start - 1, end)}
print(len("".join(lines[i] for i in sorted(selected)).split()))  # 453
```

### Ordinary GameMaker implementation

| File | Before ranges | Words | After ranges | Words |
| --- | --- | ---: | --- | ---: |
| `AGENTS.md` | 1–64 | 430 | 1–66 | 462 |
| `.agents/skills/governed-change/SKILL.md` | 1–127 | 832 | 1–108 | 602 |
| `GOVERNANCE.md` | 3–331 + 403–652 + 713–807 + 847–903 + 982–1054 + 1105–1141 | 5748 | 3–20 + 66–154 + 407–515 + 581–656 + 717–811 + 851–907 + 986–1058 + 1109–1145 | 3587 |
| `docs/CI.md` | 156–216 | 420 | 156–216 | 420 |
| `.agents/skills/gamemaker-production/SKILL.md` | 1–92 | 655 | 1–78 | 522 |
| `PROJECT_POLICY.toml` | 3–32 + 102–120 | 86 | 3–32 + 102–120 | 86 |

### Authored raster change

| File | Before ranges | Words | After ranges | Words |
| --- | --- | ---: | --- | ---: |
| `AGENTS.md` | 1–64 | 430 | 1–66 | 462 |
| `.agents/skills/governed-change/SKILL.md` | 1–127 | 832 | 1–108 | 602 |
| `GOVERNANCE.md` | 3–652 + 713–807 + 847–968 + 1105–1141 | 6245 | 3–20 + 66–154 + 336–515 + 581–656 + 717–811 + 851–972 + 1109–1145 | 4084 |
| `docs/CI.md` | 156–216 | 420 | 156–216 | 420 |
| `.agents/skills/asset-production/SKILL.md` | 1–90 | 584 | 1–72 | 408 |
| `.agents/skills/gamemaker-production/SKILL.md` | 1–92 | 655 | not selected | 0 |
| `PROJECT_POLICY.toml` | 54–62 + 70–76 + 102–120 | 89 | 54–62 + 70–76 + 102–120 | 89 |

### High-risk governance routing change

| File | Before ranges | Words | After ranges | Words |
| --- | --- | ---: | --- | ---: |
| `AGENTS.md` | 1–64 | 430 | 1–66 | 462 |
| `.agents/skills/governed-change/SKILL.md` | 1–127 | 832 | 1–108 | 602 |
| `GOVERNANCE.md` | 3–331 + 403–652 + 713–795 + 808–820 + 1029–1054 + 1105–1141 | 5035 | 3–20 + 66–154 + 407–515 + 581–656 + 717–799 + 812–824 + 1033–1058 + 1109–1145 | 2874 |
| `docs/CI.md` | 156–216 | 420 | 156–216 | 420 |
| `PROJECT_POLICY.toml` | 3–32 + 102–120 | 86 | 3–32 + 102–120 | 86 |

### Stewardship

| File | Before ranges | Words | After ranges | Words |
| --- | --- | ---: | --- | ---: |
| `AGENTS.md` | 1–64 | 430 | 1–66 | 462 |
| `.agents/skills/project-steward/SKILL.md` | 1–96 | 613 | 1–90 | 528 |
| `GOVERNANCE.md` | 3–331 + 472–576 + 653–712 | 3583 | 3–20 + 66–154 + 476–515 + 548–580 + 657–716 | 1624 |

### Fresh setup

| File | Before ranges | Words | After ranges | Words |
| --- | --- | ---: | --- | ---: |
| `AGENTS.md` | 1–64 | 430 | 1–66 | 462 |
| `docs/SETUP.md` | 1–199 | 1042 | 1–199 | 1042 |
| `GOVERNANCE.md` | 3–65 + 653–712 + 1055–1104 | 1299 | 3–34 + 657–716 + 1059–1108 | 1051 |

### Brownfield characterization

| File | Before ranges | Words | After ranges | Words |
| --- | --- | ---: | --- | ---: |
| `AGENTS.md` | 1–64 | 430 | 1–66 | 462 |
| `docs/ADOPTION.md` | 1–159 | 1103 | 1–159 | 1103 |
| `GOVERNANCE.md` | 3–65 + 403–430 + 821–846 | 670 | 3–20 + 407–434 + 825–850 | 323 |
| `docs/SETUP.md` | 1–199 | 1042 | not selected | 0 |

### Scoped performance implementation

| File | Before ranges | Words | After ranges | Words |
| --- | --- | ---: | --- | ---: |
| `AGENTS.md` | 1–64 | 430 | 1–66 | 462 |
| `.agents/skills/governed-change/SKILL.md` | 1–127 | 832 | 1–108 | 602 |
| `GOVERNANCE.md` | 3–331 + 403–652 + 713–807 + 847–903 + 982–1054 + 1105–1141 | 5748 | 3–20 + 66–154 + 407–515 + 548–656 + 717–811 + 851–907 + 986–1058 + 1109–1145 | 3789 |
| `docs/CI.md` | 156–216 | 420 | 156–216 | 420 |
| `.agents/skills/gamemaker-production/SKILL.md` | 1–92 | 655 | 1–78 | 522 |
| `PROJECT_POLICY.toml` | 3–32 + 102–120 | 86 | 3–32 + 102–120 | 86 |
