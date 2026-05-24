# Playbook: Decompose `chat_completion.py`

**Target file:** `@backend/src/personagent/application/use_cases/chat_completion.py`

**Target package:** `@backend/src/personagent/application/use_cases/chat/`
(already exists; new slices go here)

**Test directory:** `@backend/tests/unit/`

This playbook tracks the in-progress decomposition of the chat-turn
orchestrator. Before working any slice, read `_protocol.md` in this
directory.

## Status

| Slice                  | PR  | Lines removed | File after |
| ---------------------- | --- | ------------- | ---------- |
| Baseline               | —   | —             | 2,742      |
| Helpers + state        | #7  | ~360          | 2,388      |
| Conversation compactor | #8  | ~145          | 2,243      |
| Operational memory     | #9  | ~145          | 2,125      |
| Memory recall          | #10 | ~118          | 2,007      |
| Prompt surfaces        | #11 | ~187          | 1,938      |
| Prompt package         | #13 | ~290          | 1,648      |
| Tool result handler    | #14 | ~252          | 1,396      |
| Message preparation    | #16 | ~88           | 1,308      |
| Tool context builder   | #17 | ~118          | 1,190      |
| After-turn coordinator | #19 | ~38           | 1,152      |
| Media policy handler   | #20 | ~54           | 1,098      |
| Conversation lifecycle | #21 | ~33           | 1,065      |
| **Current**            |     |               | **1,065**  |

Cumulative reduction: **2,742 → 1,065 lines (–61%)**.

## Public contract that must be preserved

The chat use case is consumed by:

- `interfaces/api/chat_routes.py` (sync execute)
- `interfaces/websocket/chat_streaming.py` (streaming)
- `application/team_chat/orchestrator.py` (Team Mode)

Public entry points (do not rename, do not change signature):

- `ChatCompletionUseCase.__init__(...)`
- `async def execute(request: ChatRequestDTO) -> ChatResponseDTO`
- `async def stream(request: ChatRequestDTO) -> AsyncIterator[ChatStreamEvent]`

Constructor kwargs must keep their names. New optional dependencies
go at the end of the kwargs list with `= None` defaults.

## Remaining slices (in priority order)

The order is **low-risk → high-risk**. Always finish the current
slice and land it before starting the next.

### Slice 6 — `PromptPackageBuilder` (✅ landed in #13; ~290 lines)

**What moves out:**

- `_analyze_prompt_profile` (chat_completion.py:1312–1356)
- `_build_prompt_package` (chat_completion.py:1521–1681)
- `_clean_user_context_for_system_prompt` (chat_completion.py:1769–1778; static)

**Collaborators (inject in constructor):**

- `prompt_builder: PromptBuilder` (required)
- `prompt_context_analyzer: PromptContextAnalyzer | None`
- `agent_state_resolver: AgentStateResolver` (required)
- `command_registry: CommandRegistry` (required — for
  `list_commands(workspace_root)`)
- `session_memory_service: SessionMemoryService | None`
- `tool_runtime_config: ToolRuntimeConfig | None` (for skill roots)

**Methods (public):**

- `async def build(request, conversation, context_result, *, tools, preparation, relevant_memories, memory_trace) -> PromptPackage`

**Auxiliary helpers that must travel with the slice:**

- `_skill_inventory(request, context_result) -> list[SkillDefinition]`
- `_skill_roots() -> tuple[str | Path, ...]` (already a thin helper)
- `_prompt_tool_definitions(request) -> list[ToolDefinition]`
- `_available_tool_names(tools) -> list[str]`
- `_supports_parallel_tool_calls(request, tools) -> bool`
- `_conversation_recent_tool_names(conversation) -> list[str]`
- `_conversation_recent_error_count(conversation) -> int`

These belong with the prompt package because they're *only* called
from `_build_prompt_package`. Verify with `grep "self\._<name>"` —
if no other caller exists, move it. Otherwise leave it on the
orchestrator and inject the helper as a callable.

**Why this is the right next slice:**

- Single, well-defined input (request + conversation + context_result
  + tools + preparation + recall result) and output (`PromptPackage`).
- Already abstracted: `_build_prompt_package` returns a typed
  `PromptPackage`; the orchestrator never reaches inside it.
