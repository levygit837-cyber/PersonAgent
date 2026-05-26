#!/bin/bash
# codedb-startup hook for KimiCode
# Reads .codedb/reader.md and injects it into the session context on start
# Also verifies codedb MCP is available

echo "<!-- injected by codedb-startup hook -->"
echo ""

# Check if reader.md exists
if [ -f ".codedb/reader.md" ]; then
    echo "**Reader.md loaded:** The project has a codedb reader.md at .codedb/reader.md. Use codedb_context for one-shot orientation — it auto-prepends this file when the hash matches."
    echo ""
fi

# Check codedb MCP availability
if command -v codedb &> /dev/null; then
    echo "**codedb MCP available.** Prefer codedb MCP tools (codedb_context, codedb_outline, codedb_symbol, codedb_search, codedb_callers, codedb_deps, codedb_hot) over grep/ripgrep for code exploration. Only use grep/ripgrep as a fallback."
    echo ""
fi

# Project-specific conventions
echo "**Project conventions:** Clean Architecture (domain → app → infra → interfaces). Python: ruff + mypy + pytest. TypeScript: strict mode, const, object params for 2+ args. Tests: @backend/tests/ or @desktop-electron/src/**/*.test.tsx. Never modify .worktrees/."
