from __future__ import annotations

import pytest

from personagent.infrastructure.llm.shared.process_manager import (
    EmbeddingServerProcessManager,
    LlamaServerProcessManager,
)


def test_llama_process_manager_binds_loopback_by_default() -> None:
    manager = LlamaServerProcessManager()
    command = manager._build_llama_command("/tmp/llama-server", "/tmp/model.gguf")

    assert command[command.index("--host") + 1] == "127.0.0.1"


def test_embedding_process_manager_ctx_fallback_attempts() -> None:
    manager = EmbeddingServerProcessManager()
    manager._target_ctx_size = 32_768

    assert manager._ctx_size_attempts() == [32_768, 24_576, 16_384, 8_192]


def test_embedding_process_manager_binds_loopback_by_default() -> None:
    manager = EmbeddingServerProcessManager()
    command = manager._build_embedding_command("/tmp/llama-server", "/tmp/model.gguf", 32_768)

    assert command[command.index("--host") + 1] == "127.0.0.1"


def test_embedding_process_manager_runtime_status_exposes_context() -> None:
    manager = EmbeddingServerProcessManager()
    manager._target_ctx_size = 32_768
    manager._actual_ctx_size = 16_384
    manager._fallback_used = True
    manager._startup_error = "startup timeout"

    status = manager.runtime_status()

    assert status["target_ctx_size"] == 32_768
    assert status["actual_ctx_size"] == 16_384
    assert status["fallback_used"] is True
    assert status["startup_error"] == "startup timeout"


@pytest.mark.asyncio
async def test_embedding_process_manager_start_uses_ctx_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _FallbackManager()

    monkeypatch.setattr(
        "personagent.infrastructure.llm.shared.process_manager.subprocess.Popen",
        lambda *_args, **_kwargs: _FakeProcess(),
    )

    started = await manager.start()

    assert started is True
    assert manager.attempted_ctx_sizes == [32_768, 24_576]
    assert manager.runtime_status()["actual_ctx_size"] == 24_576
    assert manager.runtime_status()["fallback_used"] is True
    manager.stop()


class _FallbackManager(EmbeddingServerProcessManager):
    def __init__(self) -> None:
        super().__init__()
        self._target_ctx_size = 32_768
        self.attempted_ctx_sizes: list[int] = []

    def find_binary(self) -> str | None:
        return "/tmp/llama-server"

    def find_model(self) -> str | None:
        return "/tmp/model.gguf"

    async def _external_server_ready(self) -> bool:
        return False

    async def _wait_for_startup(self, timeout: float = 90.0) -> bool:
        return len(self.attempted_ctx_sizes) == 2

    async def _log_output(self) -> None:
        return None

    def _build_embedding_command(self, binary: str, model: str, ctx_size: int) -> list[str]:
        self.attempted_ctx_sizes.append(ctx_size)
        return [binary, "-m", model, "--ctx-size", str(ctx_size)]


class _FakeProcess:
    pid = 999_999
    stdout = None

    def __init__(self) -> None:
        self._running = True

    def poll(self) -> int | None:
        return None if self._running else 0

    def terminate(self) -> None:
        self._running = False

    def kill(self) -> None:
        self._running = False

    def wait(self, timeout: float | None = None) -> int:
        self._running = False
        return 0
