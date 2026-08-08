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

7. Implement only the issue scope.

8. Apply repository structure, asset, and content rules.

9. Run:
   - python3.12 tools/ci/check_repo.py
   - relevant tests
   - python3.12 -m unittest discover -s tools/tests -p 'test_*.py'
   - git diff --check

10. Push the work branch.

11. Create a draft PR into dev.

12. Include exactly one:

    Closes #<issue>

13. Apply exactly one:
    - risk:low
    - risk:high

14. Never downgrade automatically high-risk work.

15. For low risk, stop after publication and allow repository automation to
    continue.

16. For high risk, stop after publication and validation.

Never:

- branch from local dev;
- force-push;
- automatically mark high-risk work ready;
- automatically merge high-risk work;
- merge into main;
- create releases;
- perform unrelated cleanup.