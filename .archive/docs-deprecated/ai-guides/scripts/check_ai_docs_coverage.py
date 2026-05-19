#!/usr/bin/env python3
"""Verifica cobertura de subsistemas documentados vs subsistemas existentes.

Usage:
    cd /home/levybonito/PersonAgent
    python3 docs/ai-guides/scripts/check_ai_docs_coverage.py

Compara manifest.json com o inventário de símbolos para detectar subsistemas
sem guide documentado.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/levybonito/PersonAgent")
MANIFEST = PROJECT_ROOT / "docs" / "ai-guides" / "manifest.json"
BACKEND_SYMBOLS = PROJECT_ROOT / "docs" / "ai-guides" / "_inventory" / "backend_symbols.json"

# Subsistemas conhecidos que devem ter guides
EXPECTED_SUBSYSTEMS = {
    "browser_action_arbiter",
    "browser_cooperation",
    "build_context",
    "command_registry",
    "llm_adapters",
    "memory_jobs",
    "next_step_suggestion",
    "operational_memory_queue",
    "qa_indexer",
    "session_memory",
    "session_title",
    "state_manager",
    "tools_schema_cache",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    manifest = load_json(MANIFEST)
    symbols = load_json(BACKEND_SYMBOLS)

    documented = set(manifest.get("subsystems", {}).keys())
    missing = EXPECTED_SUBSYSTEMS - documented
    extra = documented - EXPECTED_SUBSYSTEMS

    print(f"Subsistemas esperados: {len(EXPECTED_SUBSYSTEMS)}")
    print(f"Subsistemas documentados: {len(documented)}")
    print(f"Cobertura: {len(documented & EXPECTED_SUBSYSTEMS)}/{len(EXPECTED_SUBSYSTEMS)}")

    if missing:
        print(f"\nSubsistemas SEM guide ({len(missing)}):")
        for s in sorted(missing):
            print(f"  - {s}")

    if extra:
        print(f"\nSubsistemas extras (não na lista de esperados) ({len(extra)}):")
        for s in sorted(extra):
            print(f"  - {s}")

    # Verificar symbols sem referência em nenhum guide
    symbol_names = {s["name"] for s in symbols if s.get("is_public")}
    referenced_symbols: set[str] = set()
    for ss_data in manifest.get("subsystems", {}).values():
        referenced_symbols.update(ss_data.get("symbols", []))

    orphan_symbols = symbol_names - referenced_symbols
    # Filtrar apenas classes/funções importantes (não constantes pequenas)
    important_orphans = {s for s in orphan_symbols if len(s) > 3 and s[0].isupper()}

    if important_orphans:
        print(f"\nSímbolos importantes não referenciados ({len(important_orphans)}):")
        for s in sorted(important_orphans)[:20]:
            print(f"  - {s}")
        if len(important_orphans) > 20:
            print(f"  ... e mais {len(important_orphans) - 20}")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
