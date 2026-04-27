"""Unit tests for StateManager."""


from personagent.application.state import AppState
from personagent.application.state.services import StateManager


class TestStateManager:
    """Tests for StateManager."""

    def setup_method(self):
        """Reset StateManager before each test."""
        StateManager.reset()

    def test_singleton_pattern(self):
        """Test that StateManager is a singleton."""
        instance1 = StateManager.get_instance()
        instance2 = StateManager.get_instance()

        assert instance1 is instance2

    def test_reset(self):
        """Test reset method."""
        instance1 = StateManager.get_instance()
        instance1.state.session_id = "test-id"

        StateManager.reset()
        instance2 = StateManager.get_instance()

        assert instance1 is not instance2
        assert instance2.state.session_id != "test-id"

    def test_state_property(self):
        """Test state property returns AppState."""
        manager = StateManager.get_instance()
        state = manager.state

        assert isinstance(state, AppState)

    def test_get_session_id(self):
        """Test get_session_id."""
        manager = StateManager.get_instance()
        session_id = manager.get_session_id()

        assert isinstance(session_id, str)
        assert len(session_id) > 0

    def test_set_conversation_id(self):
        """Test set_conversation_id."""
        manager = StateManager.get_instance()
        manager.set_conversation_id("test-conv-id")

        assert manager.get_conversation_id() == "test-conv-id"

    def test_get_conversation_id(self):
        """Test get_conversation_id."""
        manager = StateManager.get_instance()
        manager.set_conversation_id("test-conv-id")

        assert manager.get_conversation_id() == "test-conv-id"

    def test_set_workspace_root(self):
        """Test set_workspace_root."""
        manager = StateManager.get_instance()
        manager.set_workspace_root("/workspace")

        assert manager.get_workspace_root() == "/workspace"

    def test_get_workspace_root(self):
        """Test get_workspace_root."""
        manager = StateManager.get_instance()
        manager.set_workspace_root("/workspace")

        assert manager.get_workspace_root() == "/workspace"

    def test_set_permission_mode(self):
        """Test set_permission_mode."""
        manager = StateManager.get_instance()
        manager.set_permission_mode("auto")

        assert manager.get_permission_mode() == "auto"

    def test_set_permission_mode_invalid(self):
        """Test set_permission_mode with invalid mode."""
        manager = StateManager.get_instance()
        manager.set_permission_mode("invalid")

        # Should not change if invalid
        assert manager.get_permission_mode() == "manual"

    def test_get_permission_mode(self):
        """Test get_permission_mode."""
        manager = StateManager.get_instance()
        manager.set_permission_mode("ask")

        assert manager.get_permission_mode() == "ask"

    def test_get_settings(self):
        """Test get_settings."""
        manager = StateManager.get_instance()
        manager.update_settings({"key1": "value1"})

        settings = manager.get_settings()

        assert isinstance(settings, dict)
        assert settings == {"key1": "value1"}

    def test_update_settings(self):
        """Test update_settings."""
        manager = StateManager.get_instance()
        manager.update_settings({"key1": "value1"})
        manager.update_settings({"key2": "value2"})

        settings = manager.get_settings()

        assert "key1" in settings
        assert "key2" in settings

    def test_get_system_context(self):
        """Test get_system_context."""
        manager = StateManager.get_instance()
        manager.set_system_context({"git_branch": "main"})

        context = manager.get_system_context()

        assert isinstance(context, dict)
        assert context == {"git_branch": "main"}

    def test_set_system_context(self):
        """Test set_system_context."""
        manager = StateManager.get_instance()
        manager.set_system_context({"git_branch": "main"})

        assert manager.get_system_context()["git_branch"] == "main"

    def test_get_user_context(self):
        """Test get_user_context."""
        manager = StateManager.get_instance()
        manager.set_user_context({"claude_md": "# Instructions"})

        context = manager.get_user_context()

        assert isinstance(context, dict)
        assert context == {"claude_md": "# Instructions"}

    def test_set_user_context(self):
        """Test set_user_context."""
        manager = StateManager.get_instance()
        manager.set_user_context({"claude_md": "# Instructions"})

        assert manager.get_user_context()["claude_md"] == "# Instructions"

    def test_add_allowed_tool(self):
        """Test add_allowed_tool."""
        manager = StateManager.get_instance()
        manager.add_allowed_tool("read_file")

        assert "read_file" in manager.get_allowed_tools()

    def test_remove_allowed_tool(self):
        """Test remove_allowed_tool."""
        manager = StateManager.get_instance()
        manager.add_allowed_tool("read_file")
        manager.remove_allowed_tool("read_file")

        assert "read_file" not in manager.get_allowed_tools()

    def test_get_allowed_tools(self):
        """Test get_allowed_tools."""
        manager = StateManager.get_instance()
        manager.add_allowed_tool("read_file")
        manager.add_allowed_tool("write_file")

        tools = manager.get_allowed_tools()

        assert isinstance(tools, set)
        assert "read_file" in tools
        assert "write_file" in tools

    def test_increment_request_count(self):
        """Test increment_request_count."""
        manager = StateManager.get_instance()
        count1 = manager.increment_request_count()
        count2 = manager.increment_request_count()

        assert count1 == 1
        assert count2 == 2
        assert manager.state.request_count == 2

    def test_add_cost(self):
        """Test add_cost."""
        manager = StateManager.get_instance()
        cost1 = manager.add_cost(0.5)
        cost2 = manager.add_cost(0.3)

        assert cost1 == 0.5
        assert cost2 == 0.8
        assert manager.state.total_cost_usd == 0.8

    def test_get_metrics(self):
        """Test get_metrics."""
        manager = StateManager.get_instance()
        manager.increment_request_count()
        manager.add_cost(1.0)
        manager.add_api_duration(100)
        manager.add_tool_duration(50)
        manager.add_tokens_used(1000)

        metrics = manager.get_metrics()

        assert isinstance(metrics, dict)
        assert metrics["request_count"] == 1
        assert metrics["total_cost_usd"] == 1.0
        assert metrics["total_api_duration_ms"] == 100
        assert metrics["total_tool_duration_ms"] == 50
        assert metrics["total_tokens_used"] == 1000

    def test_cache_system_prompt(self):
        """Test cache_system_prompt."""
        manager = StateManager.get_instance()
        manager.cache_system_prompt("key1", "prompt content")

        assert manager.get_cached_system_prompt("key1") == "prompt content"

    def test_get_cached_system_prompt(self):
        """Test get_cached_system_prompt."""
        manager = StateManager.get_instance()
        manager.cache_system_prompt("key1", "prompt content")

        prompt = manager.get_cached_system_prompt("key1")

        assert prompt == "prompt content"
        assert manager.get_cached_system_prompt("nonexistent") is None

    def test_cache_context(self):
        """Test cache_context."""
        manager = StateManager.get_instance()
        manager.cache_context("key1", {"data": "value"})

        assert manager.get_cached_context("key1") == {"data": "value"}

    def test_get_cached_context(self):
        """Test get_cached_context."""
        manager = StateManager.get_instance()
        manager.cache_context("key1", {"data": "value"})

        context = manager.get_cached_context("key1")

        assert context == {"data": "value"}
        assert manager.get_cached_context("nonexistent") is None

    def test_clear_caches(self):
        """Test clear_caches."""
        manager = StateManager.get_instance()
        manager.cache_system_prompt("key1", "prompt")
        manager.cache_context("key2", {"data": "value"})

        manager.clear_caches()

        assert manager.get_cached_system_prompt("key1") is None
        assert manager.get_cached_context("key2") is None

    def test_reset_state(self):
        """Test reset_state."""
        manager = StateManager.get_instance()
        manager.set_conversation_id("test-id")
        manager.add_allowed_tool("read_file")

        manager.reset_state()

        assert manager.get_conversation_id() == ""
        assert len(manager.get_allowed_tools()) == 0

    def test_update_state(self):
        """Test update_state."""
        manager = StateManager.get_instance()
        manager.update_state(
            conversation_id="test-id",
            workspace_root="/workspace",
            permission_mode="auto",
        )

        assert manager.get_conversation_id() == "test-id"
        assert manager.get_workspace_root() == "/workspace"
        assert manager.get_permission_mode() == "auto"


