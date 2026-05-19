#!/usr/bin/env python3
"""Extract public symbols from PersonAgent backend for AI documentation inventory.

Usage:
    cd /home/levybonito/PersonAgent
    python docs/ai-guides/scripts/extract_backend_symbols.py

Output:
    docs/ai-guides/_inventory/backend_symbols.json
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/home/levybonito/PersonAgent")
BACKEND_SRC = PROJECT_ROOT / "@backend" / "src" / "personagent"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "ai-guides" / "_inventory" / "backend_symbols.json"


def get_lineno(node: ast.AST) -> int:
    return getattr(node, "lineno", 0)


def get_end_lineno(node: ast.AST) -> int:
    return getattr(node, "end_lineno", 0)


def extract_decorators(node: ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef) -> list[str]:
    result: list[str] = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            name = _expr_to_str(dec.func)
            result.append(name + "()")
        else:
            result.append(_expr_to_str(dec))
    return result


def _expr_to_str(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _expr_to_str(node.value) + "." + node.attr
    if isinstance(node, ast.Subscript):
        return _expr_to_str(node.value) + "[...]"
    return "<expr>"


def _get_bases(node: ast.ClassDef) -> list[str]:
    return [_expr_to_str(base) for base in node.bases]


def _get_returns(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if node.returns is None:
        return None
    return ast.unparse(node.returns)


def _get_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = []
    for arg in node.args.posonlyargs:
        args.append(_arg_str(arg))
    if node.args.posonlyargs and node.args.args:
        args.append("/")
    for arg in node.args.args:
        args.append(_arg_str(arg))
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    for arg in node.args.kwonlyargs:
        args.append(_arg_str(arg))
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    sig = f"({', '.join(args)})"
    ret = _get_returns(node)
    if ret:
        sig += f" -> {ret}"
    return sig


def _arg_str(node: ast.arg) -> str:
    ann = f": {ast.unparse(node.annotation)}" if node.annotation else ""
    default = ""
    return f"{node.arg}{ann}"


def _is_public(name: str) -> bool:
    if name.startswith("__") and not name.endswith("__"):
        return False
    return not name.startswith("_")


def _is_test_file(path: Path) -> bool:
    return "test" in path.name or path.name.endswith("_test.py")


def _is_constant_assign(node: ast.Assign) -> bool:
    for target in node.targets:
        if isinstance(target, ast.Name) and target.id.isupper():
            return True
    return False


def parse_file(path: Path) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return symbols

    module_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                module_imports.append(f"{module}.{alias.name}")

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_public(node.name):
            methods: list[dict[str, Any]] = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        "name": item.name,
                        "type": "async_method" if isinstance(item, ast.AsyncFunctionDef) else "method",
                        "line": get_lineno(item),
                        "end_line": get_end_lineno(item),
                        "decorators": extract_decorators(item),
                        "signature": _get_signature(item),
                        "is_public": _is_public(item.name),
                        "docstring": ast.get_docstring(item),
                    })
            symbols.append({
                "name": node.name,
                "type": "class",
                "line": get_lineno(node),
                "end_line": get_end_lineno(node),
                "file": str(path.relative_to(PROJECT_ROOT)),
                "bases": _get_bases(node),
                "decorators": extract_decorators(node),
                "docstring": ast.get_docstring(node),
                "methods": methods,
                "is_public": True,
            })
            # Emit flat symbols for methods so the inventory can resolve them
            for m in methods:
                symbols.append({
                    "name": f"{node.name}.{m['name']}",
                    "type": m["type"],
                    "line": m["line"],
                    "end_line": m["end_line"],
                    "file": str(path.relative_to(PROJECT_ROOT)),
                    "decorators": m["decorators"],
                    "signature": m["signature"],
                    "docstring": m["docstring"],
                    "is_public": m["is_public"],
                    "parent_class": node.name,
                })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(node.name):
            symbols.append({
                "name": node.name,
                "type": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                "line": get_lineno(node),
                "end_line": get_end_lineno(node),
                "file": str(path.relative_to(PROJECT_ROOT)),
                "decorators": extract_decorators(node),
                "signature": _get_signature(node),
                "docstring": ast.get_docstring(node),
                "is_public": True,
            })
        elif isinstance(node, ast.Assign) and _is_constant_assign(node):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    symbols.append({
                        "name": target.id,
                        "type": "constant",
                        "line": get_lineno(node),
                        "end_line": get_end_lineno(node),
                        "file": str(path.relative_to(PROJECT_ROOT)),
                        "value": ast.unparse(node.value) if node.value else None,
                        "is_public": True,
                    })

    return symbols


def main() -> None:
    all_symbols: list[dict[str, Any]] = []
    for path in sorted(BACKEND_SRC.rglob("*.py")):
        if _is_test_file(path):
            continue
        symbols = parse_file(path)
        all_symbols.extend(symbols)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(all_symbols, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Extracted {len(all_symbols)} symbols to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
