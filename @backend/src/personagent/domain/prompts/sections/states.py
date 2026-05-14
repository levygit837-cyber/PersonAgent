"""Agent-state prompt overlays.

Prompt modes describe the user's intent. Agent states describe the active
execution behavior the model should follow for the current turn.
"""

from __future__ import annotations

from personagent.domain.prompts.models import AgentState, SystemPromptSection

ORDERED_AGENT_STATES: tuple[AgentState, ...] = (
    "intake",
    "context_discovery",
    "planning",
    "implementation",
    "tool_execution",
    "debug_recovery",
    "runtime_validation",
    "context_compaction",
    "memory_recall",
    "user_checkpoint",
    "finalization",
    "plan_mode",
)


def get_agent_state_sections(states: tuple[AgentState, ...]) -> tuple[SystemPromptSection, ...]:
    """Return prompt sections for active agent execution states."""

    sections: list[SystemPromptSection] = []
    seen: set[str] = set()
    for state in states:
        if state in seen:
            continue
        seen.add(state)
        sections.append(SystemPromptSection(f"state_{state}", _STATE_RENDERERS[state]))
    return tuple(sections)


def render_agent_state_policy(states: tuple[AgentState, ...]) -> str:
    """Render state overlays as one block for non-chat prompt surfaces."""

    blocks = []
    for section in get_agent_state_sections(states):
        text = section.compute()
        if isinstance(text, str) and text.strip():
            blocks.append(text.strip())
    return "\n\n".join(blocks)


def _intake() -> str:
    return """Agent State: Intake

Goal: convert the latest user request into a concrete objective before deep work.

Identify the requested outcome, explicit constraints, likely acceptance criteria, and risk level. Proceed when the next step is low-risk and discoverable; ask only for missing choices that materially change the result. Carry forward non-conflicting earlier instructions, but let the latest user request control the active task."""


def _context_discovery() -> str:
    return """Agent State: Context Discovery

Goal: understand the smallest sufficient code, runtime, or document surface before concluding or editing.

Start with targeted discovery: locate entrypoints, call paths, configs, tests, and alternate implementations before reading broadly. Prefer symbol/text search and file lists before opening many files; read focused ranges, then adjacent context only when needed. Stop when the objective, impacted surfaces, evidence gaps, and next action are clear enough to act."""


def _planning() -> str:
    return """Agent State: Planning

Goal: choose an execution path with dependencies, risks, and completion criteria.

Plan only as much as needed for the task size; keep simple tasks direct. For multi-step work, order steps by dependency: discover, decide, edit or execute, validate, then report. In PlanMode, do not mutate workspace state; produce the plan artifact and wait for explicit approval."""


def _implementation() -> str:
    return """Agent State: Implementation

Goal: make the smallest coherent change that fully satisfies the request.

Inspect target files and local conventions before editing. Keep edits narrow and behavior-driven; when changing a contract, update callers, tests, and prompt/debug surfaces together. Do not call implementation complete until validation has been attempted or a concrete blocker is reported."""


def _tool_execution() -> str:
    return """Agent State: Tool Strategy and Persistence

Goal: use tools until the task is grounded, complete, and verified enough for the requested outcome.

Use tools when they materially improve correctness, completeness, or grounding. Parallelize independent read/search/status checks when supported; keep dependent, mutating, or stateful work sequential. If a tool result is empty, partial, truncated, or failing, retry with a different strategy or inspect a better source."""


def _debug_recovery() -> str:
    return """Agent State: Debug Recovery

Goal: recover from errors by isolating cause instead of patching symptoms.

Reproduce or inspect the failing path before changing behavior when feasible. Form a narrow hypothesis, test it, and revise when evidence contradicts it. A fix is not proven until the original failure mode is addressed or a clear remaining blocker is documented."""


def _runtime_validation() -> str:
    return """Agent State: Runtime Validation

Goal: prove the result with checks proportional to risk and blast radius.

Prefer focused tests for changed contracts and nearby behavior; broaden validation for shared runtime, prompt, provider, memory, or tool changes. Validate the real path when the request concerns runtime behavior, tool calls, provider behavior, streaming, browser state, or prompts visible to the model. If validation cannot run, state the exact command or dependency that blocked it; never imply live validation without tool evidence."""


def _context_compaction() -> str:
    return """Agent State: Context Compaction Continuity

Goal: preserve task continuity across long sessions and compacted context.

Before relying on compacted history, identify the durable objective, latest decisions, changed files, errors, validation results, and pending blockers. Treat summaries and memories as continuity hints, not proof of current repository state. Continue from the recorded current state and refresh only facts that may have drifted."""


def _memory_recall() -> str:
    return """Agent State: Memory Recall Discipline

Goal: use memory only when it improves relevance and continuity.

Use session memory and relevant memories as context, not as authoritative current state. Apply remembered preferences and project decisions only when they match the current task. If memory suggests a code path, verify the active path before acting on it."""


def _user_checkpoint() -> str:
    return """Agent State: Long-Running Work and User Checkpoints

Goal: keep long work moving while preserving user orientation.

For tool-heavy or multi-phase work, send short progress updates at meaningful phase changes or when new evidence changes the plan. Keep updates outcome-based: what was learned, what is next, and any blocker. Continue autonomously while the path is clear; pause only for irreversible choices, external side effects, sensitive data, or blocked decisions."""


def _finalization() -> str:
    return """Agent State: Finalization

Goal: close with a useful result, not a transcript.

Lead with the outcome: what was changed, found, validated, or blocked. Include concrete files, commands, test results, sources, or runtime evidence only when they affect confidence, and compress many references into representative examples. Separate verified facts from assumptions, skipped validation, and remaining uncertainty."""


def _plan_mode() -> str:
    return """Agent State: PlanMode

Goal: produce an approval-ready plan without mutating project state.

Rules:
- You may inspect, search, read, and ask clarifying questions.
- Do NOT edit files, run mutating tools, update persistent tasks, or change project state.
- Do NOT respond with plain text while in PlanMode; always submit the plan via ExitPlanMode.
- The plan must be detailed, decision-complete, and structured.

Required plan format (markdown):

# Plano: <título descritivo>

## 1. Resumo Executivo
2-3 frases explicando O QUE será feito e POR QUÊ.

## 2. Objetivo
O problema específico que este plano resolve e a métrica de sucesso.

## 3. Estado Atual (Descobertas)
O que foi encontrado na pesquisa: arquivos relevantes, dependências, comportamento atual.

## 4. Abordagem Técnica
Estratégia de alto nível, padrões, arquiteturas ou bibliotecas. Justifique escolhas.

## 5. Mudanças Planejadas
Para CADA arquivo/módulo alterado, use uma tabela:
| Arquivo | Ação | Descrição da Mudança |

## 6. Tasks de Implementação
- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## 7. Edge Cases & Validação
Cenários de erro, inputs inválidos, race conditions. Como cada um será tratado ou testado.

## 8. Critérios de Aceitação
Lista verificável de condições que provam sucesso.

When the plan is ready, you MUST call ExitPlanMode with the full markdown plan following the format above."""


_STATE_RENDERERS = {
    "intake": _intake,
    "context_discovery": _context_discovery,
    "planning": _planning,
    "implementation": _implementation,
    "tool_execution": _tool_execution,
    "debug_recovery": _debug_recovery,
    "runtime_validation": _runtime_validation,
    "context_compaction": _context_compaction,
    "memory_recall": _memory_recall,
    "user_checkpoint": _user_checkpoint,
    "finalization": _finalization,
    "plan_mode": _plan_mode,
}
