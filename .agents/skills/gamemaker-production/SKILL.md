---
name: gamemaker-production
description: Make production GameMaker changes while preserving readable architecture, tests, content data, and source/runtime asset boundaries.
---

# GameMaker production

Read:

- AGENTS.md
- GOVERNANCE.md
- PROJECT_POLICY.toml

## Code

For repository-owned production GML, follow the style, readability, and
simplicity rules in AGENTS.md and GOVERNANCE.md. Preserve imported libraries
instead of restyling or simplifying them.

Give every source file one primary responsibility.

Do not create generic helper or utility dumping grounds.

Respect the source-size limit.

When reusing an older project:

1. identify the useful behavior;
2. understand its assumptions;
3. adapt it to current architecture;
4. leave unrelated legacy structure behind.

## Assets

Use:

Vector:
- Inkscape `.svg`
- plain runtime `.svg`

Raster:
- `.kra`
- runtime `.png`

Music:
- `.mid`
- `.logicx`
- runtime `.flac`, 48 kHz stereo

Sound effects:
- `.logicx`
- runtime `.wav`, 48 kHz stereo

3D:
- `.blend`
- `.obj` and `.mtl`
- runtime `.vbuff`

Derived runtime assets must be mapped in assets/exports.json.

## GameMaker data

Use canonical `.json` under content/ for:

- stories;
- saves;
- bullet patterns;
- levels and stages;
- encounters;
- cached GameMaker data.

The same JSON is source and runtime data.

## GameMaker resources

Preserve valid GameMaker resource relationships.

Treat project configuration, extensions, core architecture, persistence, save
code, and migrations as high risk.

## Validation

Run the narrowest relevant tests first.

Then run all required repository checks.

For visual behavior, report actual observed results rather than inferring
visual correctness from code.
