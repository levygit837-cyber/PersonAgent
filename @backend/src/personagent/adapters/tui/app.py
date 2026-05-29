"""PersonAgent TUI — Terminal chat interface."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from textual.app import App
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Header

from personagent.adapters.tui.client import (
    ChatRequestPayload,
    get_conversation,
    list_conversations,
    list_models,
    resolve_backend_url,
    stream_chat_completion,
)
from personagent.adapters.tui.widgets import (
    ChatContainer,
    InputBar,
    MemoryRecallBlock,
    ModelLabel,
    ModelList,
    StreamingIndicator,
    ToolCallGroup,
)
from personagent.adapters.tui.widgets.chat_message import ChatMessage
from personagent.adapters.tui.widgets.command_palette import CommandPalette
from personagent.adapters.tui.widgets.session_list import SessionList
from personagent.adapters.tui.widgets.tool_call_group import (
    is_memory_recall_event,
    is_tool_stream_event,
)


class ChatApp(App[None]):
    """Textual app for PersonAgent chat."""

    CSS_PATH = "styles/personagent.tcss"

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
        ("t", "toggle_thinking", "Toggle Thinking"),
        ("pageup", "scroll_up", "Scroll Up"),
        ("pagedown", "scroll_down", "Scroll Down"),
        ("home", "scroll_top", "Scroll Top"),
        ("end", "scroll_bottom", "Scroll Bottom"),
        ("escape", "palette_close", "Palette Close"),
    ]

    is_streaming: reactive[bool] = reactive(False)
    conversation_id: reactive[str | None] = reactive(None)
    model_name: reactive[str] = reactive("deepseek-v4-flash")

    def __init__(self, base_url: str | None = None, **kwargs: Any) -> None:
        self._base_url = base_url
        self._abort_event = asyncio.Event()
        self._stream_aborted = False
        self._current_agent_message: ChatMessage | None = None
        self._current_tool_group: ToolCallGroup | None = None
        self._current_memory_block: MemoryRecallBlock | None = None
        self._command_palette: CommandPalette | None = None
        self._session_list: SessionList | None = None
        self._session_overlay: Container | None = None
        self._model_list: ModelList | None = None
        super().__init__(**kwargs)

    def compose(self) -> Any:
        yield Container(
            Header(),
            ChatContainer(id="chat-container"),
            StreamingIndicator(id="streaming-indicator"),
            InputBar(id="input-bar"),
            ModelLabel(id="model-label"),
            id="main-container",
        )

    async def on_mount(self) -> None:
        self.title = "PersonAgent"
        self.sub_title = "Chat"
        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.focus()
        self._backend_url = self._base_url or await resolve_backend_url()

    def on_text_area_changed(self, event: InputBar.Changed) -> None:
        """Show/hide the command palette as the user types."""
        text = event.text_area.text
        if text.startswith("/") and "\n" not in text and " " not in text:
            self._show_palette(text)
        else:
            self._hide_palette()

    def _show_palette(self, query: str) -> None:
        """Mount or update the command palette above the input bar."""
        if self._command_palette is None:
            self._command_palette = CommandPalette(id="command-palette")
            main_container = self.query_one("#main-container", Container)
            input_bar = self.query_one("#input-bar", InputBar)
            main_container.mount(self._command_palette, before=input_bar)
        self._command_palette.query = query

    def _hide_palette(self) -> None:
        """Remove the command palette if it exists."""
        if self._command_palette is not None:
            self._command_palette.remove()
            self._command_palette = None

    def action_palette_select(self) -> None:
        """Auto-complete the currently selected command from the palette."""
        if self._command_palette is None:
            return
        cmd = self._command_palette.get_selected_command()
        if cmd is None:
            return
        input_bar = self.query_one("#input-bar", InputBar)
        new_text = f"/{cmd.name} "
        input_bar.text = new_text
        input_bar.cursor_location = (0, len(new_text))

    def action_palette_up(self) -> None:
        """Move selection up in the command palette."""
        if self._command_palette is not None:
            self._command_palette.move_selection(-1)

    def action_palette_down(self) -> None:
        """Move selection down in the command palette."""
        if self._command_palette is not None:
            self._command_palette.move_selection(1)

    def _abort_stream(self) -> None:
        """Abort the current stream and show an interrupted label."""
        self._stream_aborted = True
        self._abort_event.set()
        self.is_streaming = False
        indicator = self.query_one("#streaming-indicator", StreamingIndicator)
        indicator.is_streaming = False
        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.focus()

        container = self.query_one("#chat-container", ChatContainer)
        if self._current_agent_message is not None:
            container.mark_aborted(self._current_agent_message)
        else:
            # No message created yet: inject one with the interrupted label
            self._current_agent_message = container.add_message(
                "agent",
                "",
                aborted=True,
                model=self.model_name,
            )

    def _hide_model_list(self) -> None:
        """Remove the floating model list if it exists."""
        if self._model_list is not None:
            self._model_list.remove()
            self._model_list = None

    def action_palette_close(self) -> None:
        """Close any open overlays or abort streaming if active."""
        if self._command_palette is not None:
            self._hide_palette()
            return
        if self._model_list is not None:
            self._hide_model_list()
            return
        if self._session_overlay is not None:
            self._session_overlay.remove()
            self._session_overlay = None
            self._session_list = None
            return
        if self.is_streaming:
            self._abort_stream()
            return

    def action_submit(self) -> None:
        """Submit the current input text (Enter)."""
        if self.is_streaming:
            return
        input_bar = self.query_one("#input-bar", InputBar)
        text = input_bar.text.strip()
        if not text:
            return
        # Handle local slash commands
        if text.startswith("/"):
            self._handle_slash_command(text)
            return
        self._send_message(text)

    def _handle_slash_command(self, text: str) -> None:
        """Process local slash commands."""
        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.text = ""
        self._hide_palette()

        parts = text.split(None, 1)
        command = parts[0][1:].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == "sessions":
            self.run_worker(self._show_sessions(), name="show_sessions", thread=False)
            return
        if command in ("clear", "new"):
            self._clear_chat()
            return
        if command == "help":
            self._show_help()
            return
        if command == "model":
            self.run_worker(self._handle_model(args), name="handle_model", thread=False)
            return
        if command == "effort":
            self._handle_effort(args)
            return
        if command == "skills":
            self._show_not_implemented("skills", "Skills workspace")
            return
        if command == "permissions":
            self._show_not_implemented("permissions", "Tool permissions inspector")
            return
        if command == "usage":
            self._show_not_implemented("usage", "Token and tool usage")
            return
        if command == "status":
            self._show_not_implemented("status", "Workspace and session status")
            return

        # Unknown local command: treat as chat message so backend can handle it
        self._send_message(text)

    def _clear_chat(self) -> None:
        """Clear the chat container and reset conversation state."""
        container = self.query_one("#chat-container", ChatContainer)
        for child in list(container.children):
            child.remove()
        self.conversation_id = None
        self._current_agent_message = None

    def _show_help(self) -> None:
        """Display available slash commands in the chat."""
        from personagent.adapters.tui.widgets.command_palette import BUILTIN_COMMANDS
        lines = ["**Available slash commands:**", ""]
        for cmd in BUILTIN_COMMANDS:
            hint = f" `{cmd.argument_hint}`" if cmd.argument_hint else ""
            lines.append(f"`/{cmd.name}`{hint} — {cmd.description}")
        container = self.query_one("#chat-container", ChatContainer)
        container.add_message("agent", "\n".join(lines))

    def on_session_list_session_selected(
        self, event: SessionList.SessionSelected
    ) -> None:
        """Switch to the selected conversation and load its messages."""
        self.conversation_id = event.session_id
        if self._session_overlay is not None:
            self._session_overlay.remove()
            self._session_overlay = None
            self._session_list = None
        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.focus()
        self.run_worker(
            self._load_session(event.session_id), name="load_session", thread=False
        )

    async def _show_sessions(self) -> None:
        """Fetch and display the session list overlay centered on screen."""
        container = self.query_one("#chat-container", ChatContainer)
        try:
            sessions = await list_conversations(self._backend_url)
        except Exception as exc:
            container.add_message("agent", f"**Error loading sessions:** {exc}")
            return

        overlay = Container(id="session-overlay")
        self.screen.mount(overlay)
        self._session_overlay = overlay
        self._session_list = SessionList(id="session-list")
        overlay.mount(self._session_list)

        self._session_list.sessions = sessions
        self._session_list.focus()

    async def _load_session(self, session_id: str) -> None:
        """Clear chat and render the selected conversation's messages."""
        container = self.query_one("#chat-container", ChatContainer)
        for child in list(container.children):
            child.remove()
        self._current_agent_message = None
        try:
            conv = await get_conversation(self._backend_url, session_id)
            messages = conv.get("messages", [])
            if not messages:
                container.add_message(
                    "agent", f"*Session `{session_id[:8]}...` has no messages.*"
                )
                return
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls")
                if role == "user":
                    container.add_message("user", content)
                elif role in ("assistant", "agent"):
                    thinking = ""
                    metadata = msg.get("metadata") or {}
                    if isinstance(metadata, dict):
                        reasoning = metadata.get("reasoning_content")
                        if reasoning and isinstance(reasoning, str):
                            thinking = reasoning
                    if not content and tool_calls:
                        content = self._format_tool_calls(tool_calls)
                    container.add_message("agent", content, thinking=thinking)
                elif role == "tool":
                    container.add_message("agent", content)
        except Exception as exc:
            container.add_message("agent", f"**Error loading session:** {exc}")

    def _handle_effort(self, args: str) -> None:
        """Handle the /effort command: show or set reasoning effort."""
        container = self.query_one("#chat-container", ChatContainer)
        if args.strip():
            level = args.strip().lower()
            os.environ["PERSONAGENT_REASONING_LEVEL"] = level
            container.add_message("agent", f"Reasoning effort set to `{level}`.")
        else:
            level = os.environ.get("PERSONAGENT_REASONING_LEVEL", "medium")
            container.add_message(
                "agent",
                f"**Current reasoning effort:** `{level}`\n\n"
                f"Supported levels: `low`, `medium`, `high`, `xhigh`, `max`",
            )

    def _show_not_implemented(self, command: str, feature: str) -> None:
        """Show a friendly message for commands not yet available in the TUI."""
        container = self.query_one("#chat-container", ChatContainer)
        container.add_message(
            "agent",
            f"{feature} is a desktop UI action and is not yet implemented in the TUI terminal.\n\n"
            f"Use the PersonAgent desktop app for full `{command}` functionality.",
        )

    async def _handle_model(self, args: str) -> None:
        """Handle the /model command: show current model or list available models."""
        if args.strip():
            container = self.query_one("#chat-container", ChatContainer)
            parts = args.strip().split("/", 1)
            if len(parts) == 2:
                provider, model = parts
                os.environ["PERSONAGENT_PROVIDER"] = provider.strip()
                os.environ["PERSONAGENT_MODEL"] = model.strip()
                self.model_name = f"{provider.strip()}/{model.strip()}"
            else:
                os.environ["PERSONAGENT_MODEL"] = args.strip()
                self.model_name = args.strip()
            container.add_message(
                "agent", f"Model set to `{self.model_name}`."
            )
            return

        # No args: show floating model card overlay
        provider = os.environ.get("PERSONAGENT_PROVIDER", "deepseek")
        try:
            data = await list_models(self._backend_url, provider=provider)
            models = data.get("data", [])
        except Exception as exc:
            container = self.query_one("#chat-container", ChatContainer)
            container.add_message("agent", f"**Error fetching models:** {exc}")
            return

        self._model_list = ModelList(id="model-list")
        self.screen.mount(self._model_list)

        # Center the floating card on screen
        card_width = 60
        card_height = min(len(models) + 2, 40)
        offset_x = max(0, (self.screen.size.width - card_width) // 2)
        offset_y = max(0, (self.screen.size.height - card_height) // 2)
        self._model_list.styles.offset = (offset_x, offset_y)

        self._model_list.models = models
        self._model_list.focus()

    def on_model_list_model_selected(self, event: ModelList.ModelSelected) -> None:
        """Update the active model when selected from the floating card."""
        self.model_name = event.model_name
        parts = event.model_name.split("/", 1)
        if len(parts) == 2:
            os.environ["PERSONAGENT_PROVIDER"] = parts[0].strip()
            os.environ["PERSONAGENT_MODEL"] = parts[1].strip()
        else:
            os.environ["PERSONAGENT_MODEL"] = event.model_name.strip()
        self._hide_model_list()
        input_bar = self.query_one("#input-bar", InputBar)
        input_bar.focus()

    def _send_message(self, text: str) -> None:
        container = self.query_one("#chat-container", ChatContainer)
        input_bar = self.query_one("#input-bar", InputBar)
        indicator = self.query_one("#streaming-indicator", StreamingIndicator)

        container.add_message("user", text, model=self.model_name)
        input_bar.text = ""
        self.is_streaming = True
        indicator.is_streaming = True

        self.run_worker(
            self._stream_response(text),
            name="stream_response",
            thread=False,
        )

    async def _stream_response(self, text: str) -> None:
        container = self.query_one("#chat-container", ChatContainer)
        indicator = self.query_one("#streaming-indicator", StreamingIndicator)

        payload = ChatRequestPayload(
            message=text,
            stream=True,
            conversation_id=self.conversation_id,
            provider=os.environ.get("PERSONAGENT_PROVIDER", "deepseek"),
            model=os.environ.get("PERSONAGENT_MODEL", "deepseek-v4-flash"),
            reasoning_level=os.environ.get("PERSONAGENT_REASONING_LEVEL", "medium"),
        )

        try:
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            was_thinking = False
            current_thinking_msg: ChatMessage | None = None
            current_content_msg: ChatMessage | None = None

            async for chunk in stream_chat_completion(
                self._backend_url,
                payload,
                signal=self._abort_event,
            ):
                if chunk.conversation_id:
                    self.conversation_id = chunk.conversation_id
                if chunk.model:
                    self.model_name = chunk.model

                if is_memory_recall_event(chunk):
                    if self._current_memory_block is None:
                        self._current_memory_block = container.add_memory_recall(
                            model=self.model_name,
                        )
                    self._current_memory_block.update_from_chunk(chunk)
                    await asyncio.sleep(0)
                    continue

                if is_tool_stream_event(chunk):
                    content_parts = []
                    thinking_parts = []
                    current_content_msg = None
                    current_thinking_msg = None
                    self._current_agent_message = None
                    self._current_memory_block = None
                    if self._current_tool_group is None:
                        self._current_tool_group = container.add_tool_group(
                            model=self.model_name,
                        )
                    self._current_tool_group.upsert_chunk(chunk)
                    await asyncio.sleep(0)
                    continue

                is_now_thinking = bool(chunk.is_thinking)

                # Start of a new reasoning block: create a new message
                if is_now_thinking and not was_thinking:
                    thinking_parts = []
                    current_thinking_msg = container.add_message(
                        "agent",
                        "",
                        thinking="",
                        model=self.model_name,
                    )
                    current_content_msg = None
                    self._current_tool_group = None
                    self._current_memory_block = None

                # Capture reasoning/thinking content
                if chunk.reasoning_content:
                    thinking_parts.append(chunk.reasoning_content)
                    full_thinking = "".join(thinking_parts)
                    self._current_tool_group = None
                    self._current_memory_block = None
                    if current_thinking_msg is not None:
                        container.update_thinking(current_thinking_msg, full_thinking)
                        self._current_agent_message = current_thinking_msg
                    await asyncio.sleep(0)

                if chunk.content:
                    # Skip raw tool JSON or tool args that the backend mirrors as content
                    if self._is_tool_like_content(chunk.content):
                        await asyncio.sleep(0)
                        continue
                    content_parts.append(chunk.content)
                    full_text = "".join(content_parts)
                    self._current_tool_group = None
                    self._current_memory_block = None
                    if current_content_msg is None:
                        current_content_msg = container.add_message(
                            "agent",
                            full_text,
                            model=self.model_name,
                        )
                    else:
                        container.update_message(current_content_msg, full_text)
                    self._current_agent_message = current_content_msg
                    await asyncio.sleep(0)

                # Tool calls signal a phase transition
                if chunk.tool_calls:
                    content_parts = []
                    thinking_parts = []
                    current_content_msg = None
                    current_thinking_msg = None
                    self._current_tool_group = None
                    self._current_memory_block = None
                    # Tool execution details arrive as tool_* stream events.

                was_thinking = is_now_thinking

                if chunk.finish_reason:
                    break

        except Exception as exc:
            container.add_message("agent", f"**Error:** {exc}")
        finally:
            self.is_streaming = False
            indicator.is_streaming = False
            input_bar = self.query_one("#input-bar", InputBar)
            input_bar.focus()

            # If stream was aborted and no message exists yet, inject an interrupted label
            if self._stream_aborted and self._current_agent_message is None:
                container.add_message("agent", "", aborted=True, model=self.model_name)

            self._current_agent_message = None
            self._current_tool_group = None
            self._current_memory_block = None
            self._stream_aborted = False
            self._abort_event.clear()

    def _format_tool_calls(self, tool_calls: list[dict[str, Any]]) -> str:
        """Format tool calls into a readable plain-text string (no code blocks, no labels)."""
        lines: list[str] = []
        for call in tool_calls:
            name = call.get("function", {}).get("name") if "function" in call else call.get("name")
            args = call.get("function", {}).get("arguments") if "function" in call else call.get("arguments")
            if name:
                lines.append(f"  - {name}")
            if args:
                arg_str = str(args).replace("\n", "\n    ")
                lines.append(f"    args: {arg_str}")
        return "\n".join(lines)

    def action_toggle_thinking(self) -> None:
        """Toggle thinking block visibility for all agent messages."""
        from personagent.adapters.tui.widgets.chat_message import ChatMessage
        for msg in self.query(ChatMessage):
            if msg.role == "agent":
                msg.thinking_visible = not msg.thinking_visible

    def action_scroll_up(self) -> None:
        """Scroll the chat container up by one page."""
        container = self.query_one("#chat-container", ChatContainer)
        container.scroll_page_up()

    def action_scroll_down(self) -> None:
        """Scroll the chat container down by one page."""
        container = self.query_one("#chat-container", ChatContainer)
        container.scroll_page_down()

    def action_scroll_top(self) -> None:
        """Scroll to the top of the chat container."""
        container = self.query_one("#chat-container", ChatContainer)
        container.scroll_home()

    def action_scroll_bottom(self) -> None:
        """Scroll to the bottom of the chat container."""
        container = self.query_one("#chat-container", ChatContainer)
        container.scroll_end()

    def _is_tool_like_content(self, text: str) -> bool:
        """Heuristic: detect raw tool JSON or tool args the backend sends as content."""
        text = text.strip()
        if not text:
            return False
        # Raw JSON result with known tool type field
        if text.startswith("{"):
            prefix = text[:300]
            if '"type"' in prefix:
                return any(
                    t in prefix
                    for t in (
                        '"file_read"',
                        '"read_file"',
                        '"shell"',
                        '"glob_results"',
                        '"search_files"',
                        '"write_file"',
                        '"edit_file"',
                        '"web_fetch"',
                        '"web_search"',
                        '"browser"',
                    )
                )
            return False
        # Plain-text tool args description, e.g. "shell args: {...}"
        first_line = text.split("\n", 1)[0]
        m = re.match(r"^(\w+)\s+args:\s*\{", first_line)
        if m:
            tool_name = m.group(1).lower()
            return tool_name in {
                "shell",
                "read",
                "write",
                "edit",
                "glob",
                "grep",
                "search",
            }
        return False

    def action_quit(self) -> None:
        if self._command_palette is not None or self._session_list is not None or self._model_list is not None:
            self.action_palette_close()
            return
        if self.is_streaming:
            self._abort_stream()
        else:
            self.exit()
