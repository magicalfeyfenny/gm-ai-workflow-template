---
name: governed-change
description: Execute one repository change through issue, branch, validation, draft PR, and allowed merge policy.
---

# Governed change

1. Read GOVERNANCE.md and PROJECT_POLICY.toml.

2. Find the issue for the requested work.

3. If none exists, create one with:
   - summary;
   - acceptance criteria;
   - bounded scope;
   - expected risk.

4. Assign a newly created issue to the current user.

5. Run:

   git fetch origin dev

6. Create:

   work/<issue>-<slug>

   from origin/dev.

   Never create or use a `human/*` branch. That namespace is human-only.

7. Implement only the issue scope in coherent milestones.

8. Apply repository structure, asset, and content rules.

9. When a coherent milestone is ready, obtain Stage 1 milestone evidence under
   GOVERNANCE.md and commit it immediately to the current issue branch.
   Separate commit authorization is not required.

10. After the first meaningful commit:
   - push the work branch;
   - create a draft PR into dev;
   - omit the `Closes #<issue>` line while work remains;
   - apply exactly one of `risk:low` or `risk:high`.

   This publication permission applies to high-risk work. It does not grant
   readiness or merge authority.

11. Commit and push every later coherent milestone to the same draft PR.

12. Before declaring the whole issue complete, obtain valid Stage 2
    whole-issue local evidence under GOVERNANCE.md.

13. Never downgrade automatically high-risk work.

14. For low risk without `manual-merge`, only after the entire issue scope is
    complete and Stage 2 evidence is valid:
    - add exactly one `Closes #<issue>` line;
    - apply `work:complete`;
    - obtain Stage 3 hosted PR evidence for that completion metadata;
    - allow repository automation to mark the PR ready and configure squash
      auto-merge only after Stage 3 passes.

15. For high risk or `manual-merge`, only after the entire issue scope is
    complete and Stage 2 evidence is valid:
    - add exactly one `Closes #<issue>` line;
    - apply `work:review-ready`;
    - obtain Stage 3 hosted PR evidence for that completion metadata;
    - stop for human review, readiness, and merge.

Never:

- branch from local dev;
- force-push;
- leave a completed coherent milestone uncommitted while waiting for the whole
  issue to finish;
- add `Closes #<issue>`, `work:complete`, or `work:review-ready` before the
  entire issue scope is finished and Stage 2 evidence is valid;
- work a PR labeled `work:blocked` until its blockers are resolved;
- apply both completion labels;
- automatically mark high-risk work ready;
- automatically merge high-risk work;
- merge into main;
- create releases;
- create, modify, review, validate, label, ready, or merge a `human-created`
  PR;
- invoke a ruleset bypass;
- perform unrelated cleanup.
