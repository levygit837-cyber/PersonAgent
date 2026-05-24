"""Model listing, command listing, and prompt preview endpoints.

Endpoint functions access ``get_container``, ``resolve_model``,
``resolve_context_workspace_root``, and ``_create_chat_use_case``
through the ``_chat`` module reference so that monkeypatched test
values are resolved at call time rather than captured at import time.
This preserves the original late-binding semantics that the test
suite relies on.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

# Late-binding module reference.  See module docstring for rationale.
# Imported inside the function body to avoid circular import at load time.
# After the chat package is fully initialised, _chat points to the live
# module and attribute lookups see any monkeypatched values.
import personagent.interfaces.api.routes.chat as _chat
from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.domain.exceptions import (
    ConversationNotFoundError,
    LLMBackendConnectionError,
    LLMBackendError,
)
from personagent.domain.prompts.commands import CommandService
from personagent.domain.prompts.skills import discover_enabled_skills
from personagent.interfaces.api.routes.chat.helpers import (
    DB_SESSION_DEPENDENCY,
    ChatCommandInfo,
    ChatRequest,
    PromptPreviewResponse,
    resolve_prompt_mode,
    resolve_provider,
    resolve_reasoning_budget,
    resolve_tool_context,
)
from personagent.interfaces.api.state_events import publish_state_change


def register_model_listing_routes(router: APIRouter) -> None:
    """Register model listing, auth, commands, and prompt preview endpoints."""

    @router.get("/models")
    async def list_models(
        provider: str = Query(
            default="llama",
            description="Provider: llama, nvidia, deepseek, zenmux, vertex, kimi, or codex",
        ),
        capability: str | None = Query(default=None, description="Capability filter"),
        refresh: bool = Query(default=False, description="Ignore the catalog cache"),
    ) -> dict:
        """List the models available from the LLM backend."""
        container = _chat.get_container()
        resolved_provider = resolve_provider(provider)
        llm_backend = container.get_llm_backend(resolved_provider)
        if resolved_provider in {"nvidia", "deepseek", "zenmux", "vertex", "kimi", "codex"}:
            list_provider_models = getattr(llm_backend, "list_models", None)
            if list_provider_models is None:
                raise HTTPException(status_code=500, detail=f"{resolved_provider} provider has no catalog")
            return await list_provider_models(capability=capability, refresh=refresh)

        models_info = await llm_backend.get_model_info()
        return models_info if models_info else {"data": [], "object": "list"}

    @router.get("/auth/codex/status")
    async def codex_auth_status() -> dict[str, Any]:
        """Return Codex CLI authentication state without exposing tokens."""
        container = _chat.get_container()
        llm_backend = container.get_llm_backend("codex")
        auth_status = getattr(llm_backend, "auth_status", None)
        if auth_status is None:
            raise HTTPException(status_code=500, detail="codex provider sem estado de auth")
        return auth_status()

    @router.post("/auth/codex/logout")
    async def codex_auth_logout() -> dict[str, Any]:
        """Executa `codex logout` para desconectar a conta do ChatGPT Subscription."""
        container = _chat.get_container()
        llm_backend = container.get_llm_backend("codex")
        logout = getattr(llm_backend, "logout", None)
        if logout is None:
            raise HTTPException(status_code=500, detail="codex provider sem logout")
        try:
            result = await logout()
            publish_state_change("codex-auth", {"provider": "codex"})
            publish_state_change("models", {"provider": "codex"})
            return result
        except LLMBackendConnectionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LLMBackendError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/commands", response_model=list[ChatCommandInfo])
    async def list_chat_commands(
        workspace_root: str | None = Query(default=None),
    ) -> list[ChatCommandInfo]:
        """List prompt slash commands and user-invocable skills for desktop autocomplete."""

        root = workspace_root or _chat.resolve_context_workspace_root(
            ChatRequest(message="placeholder")
        )
        container = _chat.get_container()
        skill_roots = tuple(str(path) for path in container.get_tool_runtime_config().skill_roots)
        command_service = CommandService(container.create_command_registry())
        commands = [
            ChatCommandInfo(
                name=command.name,
                slash_name=command.slash_name,
                description=command.description,
                argument_hint=command.argument_hint,
                source="command",
                path=str(command.path),
                user_invocable=True,
                should_query=not command.disable_model_invocation,
            )
            for command in command_service.list_prompt_commands(root)
        ]
        builtins = [
            ChatCommandInfo(
                name=command.name,
                slash_name=command.slash_name,
                description=command.description,
                argument_hint=command.argument_hint,
                source="builtin",
                path=command.path,
                user_invocable=True,
                should_query=command.should_query,
                ui_action=command.ui_action,
            )
            for command in command_service.list_builtin_commands()
        ]
        skills = [
            ChatCommandInfo(
                name=skill.name,
                slash_name=skill.slash_name,
                description=skill.description,
                argument_hint=skill.argument_hint,
                source="skill",
                path=str(skill.path),
                user_invocable=skill.user_invocable,
                should_query=True,
            )
            for skill in discover_enabled_skills(
                workspace_root=root,
                cwd=root,
                extra_roots=skill_roots,
            )
            if skill.user_invocable
        ]
        by_name: dict[str, ChatCommandInfo] = {}
        for item in [*commands, *skills, *builtins]:
            by_name.setdefault(item.slash_name, item)
        return sorted(by_name.values(), key=lambda item: item.slash_name)

    @router.post("/prompt/preview", response_model=PromptPreviewResponse)
    async def prompt_preview(
        request: ChatRequest,
        session: AsyncSession = DB_SESSION_DEPENDENCY,
    ) -> PromptPreviewResponse:
        """Build and return the prompt package without running a completion."""

        container = _chat.get_container()
        provider = resolve_provider(request.provider)
        model = _chat.resolve_model(provider, request.model)
        prompt_mode = resolve_prompt_mode(request.prompt_mode)
        llm_backend = container.get_llm_backend(provider)
        conv_repo = await container.get_conversation_repo(session)
        context_workspace_root = _chat.resolve_context_workspace_root(request)
        use_case = _chat._create_chat_use_case(
            container=container,
            conv_repo=conv_repo,
            llm_backend=llm_backend,
            provider=provider,
            context_workspace_root=context_workspace_root,
        )

        try:
            conversation_id = UUID(request.conversation_id) if request.conversation_id else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid conversation_id.") from exc
        message_text = request.message
        plan_mode_requested = request.plan_mode_requested
        if message_text.strip() == "/plan":
            plan_mode_requested = True
            message_text = "Enter plan mode"
        elif message_text.strip().startswith("/plan "):
            plan_mode_requested = True
            message_text = message_text.strip()[6:]

        dto = ChatRequestDTO(
            conversation_id=conversation_id,
            message=message_text,
            system_prompt=request.system_prompt,
            stream=False,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            provider=provider,
            model=model,
            prompt_mode=prompt_mode,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=resolve_reasoning_budget(request),
            tools_enabled=request.tools_enabled and container.settings.tools_enabled,
            allowed_tools=request.allowed_tools,
            tool_context=resolve_tool_context(request),
            max_tool_iterations=request.max_tool_iterations,
            context_attachments=request.context_attachments,
            plan_mode_requested=plan_mode_requested,
        )

        try:
            return PromptPreviewResponse(**await use_case.preview_prompt(dto))
        except ConversationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
