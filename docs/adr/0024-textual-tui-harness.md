# ADR 0024: Textual TUI Harness (Persistent Terminal UI)

Date: 2026-05-27
Status: Proposed

## Context

PersonAgent currently exposes two user-facing entry points: a web UI served by FastAPI (`adapters/api/`, ADR 0002) and a one-shot CLI (`adapters/cli/`, Typer + Rich). Neither provides a persistent, interactive terminal experience comparable to Claude Code or Codex CLI. Users who prefer terminal workflows must run `personagent chat -m "hello"` repeatedly, losing context, streaming state, and conversation history across invocations.

A persistent TUI solves this by keeping the application alive, streaming responses in real time, folding tool/MCP/skill activity inline, and surfacing session statistics — all inside the terminal.

## Decision

Adopt **Textual** as the TUI framework and create a new `adapters/tui/` entry point.

### Framework choice: Textual

Textual provides CSS-like styling (TCSS), reactive data (`Reactive`), composable widgets, and built-in keybinding handling. It is the standard Python TUI framework and directly supports all requirements: streaming content, foldable cards, panels, and dark-mode theming. Rich is already a transitive dependency; Textual builds on Rich's renderables.

### Layout: persistent two-zone dashboard

```text
┌──────────────────────────────────────────────┬──────────────────┐
│                                              │  [ready]         │
│  User: How do I fix this bug?                │                  │
│                                              │  Tokens: 12.4k   │
│  🤖 Let me search the codebase...            │  Tools: 3 calls  │
│                                              │  MCP: 0 calls    │
│  ┌─ Tool: grep_search ─────────────────┐     │  Skills: 1       │
│  │  Found 3 matches in src/auth.py      │     │  Duration: 0:42  │
│  └─────────────────────────────────────┘     │                  │
│                                              │                  │
│  ┌─ MCP: ReadMcpResource ──────────────┐     │                  │
│  │  {"content": "..."}                  │     │                  │
│  └─────────────────────────────────────┘     │                  │
│                                              │                  │
│  ┌─ Reasoning... ──────────────────────┐     │                  │
│  │  Looking at the auth flow...       │     │                  │
│  └─────────────────────────────────────┘     │                  │
│                                              │                  │
│  The bug is in the token validation...       │                  │
│                                              │                  │
├──────────────────────────────────────────────┴──────────────────┤
│  streaming...                                                 │
├─────────────────────────────────────────────────────────────────┤
│  How do I fix this bug?                                         │
├─────────────────────────────────────────────────────────────────┤
│  llama-3.3-70b  |  reasoning: medium  |  temp: 0.7               │
└─────────────────────────────────────────────────────────────────┘
```

- **Main Chat Area** (left ~75%): Scrollable chat stream starting from the top edge, with user/assistant message bubbles, inline dedicated widgets for tool calls, MCP calls, reasoning, skills, and browser events
- **Right Stats Panel** (right ~25%): Session statistics — status indicator (`[ready]`, `[streaming]`, `[tool_running]`), token counts, tool call counts, MCP call counts, active skills, session duration, current conversation ID. Collapsible via `Ctrl+R`.
- **Streaming Status Bar** (above input): Dynamic text showing current activity (`Thinking...`, `Running shell_tool...`, `Calling MCP server...`, `Fetching web page...`)
- **Input Bar** (bottom): Single-line text input, no prompt character; Enter=send, Ctrl+Enter=newline
- **Model Info Bar** (below input): Active model name, reasoning effort level, temperature, and other model parameters

### Widget taxonomy

All widgets live under `adapters/tui/widgets/`.

