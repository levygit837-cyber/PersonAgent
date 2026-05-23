# ADR 0011: Phase-Based Multi-Agent Team Mode with Shared Blackboard

Date: 2025-06-10
Status: Accepted

## Context

Complex requests benefit from multiple specialized perspectives before a final answer. A single-agent loop can miss risks, duplicate reasoning, or produce shallow analysis. We need a structured team debate that is observable, interruptible, and deterministic.

## Decision

Implement **Team Mode** as a WebSocket flow (`/chat/team/ws`) orchestrated by `TeamChatOrchestrator` with a shared in-memory blackboard.

**Default team preset**
- `Analyst` (analysis), `Critic` (risk review), `Builder` (solution), `Reviewer` (final review).
- `Coordinator` (final synthesis) does not vote.

**Phases**
1. **Execution Contract**: Coordinator creates subproblems, focus assignments, and coverage matrix.
2. **Independent Round**: Each agent publishes a first-pass view without seeing others.
3. **Blackboard Publish**: Claims are deduplicated and scored for novelty.
4. **Debate Round**: Agents critique, refine, and publish deltas only.
5. **Coordinator Planning**: Coordinator assigns focus areas and redirects to reduce overlap.
6. **Vote**: Each agent votes `approve/confidence/blocker` with a 75% consensus threshold.
7. **Final Synthesis**: Coordinator streams the final answer via `chat_completion_stream`.

**Blackboard**
- In-memory `_Blackboard` collects `_BlackboardEntry` events with claim nodes, coverage tracking, and novelty scores.
- Persisted to PostgreSQL (`team_runs`, `team_blackboard_events`, `team_memory_snapshots`) for post-hoc analysis.

**Tool Policy**
- `guarded_autonomy`: agents can use read tools; mutating tools require explicit user approval.

## Consequences

- **Easier**: multi-perspective review catches edge cases; WebSocket provides real-time progress; blackboard is auditable.
- **Harder**: token cost scales linearly with agent count; vote logic must handle ties and critical blockers gracefully.
- **Risk**: agents can hallucinate claims that other agents then build upon; novelty scoring is heuristic and may filter valid duplication.
- **Out of scope**: dynamic agent recruitment mid-run; external agent marketplaces.

## Alternatives Considered

- **Sequential single-agent with reflection prompts**: rejected because it lacks true adversarial critique and parallel evidence gathering.
- **Separate backend service for team mode**: rejected to keep the runtime monolithic and reduce deployment surface.

## Validation

- `default_team_config()` is validated by `validate_team_config()` (2-6 agents, unique IDs, matching execution order).
- Integration tests in `@backend/tests/integration/` exercise the WebSocket contract and blackboard persistence.
