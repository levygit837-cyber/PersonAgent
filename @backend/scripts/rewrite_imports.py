#!/usr/bin/env python3
"""Rewrite all imports after ADR-0022 structural migration.

Run AFTER all git mv operations.
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
BACKEND_ROOT = PROJECT_ROOT / "@backend"
SRC_ROOT = BACKEND_ROOT / "src" / "personagent"
TEST_ROOT = BACKEND_ROOT / "tests"

# Ordered by specificity (most specific first)
REPLACEMENTS = [
    # Layer rename: interfaces -> adapters
    (r"from personagent\.interfaces", "from personagent.adapters"),
    (r"import personagent\.interfaces", "import personagent.adapters"),

    # Generic folder renames
    (r"from personagent\.infrastructure\.config", "from personagent.infrastructure.settings"),
    (r"from personagent\.adapters\.config", "from personagent.adapters.composition"),
    (r"from personagent\.infrastructure\.tools\.browser_tools\.helpers", "from personagent.infrastructure.tools.browser.building"),

    # Flattened files
    (r"from personagent\.application\.security\.provider_data_policy", "from personagent.application.security"),
    (r"from personagent\.application\.dto\.chat_dto", "from personagent.application.dto"),
    (r"from personagent\.application\.use_cases\.context\.build_context", "from personagent.application.use_cases.build_context"),
    (r"from personagent\.adapters\.cli\.main", "from personagent.adapters.cli"),
    (r"from personagent\.infrastructure\.persistence\.memory\.filesystem_memory_repository", "from personagent.infrastructure.persistence.memory"),
    (r"from personagent\.infrastructure\.persistence\.context\.in_memory_context_repository", "from personagent.infrastructure.persistence.context"),

    # API route moves (loose files -> routes/)
    (r"from personagent\.adapters\.api\.action_approvals", "from personagent.adapters.api.routes.action_approvals"),
    (r"from personagent\.adapters\.api\.state_events", "from personagent.adapters.api.routes.state_events"),
    (r"from personagent\.adapters\.api\.workspace_grants", "from personagent.adapters.api.routes.workspace_grants"),
    (r"from personagent\.adapters\.api\.security", "from personagent.adapters.api.middleware.auth"),

    # Domain bounded context reorganizations
    (r"from personagent\.domain\.models\.conversation", "from personagent.domain.conversation.models"),
    (r"from personagent\.domain\.repositories\.conversation_repository", "from personagent.domain.conversation.repositories"),
    (r"from personagent\.domain\.models\.inference_result", "from personagent.domain.llm_backend.models"),
    (r"from personagent\.domain\.models\.model_config", "from personagent.domain.llm_backend.models"),
    (r"from personagent\.domain\.repositories\.llm_backend_repository", "from personagent.domain.llm_backend.repositories"),
    (r"from personagent\.domain\.models\.tenancy", "from personagent.domain.conversation.tenancy"),

    # Sub-package absorptions
    (r"from personagent\.application\.use_cases\.chat\.streaming_turn", "from personagent.application.use_cases.chat.streaming"),
    (r"from personagent\.application\.team_chat\.phase_loop", "from personagent.application.team_chat.phases.loop"),
    (r"from personagent\.infrastructure\.llm\.vertex_ai_adapter", "from personagent.infrastructure.llm.vertex_ai"),

    # DI container renames
    (r"from personagent\.adapters\.composition\.di_container", "from personagent.adapters.composition"),
    (r"from personagent\.adapters\.config\.di_container", "from personagent.adapters.composition"),
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
