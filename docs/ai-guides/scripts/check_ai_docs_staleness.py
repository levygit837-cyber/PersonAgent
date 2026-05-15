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


def load_symbols() -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    raw = json.loads(BACKEND_SYMBOLS.read_text(encoding="utf-8"))
    # Indexar por (file, line) — incluir tanto caminho completo quanto basename
    by_file_line: dict[str, list[dict]] = {}
    # Indexar por arquivo (todos os caminhos possíveis) para busca por range
    by_file: dict[str, list[dict]] = {}
    for sym in raw:
        paths: set[str] = {sym['file']}
        basename = Path(sym['file']).name
        paths.add(basename)
        rel = sym['file']
        if rel.startswith('@backend/src/personagent/'):
            paths.add(rel[len('@backend/src/personagent/'):])

        for p in paths:
            key = f"{p}:{sym['line']}"
            by_file_line.setdefault(key, []).append(sym)
            by_file.setdefault(p, []).append(sym)
    return by_file_line, by_file


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
    symbols_by_file: dict[str, list[dict]],
    file_ref: str,
    start_line: int,
    end_line: int | None,
) -> tuple[bool, str]:
    # 1. Match exato no início de um símbolo
    key = f"{file_ref}:{start_line}"
    syms = symbols_by_key.get(key, [])
    if syms:
        if end_line is not None and len(syms) == 1:
            actual_end = syms[0].get("end_line")
            if actual_end and actual_end != end_line:
                return True, f"end_line mudou: docs dizem {end_line}, atual é {actual_end}"
        return True, f"OK ({len(syms)} símbolo(s))"

    # 2. Verificar se a linha cai dentro do range de algum símbolo no arquivo
    file_syms = symbols_by_file.get(file_ref, [])
    if file_syms:
        for sym in file_syms:
            sym_start = sym.get("line", 0)
            sym_end = sym.get("end_line", sym_start)
            if sym_start <= start_line <= sym_end:
                return True, f"OK (dentro de {sym['name']}:{sym_start}-{sym_end})"
        return False, f"nenhum símbolo cobre a linha {start_line}"

    return False, f"arquivo não encontrado no inventário: {file_ref}"


def main() -> int:
    symbols_by_key, symbols_by_file = load_symbols()
    md_files = find_all_md_files()
    stale: list[tuple[Path, str, int, str]] = []
    total = 0

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        refs = extract_refs(content)
        for file_ref, start_line, end_line, context in refs:
            total += 1
            ok, msg = check_stale(symbols_by_key, symbols_by_file, file_ref, start_line, end_line)
            if not ok:
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
