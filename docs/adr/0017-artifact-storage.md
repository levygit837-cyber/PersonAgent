# ADR 0017: StoredArtifact for Large Payloads Outside Chat JSON

Date: 2025-06-10
Status: Accepted

## Context

Tool results (file reads, web fetches, shell output) can exceed 60k characters. Embedding them directly in the chat JSON bloats payloads, slows SSE parsing, and can hit provider token limits.

## Decision

Store large tool results as filesystem artifacts referenced by hash, with automatic TTL cleanup.

**StoredArtifact**
- `store_bytes_artifact()` writes to `<artifact_root>/<hash_prefix>/<hash>.<ext>`.
- Hash is SHA-256 of content; deduplication is implicit.
- MIME-type filtering: text/plain, text/markdown, application/json accepted; binary files are base64-wrapped.
- TTL: default 7 days (`PERSONAGENT_ARTIFACT_TTL_SECONDS`).

**Tool result flow**
- `ToolOrchestrator._cap_result()` truncates results to `max_result_size_chars`.
- If truncation occurs, the full content is persisted and a `storage_ref` is added to metadata.
- The LLM receives the truncated preview + a `[Output truncated.]` marker; the full content is available via artifact API if needed.

**Artifact root**
- Configurable (`PERSONAGENT_ARTIFACT_ROOT`), defaults to `~/.cache/personagent/artifacts`.

## Consequences

- **Easier**: chat payloads stay small; large outputs are downloadable; deduplication saves disk.
- **Harder**: artifact cleanup must be scheduled; missing artifacts break downstream tools that expect full content.
- **Risk**: no encryption at rest; sensitive file contents are written to disk in plaintext.
- **Out of scope**: cloud object storage (S3, GCS); client-side encryption.

## Alternatives Considered

- **Inline base64 in SSE**: rejected because it doubles JSON size and breaks readability.
- **Separate vector store for large text**: rejected for operational simplicity.

## Validation

- `@backend/tests/unit/` validates hash-based deduplication, TTL expiry, and MIME-type filtering.
