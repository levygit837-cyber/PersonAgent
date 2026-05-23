"""Submodules supporting :mod:`personagent.application.use_cases.chat_completion`.

The use case lived in a single 2.7k-line file before Fase 1.2. As we
peel coherent helper surfaces out of it, they land here -- not under a
``_helpers`` private package -- because they are perfectly reasonable
import targets for tests and for future use cases that need the same
primitives (e.g. preview endpoints).

Nothing under this package is re-exported from
``personagent.application.use_cases`` on purpose; consumers that don't
need internals should keep importing
:class:`~personagent.application.use_cases.ChatCompletionUseCase`.
"""

from __future__ import annotations

from personagent.application.use_cases.chat import helpers, state
from personagent.application.use_cases.chat.state import (
    AssistantStreamState,
    MemoryRecallResult,
    PromptPackage,
    PromptPreparation,
)

__all__ = [
    "AssistantStreamState",
    "MemoryRecallResult",
    "PromptPackage",
    "PromptPreparation",
    "helpers",
    "state",
]
