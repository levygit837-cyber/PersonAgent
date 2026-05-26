"""Tool registry and runtime configuration mixin."""

from personagent.application.tools import ToolRegistry, ToolRuntimeConfig
from personagent.infrastructure.persistence.database import AsyncSessionLocal
from personagent.infrastructure.persistence.task_store import SqlAlchemyTaskStore
from personagent.infrastructure.tools import (
    create_agent_tools,
    create_ask_user_question_tool,
    create_browser_tools,
    create_config_tool,
    create_edit_file_tool,
    create_enter_plan_mode_tool,
    create_enter_worktree_tool,
    create_exit_plan_mode_tool,
    create_exit_worktree_tool,
    create_glob_tool,
    create_grep_tool,
    create_lsp_tool,
    create_mcp_tools,
    create_read_file_tool,
    create_send_user_message_tool,
    create_shell_tool,
    create_skill_tool,
    create_structured_output_tool,
    create_task_tools,
    create_todo_write_tool,
    create_tool_search_tool,
    create_web_fetch_tool,
    create_web_search_tool,
    create_write_file_tool,
)


class _ToolMixin:
    def get_tool_registry(self) -> ToolRegistry:
        """Retorna o registry de ferramentas locais (singleton)."""
        if self._tool_registry is None:
            task_store = SqlAlchemyTaskStore(AsyncSessionLocal)
            registry = ToolRegistry()
            for tool in [
                create_read_file_tool(),
                create_write_file_tool(),
                create_edit_file_tool(),
                create_glob_tool(),
                create_grep_tool(),
                create_shell_tool(),
                create_config_tool(),
                create_enter_worktree_tool(),
                create_exit_worktree_tool(),
                create_ask_user_question_tool(),
                create_send_user_message_tool(enabled=self._settings.brief_tool_enabled),
                create_web_fetch_tool(),
                create_web_search_tool(enabled=False),
                *create_browser_tools(self.get_lightpanda_browser_worker()),
                *create_mcp_tools(
                    self._settings.tool_mcp_server_configs,
                    enabled=self._settings.tools_mcp_enabled,
                ),
                create_lsp_tool(enabled=self._settings.tools_lsp_enabled),
                create_enter_plan_mode_tool(),
                create_exit_plan_mode_tool(),
                create_todo_write_tool(),
                *create_agent_tools(task_store),
                *create_task_tools(task_store),
                create_skill_tool(),
                create_structured_output_tool(),
            ]:
                registry.register(tool)
            registry.register(create_tool_search_tool(lambda: registry))
            self._tool_registry = registry
        return self._tool_registry

    def get_tool_runtime_config(self) -> ToolRuntimeConfig:
        """Return the tool runtime configuration."""
        if self._tool_runtime_config is None:
            self._tool_runtime_config = ToolRuntimeConfig.from_values(
                workspace_root=self._settings.tool_workspace_root_path,
                allowed_roots=self._settings.tool_allowed_root_paths,
                max_tool_iterations=self._settings.tools_max_iterations,
                max_concurrency=self._settings.tools_max_concurrency,
                read_max_bytes=self._settings.tools_read_max_bytes,
                read_default_limit=self._settings.tools_read_default_limit,
                read_max_lines=self._settings.tools_read_max_lines,
                search_timeout_ms=self._settings.tools_search_timeout_ms,
                shell_timeout_ms=self._settings.tools_shell_timeout_ms,
                web_timeout_ms=self._settings.tools_web_timeout_ms,
                web_max_bytes=self._settings.tools_web_max_bytes,
                result_max_chars=self._settings.tools_result_max_chars,
                tool_result_storage_root=(
                    self._settings.tools_result_storage_root
                    or self._settings.personagent_artifact_root
                ),
                web_allowed_domains=self._settings.tool_web_allowed_domain_list,
                web_blocked_domains=self._settings.tool_web_blocked_domain_list,
                skill_roots=self._settings.tool_skill_root_paths,
                lsp_enabled=self._settings.tools_lsp_enabled,
            )
        return self._tool_runtime_config