class TestAppState:
    """Tests for AppState."""

    def test_app_state_defaults(self):
        """Test AppState with default values."""
        state = AppState()

        assert isinstance(state.session_id, str)
        assert len(state.session_id) > 0
        assert state.conversation_id == ""
        assert state.permission_mode == "manual"
        assert state.settings == {}
        assert state.system_context == {}
        assert state.user_context == {}
        assert state.workspace_root == ""
        assert state.allowed_roots == ()
        assert state.tool_permissions == {}
        assert state.allowed_tools == set()
        assert state.total_cost_usd == 0.0
        assert state.total_api_duration_ms == 0
        assert state.total_tool_duration_ms == 0
        assert state.total_tokens_used == 0
        assert state.request_count == 0

    def test_update_timestamp(self):
        """Test update_timestamp."""
        state = AppState()
        original_timestamp = state.updated_at

        state.update_timestamp()

        assert state.updated_at >= original_timestamp

    def test_with_conversation(self):
        """Test with_conversation method."""
        state = AppState()
        new_state = state.with_conversation("test-id")

        assert new_state.conversation_id == "test-id"
        assert new_state is state  # Returns self

    def test_with_workspace(self):
        """Test with_workspace method."""
        state = AppState()
        new_state = state.with_workspace("/workspace")

        assert new_state.workspace_root == "/workspace"
        assert new_state is state

    def test_with_permission_mode(self):
        """Test with_permission_mode method."""
        state = AppState()
        new_state = state.with_permission_mode("auto")

        assert new_state.permission_mode == "auto"
        assert new_state is state

    def test_add_allowed_tool(self):
        """Test add_allowed_tool."""
        state = AppState()
        state.add_allowed_tool("read_file")

        assert "read_file" in state.allowed_tools

    def test_remove_allowed_tool(self):
        """Test remove_allowed_tool."""
        state = AppState()
        state.add_allowed_tool("read_file")
        state.remove_allowed_tool("read_file")

        assert "read_file" not in state.allowed_tools

    def test_increment_request_count(self):
        """Test increment_request_count."""
        state = AppState()
        state.increment_request_count()

        assert state.request_count == 1

    def test_add_cost(self):
        """Test add_cost."""
        state = AppState()
        state.add_cost(0.5)

        assert state.total_cost_usd == 0.5

    def test_add_api_duration(self):
        """Test add_api_duration."""
        state = AppState()
        state.add_api_duration(100)

        assert state.total_api_duration_ms == 100

    def test_add_tool_duration(self):
        """Test add_tool_duration."""
        state = AppState()
        state.add_tool_duration(50)

        assert state.total_tool_duration_ms == 50

    def test_add_tokens_used(self):
        """Test add_tokens_used."""
        state = AppState()
        state.add_tokens_used(1000)

        assert state.total_tokens_used == 1000

    def test_cache_system_prompt(self):
        """Test cache_system_prompt."""
        state = AppState()
        state.cache_system_prompt("key", "prompt")

        assert state.system_prompt_cache["key"] == "prompt"

    def test_get_cached_system_prompt(self):
        """Test get_cached_system_prompt."""
        state = AppState()
        state.cache_system_prompt("key", "prompt")

        assert state.get_cached_system_prompt("key") == "prompt"
        assert state.get_cached_system_prompt("nonexistent") is None

    def test_cache_context(self):
        """Test cache_context."""
        state = AppState()
        state.cache_context("key", {"data": "value"})

        assert state.context_cache["key"] == {"data": "value"}

    def test_get_cached_context(self):
        """Test get_cached_context."""
        state = AppState()
        state.cache_context("key", {"data": "value"})

        assert state.get_cached_context("key") == {"data": "value"}
        assert state.get_cached_context("nonexistent") is None

    def test_clear_caches(self):
        """Test clear_caches."""
        state = AppState()
        state.cache_system_prompt("key", "prompt")
        state.cache_context("key", {"data": "value"})

        state.clear_caches()

        assert len(state.system_prompt_cache) == 0
        assert len(state.context_cache) == 0
