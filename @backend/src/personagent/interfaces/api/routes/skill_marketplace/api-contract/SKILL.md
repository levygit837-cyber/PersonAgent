---
name: API Contract
description: Design or review backend/frontend API contracts and compatibility.
allowed-tools: Read, Grep, Glob
argument-hint: [endpoint or flow]
when_to_use: Use when changing request or response shapes shared across frontend and backend.
---
# API Contract

Treat wire shapes as product contracts. Keep compatibility explicit.

Specify:

- Request fields, response fields, and error shapes.
- Defaults, nullable fields, and persistence behavior.
- Frontend cache keys and invalidation points.
- Tests that prove old and new clients behave correctly.

Avoid adding fields that are not used by a real consumer.
