# Architecture Decision Records

Use ADRs for durable decisions that affect architecture, persistence,
integration contracts, provider behavior, or desktop/backend ownership.

## Status Values

- `Proposed`: under discussion, not yet implemented.
- `Accepted`: current intended direction.
- `Superseded`: replaced by a newer ADR.
- `Deprecated`: intentionally moving away from this decision.

## Naming

Use monotonically increasing files:

```text
docs/adr/0001-short-title.md
docs/adr/0002-short-title.md
```

## Template

```markdown
# ADR 0001: Short Title

Date: YYYY-MM-DD
Status: Proposed | Accepted | Superseded | Deprecated

## Context

What problem, constraint, or tradeoff forced this decision?

## Decision

What are we choosing?

## Consequences

What becomes easier, harder, riskier, or explicitly out of scope?

## Alternatives Considered

What did we reject and why?

## Validation

What tests, runtime checks, or operational evidence prove this decision works?
```

## When To Add An ADR

- A new persistence table, migration strategy, or schema boundary is introduced.
- API, SSE, WebSocket, or tool contracts change in a way clients must honor.
- Provider routing, model payload semantics, or credential ownership changes.
- A subsystem is removed, renamed, or moved across backend/desktop boundaries.
- A reliability, security, or performance tradeoff becomes part of the product.
