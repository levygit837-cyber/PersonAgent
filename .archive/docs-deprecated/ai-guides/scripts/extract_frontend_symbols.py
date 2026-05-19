#!/usr/bin/env python3
"""Extract exported symbols from PersonAgent frontend for AI documentation inventory.

Usage:
    cd /home/levybonito/PersonAgent
    python3 docs/ai-guides/scripts/extract_frontend_symbols.py

Output:
    docs/ai-guides/_inventory/frontend_symbols.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/home/levybonito/PersonAgent")
FRONTEND_SRC = PROJECT_ROOT / "@desktop-electron" / "src"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "ai-guides" / "_inventory" / "frontend_symbols.json"

_EXPORT_RE = re.compile(
    r"^(?:export\s+)?(?:const|let|var|function|class|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
_EXPORT_DEFAULT_RE = re.compile(r"^export\s+default\s+(?:function|class)?\s*([A-Za-z_][A-Za-z0-9_]*)?")
_EXPORT_NAMED_RE = re.compile(r"^export\s+\{([^}]+)\}")


def _clean_name(name: str) -> str:
    return name.strip().split("as")[0].split(":")[0].split("<")[0].strip()


def parse_ts_file(path: Path) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return symbols

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        m = _EXPORT_RE.match(stripped)
        if m:
            name = m.group(1)
            kind = "const" if "const" in stripped else "let" if "let" in stripped else "var" if "var" in stripped else "function" if "function" in stripped else "class" if "class" in stripped else "interface" if "interface" in stripped else "type" if "type" in stripped else "enum"
            symbols.append({
                "name": name,
                "type": kind,
                "line": lineno,
                "file": str(path.relative_to(PROJECT_ROOT)),
                "is_exported": "export" in stripped,
            })
            continue

        m = _EXPORT_DEFAULT_RE.match(stripped)
        if m:
            name = m.group(1) or f"default_export_{lineno}"
            kind = "default_export"
            symbols.append({
                "name": name,
                "type": kind,
                "line": lineno,
                "file": str(path.relative_to(PROJECT_ROOT)),
                "is_exported": True,
            })
            continue

        m = _EXPORT_NAMED_RE.match(stripped)
        if m:
            for raw in m.group(1).split(","):
                name = _clean_name(raw)
                if name:
                    symbols.append({
                        "name": name,
                        "type": "named_export",
                        "line": lineno,
                        "file": str(path.relative_to(PROJECT_ROOT)),
                        "is_exported": True,
                    })

    return symbols


def main() -> None:
    all_symbols: list[dict[str, Any]] = []
    for path in sorted(FRONTEND_SRC.rglob("*.ts")):
        if ".test." in path.name:
            continue
        symbols = parse_ts_file(path)
        all_symbols.extend(symbols)
    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        if ".test." in path.name:
            continue
        symbols = parse_ts_file(path)
        all_symbols.extend(symbols)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(all_symbols, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Extracted {len(all_symbols)} symbols to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
