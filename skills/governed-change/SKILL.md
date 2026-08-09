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

9. When a coherent milestone is ready, run proportionate validation and commit
   it immediately to the current issue branch. Separate commit authorization is
   not required.

10. After the first meaningful commit:
   - push the work branch;
   - create a draft PR into dev;
   - include exactly one `Closes #<issue>` line;
   - apply exactly one of `risk:low` or `risk:high`.

   This publication permission applies to high-risk work. It does not grant
   readiness or merge authority.

11. Commit and push every later coherent milestone to the same draft PR.

12. Before declaring the whole issue complete, run:
   - python3.12 tools/ci/check_repo.py --baseline-ref origin/dev
   - relevant tests
   - python3.12 -m unittest discover -s tools/tests -p 'test_*.py'
   - git diff --check

13. Never downgrade automatically high-risk work.

14. For low risk, apply `work:complete` only after the entire issue scope and
    validation are complete. If `manual-merge` is absent, allow repository
    automation to mark the PR ready and configure squash auto-merge.

15. For high risk, stop after publication and validation. A human controls
    readiness and merge.

Never:

- branch from local dev;
- force-push;
- leave a completed coherent milestone uncommitted while waiting for the whole
  issue to finish;
- apply `work:complete` before the entire issue scope is finished;
- automatically mark high-risk work ready;
- automatically merge high-risk work;
- merge into main;
- create releases;
- create, modify, review, validate, label, ready, or merge a `human-created`
  PR;
- invoke a ruleset bypass;
- perform unrelated cleanup.
