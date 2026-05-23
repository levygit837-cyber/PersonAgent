# ADR 0019: Provider Data Policy with Regex Secret Blocking

Date: 2025-06-10
Status: Accepted

## Context

When the user selects a hosted provider (DeepSeek, Vertex, Kimi, etc.), the backend sends the conversation history to that provider. Local files, environment variables, and shell output may contain secrets (API keys, passwords, tokens) that must not leak.

## Decision

Implement a **Provider Data Policy** that inspects outgoing payloads and blocks known secret patterns before they leave the local machine.

**Blocking rules**
- Regex patterns for common secrets: `api[_-]?key`, `password`, `secret`, `token`, `bearer`, `aws_access_key_id`, `private_key`, etc.
- File paths that look like credential files: `.env`, `.aws/credentials`, `.ssh/id_rsa`.
- Shell tool output is scanned before inclusion in the chat context.

**Policy behavior**
- When a match is found, the secret is redacted to `[REDACTED]` and a metadata warning is logged.
- The policy runs in the chat-completion use case before the final message list is sent to the LLM adapter.
- Local provider (`llama`) is exempt because data never leaves the machine.

## Consequences

- **Easier**: one centralized scan before all provider calls; regex is fast and explainable.
- **Harder**: regex can miss novel secret formats or generate false positives in code that legitimately discusses "api_key" as a variable name.
- **Risk**: a determined user can bypass the regex with creative encoding; the policy is a safety net, not a guarantee.
- **Out of scope**: deep semantic analysis of code to detect secret usage; encryption of provider traffic at rest.

## Alternatives Considered

- **Client-side scanning (Electron)**: rejected because the desktop should not own provider-specific policy logic.
- **No scanning**: rejected because accidental secret leakage is a real and documented risk.

## Validation

- Unit tests inject synthetic secrets into tool results and verify redaction.
- Integration tests assert that redacted payloads contain no original secret substrings.
