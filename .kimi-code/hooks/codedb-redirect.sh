#!/bin/bash
# codedb redirect hook for KimiCode
# Triggers on SessionStart to remind about codedb, and on PreToolUse for grep/rg
# The hook receives JSON on stdin with hook_event_name, tool_name, cwd, etc.

set -e

read -r input
hook_event=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('hook_event_name',''))" 2>/dev/null || echo "")

case "$hook_event" in
    SessionStart)
        # Output is captured by KimiCode as a SessionStart hook result
        cat << 'EOF'
CRITICAL: Always prefer codedb MCP tools over grep/ripgrep for code exploration:
- codedb_context for one-shot orientation (replaces 3-5 search calls)
- codedb_outline before reading any file
- codedb_symbol for exact definitions
- codedb_search for substring/regex search
- codedb_callers before refactoring
- codedb_deps for dependency graphs
- codedb_hot for recent changes
- Only use grep/ripgrep as a fallback

Project: Clean Architecture. Python ruff+mypy+pytest. TS strict mode.
Tests: @backend/tests/ or @desktop-electron/src/**/*.test.tsx.
EOF
        ;;
    PreToolUse)
        tool_name=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
        case "$tool_name" in
            Grep|Ripgrep|Search)
                # Remind to use codedb first, but don't block
                echo "Consider using codedb_search or codedb_word instead — 500x faster on indexed projects." >&2
                ;;
        esac
        ;;
esac

exit 0
