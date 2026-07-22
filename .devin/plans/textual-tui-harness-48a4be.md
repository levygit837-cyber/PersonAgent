# Textual TUI Harness — Design Plan

Write an ADR (0024) that documents the design for a persistent Textual-based TUI for the PersonAgent harness, covering layout, widgets, data flow, styling, keybinds, and placement within the `adapters/` layer.

## Steps

1. **Write ADR 0024** at `docs/adr/0024-textual-tui-harness.md` following the project ADR template, incorporating:
   - Textual framework choice with CSS-like TCSS styling
   - Persistent dashboard layout: Header, Main Chat Area (inline foldable cards), Right Stats Panel, Footer Input
   - Custom widget taxonomy: `ChatMessage`, `ToolCallCard`, `McpCallCard`, `SkillCard`, `BrowserEventCard`, `ReasoningBlock`, `StreamingIndicator`, `StatsPanel`, `InputBar`
   - Data flow from `ChatCompletionUseCase.execute_stream()` into reactive widget state
   - Keybinds: Enter=send, Ctrl+Enter=newline, ↑/↓=history, slash commands for conversation mgmt, Ctrl+R=toggle right panel
   - Folder placement under `adapters/tui/` per ADR 0022 folder structure principles
   - Out of scope: Browser DOM preview (desktop-only), team mode multi-agent UI, file upload

2. **Self-review** the ADR for placeholders, contradictions, ambiguity, and scope.

3. **Ask user to review** the written ADR before proceeding to implementation plan.