| Widget | Purpose |
| ------ | ------- |
| `ChatContainer` | Scrollable container for the chat stream; owns reactive message list |
| `ChatMessage` | User or assistant bubble; renders markdown via `rich.markdown.Markdown` |
| `StreamingIndicator` | Dynamic status text bar above the input; shows current activity (`Thinking...`, `Running grep_search...`, etc.) |
| `ReasoningBlock` | Dedicated widget for model reasoning/thinking content; collapsible, styled with subtle border and muted colors |
| `ToolCallCard` | Dedicated widget for tool calls with visual chrome (border, icon, status badge); color-coded: **amber**=running, **green**=success, **red**=error |
| `McpCallCard` | Same pattern as `ToolCallCard`, for MCP server calls |
| `SkillCard` | Skill invocation name, arguments, and result summary |
| `BrowserEventCard` | Browser tool call events (e.g., `browser_navigate`, `browser_click`) |
| `StatsPanel` | Right-side reactive stats panel; observes stream/tool events to update counters |
| `InputBar` | Single-line text input; Enter=send, Ctrl+Enter=newline, ↑/↓=history |
| `PersonAgentApp` | Root `App` widget; owns CSS, global state, keybinds, conversation lifecycle |

### Data flow

```text
┌─────────────┐     Enter           ┌──────────────────┐
│  InputBar   │ ── message ───────> │ ChatContainer    │
└─────────────┘                     │ (append user msg) │
                                    └────────┬─────────┘
                                             │
                              async execute_stream(dto)
                                             │
                         ┌───────────────────┼───────────────────┐
                         │                   │                   │
                         ▼                   ▼                   ▼
                   content chunks    reasoning chunks    tool_call cards
                         │                   │                   │
                         ▼                   ▼                   ▼
                  ChatMessage       ReasoningBlock      ToolCallCard
                  (append text)     (update)            /McpCallCard
                                                         /SkillCard
                                                         /BrowserEventCard
                         │
                         ▼
                  StatsPanel (update token/tool/skill counters)
```

1. **User sends** → `InputBar` emits `Submit` event → `PersonAgentApp` appends user `ChatMessage` to `ChatContainer`
2. **App spawns** `asyncio.Task` running `ChatCompletionUseCase.execute_stream(dto)`
3. **Chunks arrive** → reactive state updates in `ChatContainer`:
   - `content` → live-appended to current assistant `ChatMessage`
   - `reasoning_content` → `ReasoningBlock` (collapsible)
   - `tool_calls` → `ToolCallCard` / `McpCallCard` / `BrowserEventCard`
   - `skill_invocations` → `SkillCard`
4. **Stream ends** → conversation saved via `PostgresConversationRepository`; `StatsPanel` reflects final state

### Keybinds and slash commands

| Keybind / Command | Action |
| ----------------- | ------ |
| `Enter` | Send message |
| `Ctrl+Enter` | Insert newline in input |
| `↑` / `↓` | Navigate input history (local per session) |
| `/new` | Start a new conversation |
| `/switch <id>` | Switch to an existing conversation |
| `/list` | List recent conversations (overlay panel) |
| `/model` | Show model info overlay |
| `/quit` or `q` | Quit TUI |
| `Ctrl+R` | Toggle right stats panel visibility |
| `Ctrl+L` | Clear chat (keep conversation) |

### Styling

- **TCSS file**: `adapters/tui/styles/personagent.tcss`
- **Dark mode default** (Textual default)
- **Theme tokens**: primary accent (blue for agent), user accent (white), error (red), success (green), warning (amber), info (cyan)
- **Card borders**: `round` for normal messages, `heavy` for running tool calls, `double` for assistant responses
- **Color coding**: Tool cards use group-based colors (file ops = blue, shell = yellow, MCP = purple, browser = orange, skills = green)

### Folder placement

Per ADR 0022 (Folder Structure Principles), the TUI lives as a sibling to existing adapters:

```text
adapters/
├── api/
├── cli/
├── tui/                    ← NEW
│   ├── __init__.py
│   ├── app.py              # PersonAgentApp root
│   ├── commands.py         # slash command handlers
│   ├── state.py            # reactive session state (conversation, stats)
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── chat_container.py
│   │   ├── chat_message.py
│   │   ├── streaming_indicator.py
│   │   ├── reasoning_block.py
│   │   ├── tool_call_card.py
│   │   ├── mcp_call_card.py
│   │   ├── skill_card.py
│   │   ├── browser_event_card.py
│   │   ├── stats_panel.py
│   │   ├── input_bar.py
│   │   └── model_info_bar.py
│   └── styles/
│       └── personagent.tcss
└── composition/
```

