# ADR 0007: Modular Prompt Engineering with Sections, Modes, and Context Analysis

Date: 2025-06-10
Status: Accepted

## Context

The system prompt must adapt to user intent (writing, exploring, research), agent execution state (intake, planning, tool execution), available tools, skills, and context attachments. A single static system prompt would be too large and irrelevant for most turns.

## Decision

Build a `PromptBuilder` that assembles the system prompt from modular, cacheable sections, guided by a `PromptContextAnalyzer` and an `AgentStateResolver`.

**Sections**
- **Base** (`domain/prompts/sections/base`): identity, rules, compact mode.
- **Tools** (`domain/prompts/sections/tools`): tool descriptions, usage prompts, search hints.
- **Execution** (`domain/prompts/sections/execution`): reasoning policy, output format, plan mode instructions.
- **Agent State** (`domain/prompts/sections/states`): state-specific instructions derived from the resolved agent state profile.

**Modes**
- `auto` (default): `PromptContextAnalyzer` classifies the user message with a short, tool-free LLM call into `writing`, `exploring`, or `research`.
- Explicit override: `prompt_mode=writing/exploring/research` skips classification.
- Fallback: regex-based surface hints when the LLM classifier is unavailable or in cooldown.

**Agent states**
- `AgentStateResolver` maps the current conversation context to execution states (`intake`, `context_discovery`, `planning`, `implementation`, `tool_execution`, `debug_recovery`, `runtime_validation`, `context_compaction`, `memory_recall`, `user_checkpoint`, `finalization`, `plan_mode`).
- Each state activates specific prompt sections.

**Context attachments**
- `resolve_context_attachments` injects user-provided files, git context, persona.md, and rules into the prompt package.

## Consequences

- **Easier**: targeted prompts per turn; cacheable sections reduce recomputation; skills inject only when enabled.
- **Harder**: two LLM round-trips (classifier + main) on every auto-mode turn; classifier timeout/cooldown logic adds complexity.
- **Risk**: misclassification can send the wrong persona tone; cooldown must not hide persistent intent shifts.
- **Out of scope**: automatic prompt compression or token-based section eviction.

## Alternatives Considered

- **Single giant system prompt**: rejected because it wastes tokens and confuses the model with irrelevant tool instructions.
- **Client-side prompt assembly**: rejected to keep the backend as the source of truth for provider-specific payload shaping.

## Validation

- `PromptContextAnalyzer` has configurable timeouts and fallback profiles; unit tests verify classification caching and cooldown behavior.
