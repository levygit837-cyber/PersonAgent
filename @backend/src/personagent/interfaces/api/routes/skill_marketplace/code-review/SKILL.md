---
name: Code Review
description: Review code changes for correctness, regressions, and missing tests.
allowed-tools: Read, Grep, Glob
argument-hint: [target]
when_to_use: Use when the user asks for a focused review of changed code or a specific implementation.
---
# Code Review

Prioritize findings over summaries. Inspect the real implementation before making claims.

Focus on:

- Correctness bugs and behavioral regressions.
- Missing validation, error handling, or edge cases.
- Security risks in inputs, auth, secrets, or filesystem access.
- Missing tests for changed behavior.

Report findings with file and line references when possible. If no findings are found, say that directly and note any residual test gaps.
