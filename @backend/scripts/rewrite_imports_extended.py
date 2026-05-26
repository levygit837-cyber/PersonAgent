#!/usr/bin/env python3
"""Extended import rewrites for sub-package moves."""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
BACKEND_ROOT = PROJECT_ROOT / "@backend"
SRC_ROOT = BACKEND_ROOT / "src" / "personagent"
TEST_ROOT = BACKEND_ROOT / "tests"

REPLACEMENTS = [
    # application/use_cases/chat/
    (r"from personagent\.application\.use_cases\.chat\.after_turn", "from personagent.application.use_cases.chat.lifecycle.after_turn"),
    (r"from personagent\.application\.use_cases\.chat\.assistant_pass", "from personagent.application.use_cases.chat.lifecycle.assistant_pass"),
    (r"from personagent\.application\.use_cases\.chat\.background_tasks", "from personagent.application.use_cases.chat.lifecycle.background_tasks"),
    (r"from personagent\.application\.use_cases\.chat\.compaction", "from personagent.application.use_cases.chat.lifecycle.compaction"),
    (r"from personagent\.application\.use_cases\.chat\.conversation_lifecycle", "from personagent.application.use_cases.chat.lifecycle.conversation_lifecycle"),
    (r"from personagent\.application\.use_cases\.chat\.memory_recall", "from personagent.application.use_cases.chat.memory.memory_recall"),
    (r"from personagent\.application\.use_cases\.chat\.operational_memory", "from personagent.application.use_cases.chat.memory.operational_memory"),
    (r"from personagent\.application\.use_cases\.chat\.media_policy", "from personagent.application.use_cases.chat.messaging.media_policy"),
    (r"from personagent\.application\.use_cases\.chat\.message_preparation", "from personagent.application.use_cases.chat.messaging.message_preparation"),
    (r"from personagent\.application\.use_cases\.chat\.state", "from personagent.application.use_cases.chat.messaging.state"),
    (r"from personagent\.application\.use_cases\.chat\.turn_context", "from personagent.application.use_cases.chat.messaging.turn_context"),
    (r"from personagent\.application\.use_cases\.chat\.prompt_package", "from personagent.application.use_cases.chat.prompt.prompt_package"),
    (r"from personagent\.application\.use_cases\.chat\.prompt_surfaces", "from personagent.application.use_cases.chat.prompt.prompt_surfaces"),
    (r"from personagent\.application\.use_cases\.chat\.stream_normalization", "from personagent.application.use_cases.chat.streaming.normalization"),
    (r"from personagent\.application\.use_cases\.chat\.tool_context_builder", "from personagent.application.use_cases.chat.tooling.tool_context_builder"),
    (r"from personagent\.application\.use_cases\.chat\.tool_results", "from personagent.application.use_cases.chat.tooling.tool_results"),
    (r"from personagent\.application\.use_cases\.chat\.tool_runtime", "from personagent.application.use_cases.chat.tooling.tool_runtime"),

    # application/team_chat/
    (r"from personagent\.application\.team_chat\.blackboard_claim_graph", "from personagent.application.team_chat.blackboard.claim_graph"),
    (r"from personagent\.application\.team_chat\.blackboard_json_parsing", "from personagent.application.team_chat.blackboard.json_parsing"),
    (r"from personagent\.application\.team_chat\.blackboard_scoring", "from personagent.application.team_chat.blackboard.scoring"),
    (r"from personagent\.application\.team_chat\.blackboard", "from personagent.application.team_chat.blackboard.core"),
    (r"from personagent\.application\.team_chat\.consensus_phase", "from personagent.application.team_chat.phases.consensus"),
    (r"from personagent\.application\.team_chat\.coordinator_phase", "from personagent.application.team_chat.phases.coordinator"),
    (r"from personagent\.application\.team_chat\.final_synthesis", "from personagent.application.team_chat.phases.final_synthesis"),
    (r"from personagent\.application\.team_chat\.orchestrator", "from personagent.application.team_chat.orchestration.orchestrator"),
    (r"from personagent\.application\.team_chat\.agent_turn_runner", "from personagent.application.team_chat.orchestration.agent_turn_runner"),

    # application/services/
    (r"from personagent\.application\.services\.browser_action_arbiter", "from personagent.application.services.insights.browser_action_arbiter"),
    (r"from personagent\.application\.services\.next_step", "from personagent.application.services.insights.next_step"),
    (r"from personagent\.application\.services\.project_snapshot", "from personagent.application.services.insights.project_snapshot"),
    (r"from personagent\.application\.services\.conversation_panel_data", "from personagent.application.services.session.conversation_panel_data"),
    (r"from personagent\.application\.services\.operational_memory_queue", "from personagent.application.services.session.operational_memory_queue"),
    (r"from personagent\.application\.services\.panel_utils", "from personagent.application.services.session.panel_utils"),
    (r"from personagent\.application\.services\.session_memory", "from personagent.application.services.session.session_memory"),
    (r"from personagent\.application\.services\.session_panel", "from personagent.application.services.session.session_panel"),

    # infrastructure/browser/
    (r"from personagent\.infrastructure\.browser\.cdp_client", "from personagent.infrastructure.browser.cdp.client"),
    (r"from personagent\.infrastructure\.browser\.console", "from personagent.infrastructure.browser.cdp.console"),
    (r"from personagent\.infrastructure\.browser\.element_helpers", "from personagent.infrastructure.browser.cdp.element_helpers"),
    (r"from personagent\.infrastructure\.browser\.page_cache", "from personagent.infrastructure.browser.page.cache"),
    (r"from personagent\.infrastructure\.browser\.page_helpers", "from personagent.infrastructure.browser.page.helpers"),
    (r"from personagent\.infrastructure\.browser\.page_lifecycle", "from personagent.infrastructure.browser.page.lifecycle"),
    (r"from personagent\.infrastructure\.browser\.opened_pages", "from personagent.infrastructure.browser.page.opened_pages"),
    (r"from personagent\.infrastructure\.browser\.capture_scripts", "from personagent.infrastructure.browser.scripts.capture"),
    (r"from personagent\.infrastructure\.browser\.content_cleanup", "from personagent.infrastructure.browser.scripts.content_cleanup"),
    (r"from personagent\.infrastructure\.browser\.content_scripts", "from personagent.infrastructure.browser.scripts.content"),
    (r"from personagent\.infrastructure\.browser\.search_cache", "from personagent.infrastructure.browser.search.cache"),
    (r"from personagent\.infrastructure\.browser\.url_utils", "from personagent.infrastructure.browser.search.url_utils"),
    (r"from personagent\.infrastructure\.browser\.block_detection", "from personagent.infrastructure.browser.snapshot.block_detection"),
    (r"from personagent\.infrastructure\.browser\.snapshot_elements", "from personagent.infrastructure.browser.snapshot.elements"),
    (r"from personagent\.infrastructure\.browser\.snapshot_pipeline", "from personagent.infrastructure.browser.snapshot.pipeline"),
    (r"from personagent\.infrastructure\.browser\.snapshot_scripts", "from personagent.infrastructure.browser.snapshot.scripts"),
    (r"from personagent\.infrastructure\.browser\.snapshot_styles", "from personagent.infrastructure.browser.snapshot.styles"),
    (r"from personagent\.infrastructure\.browser\.snapshot_tabs", "from personagent.infrastructure.browser.snapshot.tabs"),
    (r"from personagent\.infrastructure\.browser\.snapshot(?![_])", "from personagent.infrastructure.browser.snapshot.snapshot"),

    # infrastructure/llm/
    (r"from personagent\.infrastructure\.llm\.codex_auth", "from personagent.infrastructure.llm.codex.auth"),
    (r"from personagent\.infrastructure\.llm\.codex_models", "from personagent.infrastructure.llm.codex.models"),
    (r"from personagent\.infrastructure\.llm\.codex_payload", "from personagent.infrastructure.llm.codex.payload"),
    (r"from personagent\.infrastructure\.llm\.codex_streaming", "from personagent.infrastructure.llm.codex.streaming"),
    (r"from personagent\.infrastructure\.llm\.codex_subscription_adapter", "from personagent.infrastructure.llm.codex.subscription_adapter"),
    (r"from personagent\.infrastructure\.llm\.kimi_auth", "from personagent.infrastructure.llm.kimi.auth"),
    (r"from personagent\.infrastructure\.llm\.kimi_coding_adapter", "from personagent.infrastructure.llm.kimi.coding_adapter"),
    (r"from personagent\.infrastructure\.llm\.kimi_history", "from personagent.infrastructure.llm.kimi.history"),
    (r"from personagent\.infrastructure\.llm\.kimi_payload", "from personagent.infrastructure.llm.kimi.payload"),
    (r"from personagent\.infrastructure\.llm\.kimi_stream", "from personagent.infrastructure.llm.kimi.stream"),
    (r"from personagent\.infrastructure\.llm\.embedding_adapter", "from personagent.infrastructure.llm.shared.embedding_adapter"),
    (r"from personagent\.infrastructure\.llm\.openai_compatible_parser", "from personagent.infrastructure.llm.shared.openai_compatible_parser"),
    (r"from personagent\.infrastructure\.llm\.process_manager", "from personagent.infrastructure.llm.shared.process_manager"),

    # infrastructure/tools/
    (r"from personagent\.infrastructure\.tools\.agent_tools", "from personagent.infrastructure.tools.agent.agent_tools"),
    (r"from personagent\.infrastructure\.tools\.config_tools", "from personagent.infrastructure.tools.planning.config_tools"),
    (r"from personagent\.infrastructure\.tools\.discovery_tools", "from personagent.infrastructure.tools.agent.discovery_tools"),
    (r"from personagent\.infrastructure\.tools\.lsp_tools", "from personagent.infrastructure.tools.dev.lsp_tools"),
    (r"from personagent\.infrastructure\.tools\.planning_tools", "from personagent.infrastructure.tools.planning.planning_tools"),
    (r"from personagent\.infrastructure\.tools\.task_tools", "from personagent.infrastructure.tools.agent.task_tools"),
    (r"from personagent\.infrastructure\.tools\.user_interaction_tools", "from personagent.infrastructure.tools.interaction.user_interaction_tools"),
    (r"from personagent\.infrastructure\.tools\.web_tools", "from personagent.infrastructure.tools.interaction.web_tools"),
    (r"from personagent\.infrastructure\.tools\.worktree_tools", "from personagent.infrastructure.tools.dev.worktree_tools"),

    # adapters/api/routes/sessions/
    (r"from personagent\.adapters\.api\.routes\.sessions\.browser_interaction", "from personagent.adapters.api.routes.sessions.browser.interaction"),
    (r"from personagent\.adapters\.api\.routes\.sessions\.browser_viewport", "from personagent.adapters.api.routes.sessions.browser.viewport"),
    (r"from personagent\.adapters\.api\.routes\.sessions\._helpers", "from personagent.adapters.api.routes.sessions.panel.helpers"),
    (r"from personagent\.adapters\.api\.routes\.sessions\.models", "from personagent.adapters.api.routes.sessions.panel.models"),
    (r"from personagent\.adapters\.api\.routes\.sessions\.panel", "from personagent.adapters.api.routes.sessions.panel.panel"),
    (r"from personagent\.adapters\.api\.routes\.sessions\.cooperation", "from personagent.adapters.api.routes.sessions.workspace.cooperation"),
    (r"from personagent\.adapters\.api\.routes\.sessions\.workspace_data", "from personagent.adapters.api.routes.sessions.workspace.data"),
    (r"from personagent\.adapters\.api\.routes\.sessions\._workspace_infra", "from personagent.adapters.api.routes.sessions.workspace.infra"),

    # adapters/composition/
    (r"from personagent\.adapters\.composition\.di_container", "from personagent.adapters.composition"),
    (r"from personagent\.adapters\.composition\.container", "from personagent.adapters.composition"),

    # domain
    (r"from personagent\.domain\.models\.conversation", "from personagent.domain.conversation.models"),
    (r"from personagent\.domain\.models\.inference_result", "from personagent.domain.llm_backend.models"),
    (r"from personagent\.domain\.models\.model_config", "from personagent.domain.llm_backend.models"),
    (r"from personagent\.domain\.models\.tenancy", "from personagent.domain.conversation.tenancy"),
    (r"from personagent\.domain\.repositories\.conversation_repository", "from personagent.domain.conversation.repositories"),
    (r"from personagent\.domain\.repositories\.llm_backend_repository", "from personagent.domain.llm_backend.repositories"),
]


def rewrite_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    modified = original
    for pattern, replacement in REPLACEMENTS:
        modified = re.sub(pattern, replacement, modified)
    if modified != original:
        path.write_text(modified, encoding="utf-8")
        return True
    return False


def main():
    changed = 0
    for root in [SRC_ROOT, TEST_ROOT]:
        if not root.exists():
            print(f"Warning: {root} does not exist, skipping")
            continue
        for py_file in root.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            if rewrite_file(py_file):
                changed += 1
                rel = py_file.relative_to(PROJECT_ROOT)
                print(f"  Rewrote: {rel}")

    print(f"\nTotal files changed: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
