# ADR 0020: Shell Tool Path Safety with Command Allowlist and Workspace Grants

Date: 2025-06-10
Status: Accepted

## Context

The `shell` tool is the highest-risk surface: it can execute arbitrary commands, modify files, and exfiltrate data. We need a defense-in-depth strategy that limits what the shell tool can do even if the permission system is bypassed.

## Decision

**Command allowlist**
- The shell tool only allows commands from an explicit allowlist of safe, read-only operations.
- Destructive commands (`rm`, `mv`, `chmod`, `chown`, `sudo`, `curl | sh`, etc.) are blocked at the input-validation layer.

**Workspace grants**
- Before any shell execution, the workspace root must be registered via `workspace:grant` in the Electron main process.
- `resolveGrantedWorkspace()` verifies the path against a map of approved roots; unknown roots are rejected.

**Path safety**
- `path_safety.py` ensures all file arguments stay within the allowed workspace roots (no `../` escape).
- Symlinks are resolved before validation.

**Read-only by default**
- The shell tool is classified as `is_destructive=True`; it can only run when permissions are explicitly granted or in auto-permission mode with allowlist confirmation.

## Consequences

- **Easier**: explicit deny-list is grep-able and auditable; workspace grants map 1:1 to user intent.
- **Harder**: every new safe command must be added to the allowlist; creative shell syntax can bypass simple string checks.
- **Risk**: a user can grant a workspace that contains a malicious script and then ask the agent to run it; the allowlist does not inspect script content.
- **Out of scope**: sandboxed execution (containers, seccomp, AppArmor); network egress filtering from shell.

## Alternatives Considered

- **Full shell freedom with audit log only**: rejected because it offers no preventive protection.
- **Containerized shell (Docker)**: rejected for latency and cross-platform complexity.

## Validation

- `@backend/tests/test_shell_safety.py` validates allowlist enforcement, path escape attempts, and workspace grant rejection.