- All collaborators are already injected — nothing new to wire.
- No streaming / no per-turn lifecycle entanglement.

**Test plan:** Minimum 20 cases in `tests/unit/test_chat_prompt_package.py`:

- Builds the package with all collaborators wired.
- Skips prompt analysis when `prompt_context_analyzer is None` and
  `prompt_mode != "auto"`.
- `llama` / `zenmux` providers in `auto` mode fall back to
  `fallback_prompt_profile`.
- `_skill_inventory` returns empty when `tool_runtime_config is
  None` (via `_skill_roots`).
- `_supports_parallel_tool_calls` returns:
  - `False` when `tools_enabled=False`
  - `True` for codex provider regardless of tool count
  - `False` for 0–1 tools, `True` for 2+ tools
- Session memory is pulled when `session_memory_service` is wired.
- Plan-mode planning tools are filtered when `plan_active` is true
  (covered today by `_resolve_tool_schemas`).
- Custom `request.system_prompt` is appended, not replaced.
- `user_context_message` is merged into the system prompt under
  the runtime-reminders heading.
- The 13 `memory_*` metadata fields are propagated from
  `conversation.metadata["_operational_memory_prompt"]`.

**Risk:** Medium-low. The class has many collaborators but every
collaborator is already injected and tested elsewhere.

### Slice 7 — `ToolResultHandler` (✅ landed in #14; ~252 lines)

**What moves out:**

- `_tool_message_from_result` (926–939)
- `_execute_tools_into_conversation` (940–962)
- `_apply_tool_state_result` (963–986)
- `_is_plan_mode_result`, `_is_plan_approval_result`,
  `_is_user_question_result` (987–998)
- `_plan_state_from_result` (999–1008)
- `_record_pending_tool_approval` (1009–1073)
- `_record_pending_user_question` (1074–1117)
- `_parse_tool_calls` (1118–1123)
- `_unique_tool_call_ids` (1124–1154)
- `_forwarded_finish_reason` (1155–1172)

**Collaborators:**

- `tool_orchestrator_factory: Callable[[], ToolOrchestrator]` (the
  use case currently builds one with `_new_orchestrator`; that
  helper stays on the use case, the new module accepts a factory)
- `conversation_repo: ConversationRepository` (already injected)

**Public API:**

- `parse_calls(raw: list[dict] | None) -> list[ToolCall]`
- `unique_call_ids(...)`
- `async def execute(orchestrator, request, conversation, tool_calls) -> list[ToolResult]`
- `apply_state(result, conversation) -> None`
- `record_pending_approval(...)`
- `record_pending_question(...)`
- `tool_message_from(result) -> Message`
- `forwarded_finish_reason(finish_reason, tool_calls) -> str | None`

**Risk:** Medium. The orchestrator holds tool-result state
(approvals, plan mode, user questions) that affects the next loop
iteration. Tests must cover all six "result kind" branches.

### Slice 8 — `MessagePreparation` (✅ landed in #16; ~88 lines)

**What moves out:**

- `_prepare_messages_for_llm` (1694–1736)
- `_messages_with_prompt` (1737–1768)
- `_messages_with_final_answer_reminder` (1286–1304)

**Collaborators:**

- `provider_message_formatter` (lookup on `self._llm_backend`?
  inspect first)
- Conversation-to-OpenAI-message conversion is shared with the
  team-chat orchestrator — when extracting, consider promoting
  this into `domain/messaging/` instead of `chat/`. Defer the
  decision until you grep for shared callers.

**Risk:** Low (pure transformation) but verify it isn't called by
team-chat.

### Slice 9 — `ToolContextBuilder` (✅ landed in #17; ~118 lines)

**What moves out:**

- `_build_tool_context` (1833–1919)
- `_resolve_workspace_root` (1920–1925)
- `_resolve_allowed_path` (1926–end)

**Collaborators:**

- `tool_runtime_config: ToolRuntimeConfig`
- `request_context_factory: RequestContextFactory`

**Risk:** Low. Mostly pure path-resolution logic.

### Slice 10 — `AfterTurnCoordinator` (✅ landed in #19; ~38 lines)

**What moves out:**

- `_after_turn_services` (1779–1808)
- `_refresh_session_title` (1809–1824)

**Collaborators:**

