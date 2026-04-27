from __future__ import annotations

from personagent.domain.memory.models.operational import RecallFinding
from personagent.domain.memory.services.operational_memory import (
    OperationalMemoryChunker,
    OperationalMemoryFormatter,
    OperationalMemoryRedactor,
)


def test_redactor_removes_known_secret_shapes() -> None:
    redactor = OperationalMemoryRedactor()

    text = "token=nvapi-secretvalue123456789 Authorization: Bearer sk-secretvalue123456789"
    redacted = redactor.redact_text(text)

    assert "nvapi-secretvalue" not in redacted
    assert "sk-secretvalue" not in redacted
    assert "[REDACTED]" in redacted


def test_redactor_masks_secret_keys_in_structured_data() -> None:
    redactor = OperationalMemoryRedactor()

    data = redactor.redact_data({"api_key": "abc123", "nested": {"password": "secret"}})

    assert data["api_key"] == "[REDACTED]"
    assert data["nested"]["password"] == "[REDACTED]"


def test_chunker_preserves_hash_and_overlap_contract() -> None:
    chunker = OperationalMemoryChunker(max_chars=40, overlap_chars=5)

    chunks = chunker.chunk_text(
        project_slug="personagent",
        source_type="diff_applied",
        source_id="event-1",
        content="line one\nline two mentions orchestrator\nline three mentions registry",
        file_path="src/agents/orchestrator.ts",
    )

    assert len(chunks) >= 2
    assert all(chunk.content_hash for chunk in chunks)
    assert chunks[0].file_path == "src/agents/orchestrator.ts"
    assert chunks[0].source_type == "diff_applied"


def test_formatter_outputs_relevant_execution_memory_section() -> None:
    formatted = OperationalMemoryFormatter.format_findings(
        [
            RecallFinding(
                finding="Na sessão anterior, o agente adicionou timeout no orchestrator.",
                source_ids=["chunk-1"],
                evidence=["diff em src/agents/orchestrator.ts"],
                paths=["src/agents/orchestrator.ts"],
                decisions=["planner delega ao executor (active)"],
                cautions=["registry já possui dispatch"],
            )
        ]
    )

    assert "# Relevant Execution Memory" in formatted
    assert "Finding 1:" in formatted
    assert "src/agents/orchestrator.ts" in formatted
    assert "Source ids: chunk-1" in formatted

