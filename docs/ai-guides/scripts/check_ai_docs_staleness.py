#!/usr/bin/env python3
"""Detecta referências stale: arquivo existe mas a linha mudou.

Usage:
    cd /home/levybonito/PersonAgent
    python3 docs/ai-guides/scripts/check_ai_docs_staleness.py

Verifica se o símbolo esperado ainda está na linha referenciada,
usando o inventário como fonte de verdade.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/levybonito/PersonAgent")
DOCS_DIR = PROJECT_ROOT / "docs" / "ai-guides"
BACKEND_SYMBOLS = PROJECT_ROOT / "docs" / "ai-guides" / "_inventory" / "backend_symbols.json"

# Padrão: `ClassName.method_name` @ `file.py:line` ou @ `file.py:line`
REF_RE = re.compile(
    r"[`@]\s*([A-Za-z0-9_@/.-]+\.py):(\d+)(?:-(\d+))?"
)


def load_symbols() -> dict[str, list[dict]]:
    raw = json.loads(BACKEND_SYMBOLS.read_text(encoding="utf-8"))
    # Indexar por (file, line) — incluir tanto caminho completo quanto basename
    by_file_line: dict[str, list[dict]] = {}
    for sym in raw:
        key = f"{sym['file']}:{sym['line']}"
        by_file_line.setdefault(key, []).append(sym)
        # Também indexar por basename para referências curtas
        basename = Path(sym['file']).name
        key_short = f"{basename}:{sym['line']}"
        by_file_line.setdefault(key_short, []).append(sym)
        # E por caminho relativo ao backend (application/services/...)
        rel = sym['file']
        if rel.startswith('@backend/src/personagent/'):
            rel_backend = rel[len('@backend/src/personagent/'):]
            key_backend = f"{rel_backend}:{sym['line']}"
            by_file_line.setdefault(key_backend, []).append(sym)
    return by_file_line


def find_all_md_files() -> list[Path]:
    return list(DOCS_DIR.rglob("*.md"))


def extract_refs(content: str) -> list[tuple[str, int, int | None, str]]:
    refs: list[tuple[str, int, int | None, str]] = []
    lines = content.splitlines()
    for lineno, line in enumerate(lines, 1):
        for m in REF_RE.finditer(line):
            file_ref = m.group(1)
            start_line = int(m.group(2))
            end_line = int(m.group(3)) if m.group(3) else None
            refs.append((file_ref, start_line, end_line, f"line {lineno}: {line.strip()[:80]}"))
    return refs


def check_stale(
    symbols_by_key: dict[str, list[dict]],
    file_ref: str,
    start_line: int,
    end_line: int | None,
) -> tuple[bool, str]:
    key = f"{file_ref}:{start_line}"
    syms = symbols_by_key.get(key, [])
    if not syms:
        # Pode ser uma linha dentro de um método - verificar se há símbolo próximo
        for offset in range(-3, 4):
            alt_key = f"{file_ref}:{start_line + offset}"
            if alt_key in symbols_by_key:
                return True, f"símbolo real está na linha {start_line + offset} (delta={offset})"
        return False, f"nenhum símbolo encontrado na linha {start_line}"
    # Se há símbolo, verificar se end_line bate (se fornecido)
    if end_line is not None and len(syms) == 1:
        actual_end = syms[0].get("end_line")
        if actual_end and actual_end != end_line:
            return True, f"end_line mudou: docs dizem {end_line}, atual é {actual_end}"
    return True, f"OK ({len(syms)} símbolo(s))"


def main() -> int:
    symbols_by_key = load_symbols()
    md_files = find_all_md_files()
    stale: list[tuple[Path, str, int, str]] = []
    total = 0

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        refs = extract_refs(content)
        for file_ref, start_line, end_line, context in refs:
            total += 1
            ok, msg = check_stale(symbols_by_key, file_ref, start_line, end_line)
            if not ok or "mudo" in msg:
                stale.append((md_file, f"{file_ref}:{start_line}", msg, context))

    print(f"Verificados {total} refs em {len(md_files)} arquivos.")
    if stale:
        print(f"\n{len(stale)} refs desatualizadas:")
        for md_file, ref, msg, context in stale:
            rel_md = md_file.relative_to(PROJECT_ROOT)
            print(f"  [{rel_md}] {ref} → {msg}")
            print(f"    Contexto: {context}")
        return 1
    print("Nenhuma referência stale detectada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
