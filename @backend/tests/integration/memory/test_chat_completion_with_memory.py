"""Testes de integração do ChatCompletionUseCase com sistema de memória.

Valida que recall e extração funcionam corretamente durante o fluxo de chat.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.jobs.memory_job_scheduler import MemoryJobScheduler
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.application.use_cases.memory.recall_memory import RecallMemoryUseCase
from personagent.domain.memory.models.memory_file import MemoryFile
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.models.operational import StructuredMemoryItem, StructuredMemoryType
from personagent.domain.memory.services.memory_recall_selector import MemoryRecallSelector
from personagent.domain.models.conversation import Conversation, Role
from personagent.infrastructure.persistence.memory.filesystem_memory_repository import (
    FileSystemMemoryRepository,
)


class MockConversationRepo:
    """Mock de ConversationRepository."""

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}

    async def get_by_id(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    async def create(self, conversation: Conversation) -> None:
        self._conversations[str(conversation.id)] = conversation

    async def update(self, conversation: Conversation) -> None:
        self._conversations[str(conversation.id)] = conversation


class MockLLMBackend:
    """Mock LLM que responde com conteúdo fixo."""

    def __init__(self, response: str = "Hello!") -> None:
        self._response = response
        self.calls: list[dict] = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        from personagent.domain.models.inference_result import InferenceResult
        return InferenceResult(content=self._response)

    async def chat_completion_stream(self, **kwargs):
        from personagent.domain.models.inference_result import StreamChunk
        yield StreamChunk(content=self._response, finish_reason="stop")

    async def health_check(self):
        return {"status": "ok"}

    async def get_model_info(self):
        return {}


class FakeOperationalPackage:
    def __init__(self) -> None:
        self.formatted = "# Relevant Execution Memory\n\n## Active Decisions\n- Keep memory visible."
        self.items = [
            StructuredMemoryItem(
                type=StructuredMemoryType.DECISION,
                summary="Keep memory visible.",
                evidence=["The prior turn used persisted memory evidence."],
                paths=["@backend/src/personagent/application/use_cases/chat_completion.py"],
                source_ids=["mem-1"],
                score=0.87,
            )
        ]
        self.filters_applied = {"workspace_root": "/tmp/default"}
        self.budget_used = 42
        self.budget_tokens = 1200
        self.omitted_count = 1
        self.latency_ms = 17
        self.recall_scope = "workspace"
        self.query_intent = "file_or_path"
        self.candidate_count = 3
        self.included_reasons = [{"source_ids": ["mem-1"], "reasons": ["exact_anchor_match"]}]

    def metadata(self) -> dict:
        return {
            "memory_budget_tokens": self.budget_tokens,
            "memory_budget_used": self.budget_used,
            "memory_items_injected": len(self.items),
            "memory_items_omitted": self.omitted_count,
            "memory_latency_ms": self.latency_ms,
            "memory_filters_applied": self.filters_applied,
            "memory_recall_scope": self.recall_scope,
            "memory_query_intent": self.query_intent,
            "memory_candidate_count": self.candidate_count,
            "memory_included_reasons": self.included_reasons,
        }


class FakeOperationalMemory:
    def __init__(self) -> None:
        self.recall_calls: list[dict] = []

    async def recall_package_for_prompt(self, *args, **kwargs):
        self.recall_calls.append(kwargs)
        return FakeOperationalPackage()

    async def capture_user_message(self, *args, **kwargs):
        return None

    async def capture_assistant_message(self, *args, **kwargs):
        return None


class TestChatCompletionWithMemory:
    """Testes do ChatCompletionUseCase integrado com memória."""

    @pytest.fixture
    def tmp_root(self, tmp_path: Path):
        return tmp_path

    @pytest.fixture
    def repo(self, tmp_root: Path):
        return FileSystemMemoryRepository(root_dir=tmp_root)

    @pytest.fixture
    def mock_llm(self):
        return MockLLMBackend()

    @pytest.fixture
    def conv_repo(self):
        return MockConversationRepo()

    def _create_use_case(
        self,
        conv_repo,
        mock_llm,
        repo,
        enable_recall: bool = True,
        enable_extraction: bool = True,
    ) -> ChatCompletionUseCase:
        """Factory para criar ChatCompletionUseCase com memória."""
        recall_uc = None
        if enable_recall:
            selector = MemoryRecallSelector(
                llm_backend=mock_llm,
                memory_repository=repo,
                max_recall=5,
            )
            recall_uc = RecallMemoryUseCase(selector)

        scheduler = None
        if enable_extraction:
            scheduler = MemoryJobScheduler()
            scheduler.initialize()

        return ChatCompletionUseCase(
            conversation_repo=conv_repo,
            llm_backend=mock_llm,
            recall_memory_use_case=recall_uc,
            memory_job_scheduler=scheduler,
            memory_repository=repo,
        )

    @pytest.mark.asyncio
    async def test_recall_injects_relevant_memories(self, repo, mock_llm, conv_repo, tmp_root):
        """Testa que memórias relevantes são injetadas no prompt."""
        # Cria memória no repo
        mem_dir = tmp_root / "projects" / "default" / "memory"
        mem_dir.mkdir(parents=True)
        mem = MemoryFile(
            path=mem_dir / "python_pref.md",
            memory_type=MemoryType.USER,
            name="python_pref",
            description="I prefer Python",
            content="I always choose Python for backend projects.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        await repo.write(mem)

        # Mock LLM do selector seleciona a memória
        mock_llm._response = '{"selected_memories": ["python_pref.md"]}'

        use_case = self._create_use_case(conv_repo, mock_llm, repo)
        conv = Conversation()
        await conv_repo.create(conv)

        request = ChatRequestDTO(
            conversation_id=str(conv.id),
            message="What language should I use?",
        )

        relevant = await use_case._recall_relevant_memories(
            request,
            SimpleNamespace(
                system_context=SimpleNamespace(workspace_root="/tmp/default"),
            ),
            conv,
        )
        assert len(relevant.prompt_memories) == 1
        assert "Python" in relevant.prompt_memories[0]
        assert relevant.trace is not None
        assert relevant.trace["summary"]["classic_count"] == 1
        assert relevant.trace["classic"][0]["name"] == "python_pref.md"

        # Verifica que already_surfaced foi atualizado
        assert "_surfaced_memory_paths" in conv.metadata
        assert len(conv.metadata["_surfaced_memory_paths"]) == 1

    @pytest.mark.asyncio
    async def test_recall_deduplicates_already_surfaced(self, repo, mock_llm, conv_repo, tmp_root):
        """Testa que memórias já surfacadas não são retornadas novamente."""
        mem_dir = tmp_root / "projects" / "default" / "memory"
        mem_dir.mkdir(parents=True)
        mem = MemoryFile(
            path=mem_dir / "pref.md",
            memory_type=MemoryType.USER,
            name="pref",
            description="My preference",
            content="I like Python.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        await repo.write(mem)

        mock_llm._response = '{"selected_memories": ["pref.md"]}'

        use_case = self._create_use_case(conv_repo, mock_llm, repo)
        conv = Conversation()
        await conv_repo.create(conv)

        request = ChatRequestDTO(
            conversation_id=str(conv.id),
            message="What do I like?",
        )

        ctx = SimpleNamespace(system_context=SimpleNamespace(workspace_root="/tmp/default"))

        # Primeiro recall
        relevant1 = await use_case._recall_relevant_memories(request, ctx, conv)
        assert len(relevant1.prompt_memories) == 1

        # Segundo recall com mesma query — deve retornar vazio
        relevant2 = await use_case._recall_relevant_memories(request, ctx, conv)
        assert len(relevant2.prompt_memories) == 0

    @pytest.mark.asyncio
    async def test_trigger_extraction_debounce(self, repo, mock_llm, conv_repo, tmp_root):
        """Testa debounce de extração (não dispara mais de uma vez por minuto)."""
        use_case = self._create_use_case(conv_repo, mock_llm, repo, enable_recall=False)

        conv = Conversation()
        await conv_repo.create(conv)

        request = ChatRequestDTO(
            conversation_id=str(conv.id),
            message="Hello",
        )

        # Primeiro trigger
        await use_case._trigger_memory_extraction(conv, request)
        assert "_last_memory_extraction" in conv.metadata

        # Segundo trigger imediato — deve ser skipado pelo debounce
        await use_case._trigger_memory_extraction(conv, request)
        # O timestamp não deve mudar
        first_time = conv.metadata["_last_memory_extraction"]

        # Simula tempo passado removendo o timestamp
        del conv.metadata["_last_memory_extraction"]
        await use_case._trigger_memory_extraction(conv, request)
        second_time = conv.metadata["_last_memory_extraction"]
        assert second_time != first_time

    @pytest.mark.asyncio
    async def test_recall_disabled_returns_empty(self, repo, mock_llm, conv_repo):
        """Testa que recall retorna vazio quando desabilitado."""
        use_case = self._create_use_case(
            conv_repo, mock_llm, repo, enable_recall=False
        )
        conv = Conversation()
        await conv_repo.create(conv)

        request = ChatRequestDTO(message="Test")
        ctx = SimpleNamespace(system_context=SimpleNamespace(workspace_root="/tmp"))

        relevant = await use_case._recall_relevant_memories(request, ctx, conv)
        assert relevant.prompt_memories == []
        assert relevant.trace is None

    @pytest.mark.asyncio
    async def test_execute_persists_classic_memory_trace(self, repo, mock_llm, conv_repo, tmp_root):
        mem_dir = tmp_root / "projects" / "default" / "memory"
        mem_dir.mkdir(parents=True)
        await repo.write(
            MemoryFile(
                path=mem_dir / "python_pref.md",
                memory_type=MemoryType.USER,
                name="python_pref",
                description="I prefer Python",
                content="I always choose Python for backend projects.",
                raw_content="",
                scope=MemoryScope.PRIVATE,
            )
        )
        mock_llm._response = '{"selected_memories": ["python_pref.md"]}'
        use_case = self._create_use_case(
            conv_repo,
            mock_llm,
            repo,
            enable_extraction=False,
        )
        conv = Conversation()
        await conv_repo.create(conv)

        await use_case.execute(
            ChatRequestDTO(
                conversation_id=str(conv.id),
                message="What language should I use?",
                tools_enabled=False,
                tool_context={
                    "workspace_root": "/tmp/default",
                    "cwd": "/tmp/default",
                    "allowed_roots": ["/tmp/default"],
                },
            )
        )

        assistant = [message for message in conv.messages if message.role == Role.ASSISTANT][-1]
        trace = assistant.metadata["memory_trace"]
        assert trace["summary"]["classic_count"] == 1
        assert trace["classic"][0]["path"].endswith("python_pref.md")

    @pytest.mark.asyncio
    async def test_execute_persists_operational_memory_trace(self, repo, mock_llm, conv_repo):
        operational_memory = FakeOperationalMemory()
        use_case = ChatCompletionUseCase(
            conversation_repo=conv_repo,
            llm_backend=mock_llm,
            memory_repository=repo,
            operational_memory_service=operational_memory,
        )
        conv = Conversation()
        await conv_repo.create(conv)

        await use_case.execute(
            ChatRequestDTO(
                conversation_id=str(conv.id),
                message="Recall the memory work for chat_completion.py",
                tools_enabled=False,
                tool_context={
                    "workspace_root": "/tmp/default",
                    "cwd": "/tmp/default",
                    "allowed_roots": ["/tmp/default"],
                },
            )
        )

        assistant = [message for message in conv.messages if message.role == Role.ASSISTANT][-1]
        trace = assistant.metadata["memory_trace"]
        assert trace["summary"] == {
            "total_used": 1,
            "classic_count": 0,
            "rag_count": 1,
            "omitted_count": 1,
            "budget_used": 42,
            "budget_tokens": 1200,
            "latency_ms": 17,
            "recall_scope": "workspace",
            "query_intent": "file_or_path",
            "candidate_count": 3,
        }
        assert trace["operational"][0]["source_ids"] == ["mem-1"]
        assert trace["filters_applied"] == {"workspace_root": "/tmp/default"}
        assert trace["included_reasons"] == [
            {"source_ids": ["mem-1"], "reasons": ["exact_anchor_match"]}
        ]
        assert operational_memory.recall_calls[0]["conversation_id"] is None
        assert operational_memory.recall_calls[0]["current_conversation_id"] == str(conv.id)

    @pytest.mark.asyncio
    async def test_sanitize_project_slug(self, repo, mock_llm, conv_repo):
        """Testa sanitização de project_slug."""
        use_case = self._create_use_case(conv_repo, mock_llm, repo)

        # Slug com espaços e caracteres especiais
        slug = use_case._sanitize_project_slug("/path/to/My Project v2.0!")
        assert slug == "my_project_v2_0_"
        assert " " not in slug
        assert "!" not in slug

        # Root vazio
        assert use_case._sanitize_project_slug("") == "default"
        assert use_case._sanitize_project_slug(None) == "default"