No single-file folders (Principle 1). `widgets/` is justified (>3 files). `styles/` is a Textual convention for TCSS files.

### Error handling

- **Backend errors** (`PersonAgentError`): Inline red `ChatMessage` with retry button keybind (`r` to retry)
- **Connection loss** (LLM backend down): Streaming status bar shows `[offline]` in red; right Stats Panel model status updates to "disconnected"; automatic retry with exponential backoff
- **Tool failures**: Card border turns red; expandable error detail inside the card body
- **Stream interruption**: Resume from `PostgresConversationRepository` state — full message history is preserved, user can continue the conversation seamlessly
- **Input validation**: Invalid slash commands show inline error tooltip in streaming status bar, no crash

### Integration with existing adapters

The TUI becomes the default entry point. Running `personagent` with no subcommand launches the TUI. Existing one-shot commands remain available as explicit subcommands (`personagent chat`, `personagent serve`, etc.).

```python
# adapters/cli/main.py
# Change no_args_is_help=True → default command launches TUI
@app.command("tui", hidden=True)  # kept for backward compatibility
@app.callback(invoke_without_command=True)
def default(ctx: typer.Context) -> None:
    """Launch the persistent interactive TUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        from personagent.adapters.tui.app import PersonAgentApp
        app = PersonAgentApp()
        app.run()
```

The TUI uses the same `DIContainer` (`adapters/composition/`), the same `ChatRequestDTO`, and the same use cases as the one-shot `chat` command. The only new dependency is `textual`.

## Consequences

- **Easier**: terminal-first users get a Claude Code-like experience; streaming, tool visibility, and conversation persistence are first-class
- **Easier**: TUI reuses existing use cases, DTOs, and DI container — no backend logic duplication
- **Harder**: Textual widgets have a lifecycle (mount, compose, watch) that must be correctly synchronized with async generator chunks; tests need `textual.testing` patterns
- **Risk**: TCSS styling is separate from the desktop Electron UI; visual consistency between TUI and desktop requires manual coordination
- **Out of scope**: Browser DOM preview (desktop-only per ADR 0013), team mode multi-agent orchestration UI, file upload/drag-drop, voice input

## Alternatives Considered

- **Rich + custom loop (no Textual)**: rejected — building layout, focus management, and keybinding from scratch with Rich `Live` and `Console` would reimplement what Textual already does. Rich is excellent for renderables, but Textual owns the app framework.
- **prompt_toolkit**: rejected — no built-in layout engine or CSS-like styling; would require custom widget system.
- **ncurses / urwid**: rejected — Python 3.11+ projects favor Textual; ncurses is low-level and urwid is unmaintained.
- **Standalone TUI package (outside @backend)**: rejected — would duplicate DI container wiring, settings loading, and use-case composition for no architectural benefit. The TUI is an adapter, not a separate bounded context.
- **Replace `cli/` entirely**: rejected — one-shot commands (`serve`, `model`, `memory_worker`) remain valid as explicit subcommands. The TUI is the default experience, not a replacement.

## Validation

- Unit tests per widget: `tests/unit/tui/widgets/test_chat_message.py`, `test_tool_call_card.py`, etc.
- Integration tests for full app lifecycle: `tests/integration/tui/test_app_streaming.py`
- Mock LLM backend for deterministic streaming tests using `textual.testing.Pilot`
- Smoke test: `personagent` exits 0 (launches TUI); `personagent chat --help` still works; `personagent serve` still works
- TCSS validation: `textual run --dev` hot-reload for style iteration
- CI gate: `pytest tests/unit/tui/ tests/integration/tui/ -q` passes