- `next_step_suggestion_service`
- `session_title_service`
- `session_memory_service`

**Risk:** Low. Side-effect-only methods; tests need to pin the
order of calls.

### Slice 11 — `StreamingTurnExecutor` (LAST; ~500+ lines, HIGH RISK)

**What moves out:**

- `_stream_completion_turn` — outer turn loop (~370 lines)
- `_stream_assistant_pass`
- `_normalize_provider_stream_chunk`
- `_empty_model_response_notice`
- ~~`_get_or_create_conversation`~~ — landed in #21 (`ConversationLifecycleHandler`)
- ~~`_assistant_message_from_result`~~ — landed in #21 (`ConversationLifecycleHandler`)
- ~~`_enforce_provider_data_policy`~~ — landed in #20 (`MediaPolicyHandler`)
- ~~`_store_generated_images`~~ — landed in #20 (`MediaPolicyHandler`)

**Why this is last:**

- Touches every collaborator the use case has.
- Streaming has tight invariants (chunk ordering, finish-reason
  forwarding, partial-message persistence). Extraction risk is
  high — the test surface is large.
- All earlier slices reduce the surface area this one has to
  reproduce.

**Pre-conditions before starting:**

- All slices 6–10 are merged.
- A new integration test covers the full streaming turn end-to-end
  with stubbed `LLMBackend` so the extraction has a safety net.
- A `_StreamingTurnState` dataclass is extracted **first** (no
  behavior change) to give the streaming method a single
  mutable-state object. Then the loop body is extracted in a
  separate PR.

This may need to be split into **3–4 sub-slices**:

1. Extract `_StreamingTurnState` dataclass (move state vars off
   `_stream_completion_turn` into a typed struct).
2. Extract the assistant-pass loop body (`_stream_assistant_pass`
   already exists; move its dependencies in).
3. Extract the outer turn loop (the `while True` with iteration
   guards).
4. Extract image-handling and provider-data-policy as a small
   coordinator.

## Things you may NOT change in this file

- `__init__` signature (add new optional kwargs at the end only).
- Public methods `execute` and `stream`.
- The order of collaborator instantiation in `__init__` — some
  collaborators depend on others (e.g.
  `OperationalMemoryCapture` depends on `_tool_runtime_config`).
- The `MemoryRecallCoordinator`, `OperationalMemoryCapture`,
  `ConversationCompactor`, and `PromptSurfacePreparer`
  instantiations — these are already migrated and other code is
  starting to depend on them.

## Validation gates (re-stated from `_protocol.md`)

```bash
cd @backend
uv run ruff check --fix src/ tests/
uv run ruff check src/ tests/
uv run mypy src/personagent/application/use_cases/chat \
            src/personagent/application/state \
            src/personagent/application/use_cases/context \
            src/personagent/domain/models/tenancy.py \
            src/personagent/domain/models/conversation.py
uv run pytest tests/unit tests/test_tool_loop_limit.py tests/test_alembic_setup.py \
              tests/test_conversations_api.py tests/test_team_chat_orchestrator.py \
              tests/test_action_approvals.py \
              -q --no-header \
              --deselect tests/unit/test_prompt_builder.py::TestPromptBuilder::test_agent_state_overlays_are_compact
```

**Current baseline (post-#13):** 473 passed, 1 deselected.

When you add tests for a new slice, the count goes up by N.
**Never let it go down.**

## Glossary of already-extracted collaborators (for context)

These are already wired in `__init__`; new slices can call them
directly via `self._<name>`:

- `self._compactor: ConversationCompactor` — context compaction
- `self._operational_memory: OperationalMemoryCapture` —
  operational memory capture
- `self._memory_recall: MemoryRecallCoordinator` — both classic
  + operational recall
- `self._prompt_surfaces: PromptSurfacePreparer` — slash command
  / skill / attachment routing
- `self._prompt_package_builder: PromptPackageBuilder` — final
  system-prompt assembly + 25+ metadata fields the use case forwards
  to the assistant message

Helper modules (functions, no class):

- `chat.helpers` — small pure helpers (token estimation, browser
  target extraction, etc.)
- `chat.state` — dataclasses (`AssistantStreamState`,
  `PromptPreparation`, `PromptPackage`, `MemoryRecallResult`)
