#!/usr/bin/env python3
"""Valida que referências de arquivo:linha nos AI-guides ainda existem.

Usage:
    cd /home/levybonito/PersonAgent
    python3 docs/ai-guides/scripts/validate_ai_docs.py

Exit code 0 se tudo OK, 1 se houver falhas.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/home/levybonito/PersonAgent")
DOCS_DIR = PROJECT_ROOT / "docs" / "ai-guides"

# Padrões de referência: `file.py:123` ou @ `file.py:123` ou `file.py:123-456`
REF_RE = re.compile(r"[`@]\s*([A-Za-z0-9_/@.-]+\.py):(\d+)")


def find_all_md_files() -> list[Path]:
    return list(DOCS_DIR.rglob("*.md"))


def extract_refs(content: str) -> list[tuple[str, int, str]]:
    """Retorna lista de (arquivo, linha, snippet_contexto)."""
    refs: list[tuple[str, int, str]] = []
    lines = content.splitlines()
    for lineno, line in enumerate(lines, 1):
        for m in REF_RE.finditer(line):
            file_ref = m.group(1)
            line_no = int(m.group(2))
            refs.append((file_ref, line_no, f"line {lineno}: {line.strip()[:80]}"))
    return refs


def resolve_file(file_ref: str) -> Path | None:
    """Tenta resolver caminho relativo ou busca no projeto se for nome curto."""
    # Tentativa 1: caminho relativo ao projeto
    target = PROJECT_ROOT / file_ref
    if target.exists():
        return target
    # Tentativa 2: buscar no backend
    backend = PROJECT_ROOT / "@backend" / "src" / "personagent"
    candidates = list(backend.rglob(file_ref))
    if candidates:
        return candidates[0]
    return None


def validate_ref(file_ref: str, line_no: int) -> tuple[bool, str]:
    target = resolve_file(file_ref)
    if target is None:
        return False, f"arquivo não encontrado: {file_ref}"
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return False, f"erro lendo arquivo: {exc}"
    if line_no < 1 or line_no > len(lines):
        return False, f"linha {line_no} fora do range (1-{len(lines)})"
    return True, f"OK"


def main() -> int:
    md_files = find_all_md_files()
    failures: list[tuple[Path, str, int, str, str]] = []
    total = 0

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        refs = extract_refs(content)
        for file_ref, line_no, context in refs:
            total += 1
            ok, msg = validate_ref(file_ref, line_no)
            if not ok:
                failures.append((md_file, file_ref, line_no, context, msg))

    print(f"Validados {total} referências em {len(md_files)} arquivos.")
    if failures:
        print(f"\n{len(failures)} FALHAS:")
        for md_file, file_ref, line_no, context, msg in failures:
            rel_md = md_file.relative_to(PROJECT_ROOT)
            print(f"  [{rel_md}] {file_ref}:{line_no} → {msg}")
            print(f"    Contexto: {context}")
        return 1
    print("Todas as referências são válidas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
