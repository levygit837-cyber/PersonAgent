# ADR 0009: Plan Mode with Structured State and HMAC-SHA256 Action Approvals

Date: 2025-06-10
Status: Accepted

## Context

When the agent proposes multi-step mutations (file writes, git commits, shell commands), the user must review the plan before execution. We need a durable, structured state machine that survives page reloads and a cryptographically verifiable approval mechanism for destructive actions.

## Decision

**Plan Mode state machine**
- State is stored in `Conversation.metadata` under the key `plan_mode` (structured dict), maintaining backward compatibility with the legacy boolean.
- States: `inactive` -> `draft` -> `awaiting_approval` -> `approved`/`cancelled`.
- `plan_mode.py` centralizes all state transitions: `activate_plan_mode_if_requested()`, `auto_finalize_plan_mode()`, `normalize_plan_state()`.

**Action Approvals**
- Desktop (Electron main) owns the signing secret (`~/.cache/personagent/action_approval_secret`, 48 random bytes, base64url, `chmod 600`).
- `createSignedActionApproval()` produces: `approval_id`, `action_kind`, `args_hash`, `expires_at`, `approval_signature` (HMAC-SHA256 over the payload).
- Backend validates the signature before executing protected actions (`workspace.git_commit`, `workspace.git_push`, `workspace.git_pr`).
- TTL: 300 seconds; expired approvals are rejected.

**Tool Permission Flow**
- Tools declare a `ToolPermissionBehavior`: `ALLOW`, `DENY`, or `ASK`.
- When `ASK`, the orchestrator pauses, emits a `permission_required` event over SSE, and waits for the frontend to return a signed approval before resuming.

## Consequences

- **Easier**: structured plan state is inspectable in the database; approvals are stateless and portable across sessions.
- **Harder**: every protected action endpoint must validate HMAC; clock skew between desktop and backend can cause spurious expiry.
- **Risk**: if the action-approval secret is leaked, an attacker can forge approvals. Mitigation: local-only auth, filesystem permissions, and short TTL.
- **Out of scope**: OAuth or RBAC; multi-user approval chains.

## Alternatives Considered

- **Server-side session storage for approvals**: rejected because it couples the desktop approval flow to server state; HMAC allows stateless verification.
- **Browser-based approval modal without crypto**: rejected because malicious scripts could auto-approve; HMAC requires the desktop secret.

## Validation

- `@backend/tests/test_action_approvals.py` verifies signature creation, validation, and TTL expiry.
- Plan mode transitions are covered in chat-completion integration tests.
