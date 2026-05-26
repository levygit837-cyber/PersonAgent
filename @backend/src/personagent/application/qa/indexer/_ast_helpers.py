"""AST analysis helpers for the code indexer."""

from __future__ import annotations

import ast


def _router_prefix(tree: ast.Module) -> str:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "router" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for keyword in node.value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value or "")
    return ""


def _route_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    router_prefix: str,
) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "router":
            continue
        method = decorator.func.attr.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"}:
            continue
        path = ""
        if decorator.args and isinstance(decorator.args[0], ast.Constant):
            path = str(decorator.args[0].value or "")
        routes.append((method, _join_paths(router_prefix, path)))
    return routes


def _join_paths(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path:
        return prefix
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _callable_name(child.func)
            if name:
                names.add(name.split(".")[-1])
    return names


def _depends_calls(node: ast.AST) -> set[str]:
    depends: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and _callable_name(child.func).endswith("Depends")
            and child.args
        ):
            depends.add(_callable_name(child.args[0]))
    return depends


def _sql_calls(node: ast.AST) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _callable_name(child.func)
            if name.split(".")[-1] in {"select", "text", "execute", "scalar", "scalars"}:
                calls.append((getattr(child, "lineno", 0), name))
    return calls


def _http_calls(node: ast.AST) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _callable_name(child.func)
            lower = name.lower()
            if "httpx" in lower or lower.endswith((".get", ".post", ".put", ".patch", ".delete", ".stream")):
                calls.append((getattr(child, "lineno", 0), name))
    return calls


def _queue_calls(node: ast.AST) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _callable_name(child.func)
            lower = name.lower()
            if any(fragment in lower for fragment in ("schedule", "enqueue", "publish", "register_handler")):
                calls.append((getattr(child, "lineno", 0), name))
    return calls


def _field_aliases(node: ast.ClassDef) -> set[str]:
    aliases: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or _callable_name(child.func).split(".")[-1] != "Field":
            continue
        for keyword in child.keywords:
            if keyword.arg == "alias" and isinstance(keyword.value, ast.Constant):
                aliases.add(str(keyword.value.value))
    return aliases


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _callable_name(node.func)
    return _callable_name(node)


def _callable_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _callable_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _callable_name(node.func)
    if isinstance(node, ast.Constant):
        return str(node.value)
    return ""
