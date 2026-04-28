---
name: Debug Root Cause
description: Reproduce a bug, isolate the real cause, and avoid symptom-only patches.
allowed-tools: Read, Grep, Glob, Bash
argument-hint: [symptom]
when_to_use: Use when a runtime issue needs diagnosis before implementation.
---
# Debug Root Cause

Start from the reported behavior and trace the live path that produces it.

Work in this order:

- Reproduce or identify the exact failing path.
- Inspect the nearest runtime, state, API, and persistence boundaries.
- Separate stale state, configuration, and transport issues from implementation defects.
- Patch the smallest code path that fixes the cause.

Validate with a command or test that exercises the same path the user hit.
