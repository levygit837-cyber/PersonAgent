"""Static code indexer for Python/FastAPI backends."""

from __future__ import annotations

import ast
import hashlib
import inspect
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute

from personagent.application.qa.contracts import (
    CodeEdgeData,
    CodeEdgeKind,
    CodeNodeData,
    CodeNodeKind,
    QACodeGraph,
)

IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


@dataclass
class _ModuleInfo:
    path: Path
    rel_path: str
    tree: ast.Module
    imports: set[str] = field(default_factory=set)
    imported_symbols: set[str] = field(default_factory=set)


class PythonCodeIndexer:
    """Build a best-effort static graph for Python/FastAPI code."""

    def __init__(self, repo_root: Path, *, app: FastAPI | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.app = app
        self._nodes: dict[str, CodeNodeData] = {}
        self._edges: dict[str, CodeEdgeData] = {}
        self._function_nodes_by_name: dict[str, list[str]] = defaultdict(list)
        self._class_nodes_by_name: dict[str, list[str]] = defaultdict(list)
        self._file_nodes_by_rel_path: dict[str, str] = {}

    def build(self, *, include_tests: bool = True) -> QACodeGraph:
        """Build the static code graph."""
        modules = self._parse_modules(include_tests=include_tests)
        for module in modules:
            self._index_file_node(module)
        for module in modules:
            self._index_module(module)
        for module in modules:
            self._index_import_edges(module)
        self._link_static_calls()
        if self.app is not None:
            self._index_fastapi_runtime_routes()

        nodes = sorted(self._nodes.values(), key=lambda node: (node.file_path or "", node.start_line or 0, node.id))
        edges = sorted(self._edges.values(), key=lambda edge: edge.id)
        return QACodeGraph(
            nodes=nodes,
            edges=edges,
            stats={
                "repo_root": str(self.repo_root),
                "file_count": sum(1 for node in nodes if node.kind == CodeNodeKind.FILE),
                "node_count": len(nodes),
                "edge_count": len(edges),
                "endpoint_count": sum(1 for node in nodes if node.kind == CodeNodeKind.ENDPOINT),
            },
        )

    def _parse_modules(self, *, include_tests: bool) -> list[_ModuleInfo]:
        modules: list[_ModuleInfo] = []
        for root in self._scan_roots(include_tests=include_tests):
            for path in sorted(root.rglob("*.py")):
                if any(part in IGNORED_DIRS for part in path.parts):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                    tree = ast.parse(text)
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                rel_path = _safe_relative(path, self.repo_root)
                info = _ModuleInfo(path=path, rel_path=rel_path, tree=tree)
                self._collect_imports(info)
                modules.append(info)
        return modules

    def _scan_roots(self, *, include_tests: bool) -> list[Path]:
        candidates = [
            self.repo_root / "@backend" / "src" / "personagent",
            self.repo_root / "src" / "personagent",
            self.repo_root / "personagent",
        ]
        roots = [candidate for candidate in candidates if candidate.exists()]
        if not roots:
            roots = [self.repo_root]
        if include_tests:
            for candidate in (self.repo_root / "@backend" / "tests", self.repo_root / "tests"):
                if candidate.exists():
                    roots.append(candidate)
        return roots

    def _index_file_node(self, module: _ModuleInfo) -> None:
        node = CodeNodeData(
            id=_node_id("file", module.rel_path),
            kind=CodeNodeKind.FILE,
            name=module.rel_path,
            file_path=module.rel_path,
            metadata={"imports": sorted(module.imports)},
        )
        self._add_node(node)
        self._file_nodes_by_rel_path[module.rel_path] = node.id

    def _index_module(self, module: _ModuleInfo) -> None:
        router_prefix = _router_prefix(module.tree)
        file_node_id = self._file_nodes_by_rel_path[module.rel_path]
        for node in module.tree.body:
            if isinstance(node, ast.ClassDef):
                class_node = self._class_node(module, node)
                self._add_node(class_node)
                self._class_nodes_by_name[node.name].append(class_node.id)
                self._add_edge(file_node_id, class_node.id, CodeEdgeKind.CONTAINS)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                self._index_function(module, node, router_prefix, file_node_id)

    def _index_function(
        self,
        module: _ModuleInfo,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        router_prefix: str,
        file_node_id: str,
    ) -> None:
        routes = _route_decorators(node, router_prefix)
        kind = _function_kind(module.rel_path, node.name, has_route=bool(routes))
        function_node = CodeNodeData(
            id=_node_id("function", module.rel_path, node.name, str(node.lineno)),
            kind=kind,
            name=node.name,
            file_path=module.rel_path,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            metadata={
                "async": isinstance(node, ast.AsyncFunctionDef),
                "decorators": [_decorator_name(dec) for dec in node.decorator_list],
                "calls": sorted(_call_names(node)),
                "depends": sorted(_depends_calls(node)),
            },
        )
        self._add_node(function_node)
        self._function_nodes_by_name[node.name].append(function_node.id)
        self._add_edge(file_node_id, function_node.id, CodeEdgeKind.CONTAINS)

        for method, full_path in routes:
            endpoint_node = CodeNodeData(
                id=_node_id("endpoint", method, full_path, module.rel_path, node.name),
                kind=CodeNodeKind.ENDPOINT,
                name=f"{method} {full_path}",
                file_path=module.rel_path,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                metadata={
                    "method": method,
                    "path": full_path,
                    "handler": node.name,
                    "source": "ast",
                },
            )
            self._add_node(endpoint_node)
            self._add_edge(file_node_id, endpoint_node.id, CodeEdgeKind.CONTAINS)
            self._add_edge(endpoint_node.id, function_node.id, CodeEdgeKind.ROUTES_TO)

        for sql_call in _sql_calls(node):
            sql_node = CodeNodeData(
                id=_node_id("sql", module.rel_path, node.name, str(sql_call[0]), sql_call[1]),
                kind=CodeNodeKind.SQL,
                name=sql_call[1],
                file_path=module.rel_path,
                start_line=sql_call[0],
                end_line=sql_call[0],
                metadata={"function": node.name},
            )
            self._add_node(sql_node)
            self._add_edge(function_node.id, sql_node.id, CodeEdgeKind.EXECUTES_SQL)

        for http_call in _http_calls(node):
            http_node = CodeNodeData(
                id=_node_id("external_http", module.rel_path, node.name, str(http_call[0]), http_call[1]),
                kind=CodeNodeKind.EXTERNAL_HTTP,
                name=http_call[1],
                file_path=module.rel_path,
                start_line=http_call[0],
                end_line=http_call[0],
                metadata={"function": node.name},
            )
            self._add_node(http_node)
            self._add_edge(function_node.id, http_node.id, CodeEdgeKind.CALLS_EXTERNAL_HTTP)

        for queue_call in _queue_calls(node):
            queue_node = CodeNodeData(
                id=_node_id("queue_event", module.rel_path, node.name, str(queue_call[0]), queue_call[1]),
                kind=CodeNodeKind.QUEUE_EVENT,
                name=queue_call[1],
                file_path=module.rel_path,
                start_line=queue_call[0],
                end_line=queue_call[0],
                metadata={"function": node.name},
            )
            self._add_node(queue_node)
            self._add_edge(function_node.id, queue_node.id, CodeEdgeKind.DEPENDS_ON)

    def _class_node(self, module: _ModuleInfo, node: ast.ClassDef) -> CodeNodeData:
        bases = [_callable_name(base) for base in node.bases]
        kind = _class_kind(module.rel_path, bases)
        metadata = {"bases": bases}
        if kind == CodeNodeKind.CONFIG:
            metadata["env_aliases"] = sorted(_field_aliases(node))
        return CodeNodeData(
            id=_node_id("class", module.rel_path, node.name, str(node.lineno)),
            kind=kind,
            name=node.name,
            file_path=module.rel_path,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            metadata=metadata,
        )

    def _collect_imports(self, module: _ModuleInfo) -> None:
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module.imports.add(alias.name)
                    module.imported_symbols.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module.imports.add(node.module)
                for alias in node.names:
                    module.imported_symbols.add(alias.asname or alias.name)
                    if node.module and alias.name != "*":
                        module.imports.add(f"{node.module}.{alias.name}")

    def _index_import_edges(self, module: _ModuleInfo) -> None:
        source_id = self._file_nodes_by_rel_path[module.rel_path]
        for imported_module in sorted(module.imports):
            rel_path = self._module_to_rel_path(imported_module)
            if rel_path is None:
                continue
            target_id = self._file_nodes_by_rel_path.get(rel_path)
            if target_id is not None and target_id != source_id:
                self._add_edge(source_id, target_id, CodeEdgeKind.IMPORTS, {"module": imported_module})

        if "/tests/" in f"/{module.rel_path}" or Path(module.rel_path).name.startswith("test_"):
            for imported_module in sorted(module.imports):
                rel_path = self._module_to_rel_path(imported_module)
                target_id = self._file_nodes_by_rel_path.get(rel_path or "")
                if target_id is not None:
                    self._add_edge(source_id, target_id, CodeEdgeKind.COVERED_BY_TEST, {"module": imported_module})

    def _module_to_rel_path(self, module_name: str) -> str | None:
        if not module_name.startswith("personagent"):
            return None
        relative = Path(*module_name.split("."))
        for prefix in ("@backend/src", "src", ""):
            base = self.repo_root / prefix if prefix else self.repo_root
            for candidate in (
                base / f"{relative}.py",
                base / relative / "__init__.py",
            ):
                if candidate.exists():
                    return _safe_relative(candidate, self.repo_root)
        return None

    def _link_static_calls(self) -> None:
        for node in list(self._nodes.values()):
            if node.kind not in {
                CodeNodeKind.CONTROLLER,
                CodeNodeKind.FUNCTION,
                CodeNodeKind.SERVICE,
                CodeNodeKind.REPOSITORY,
            }:
                continue
            for call in node.metadata.get("calls", []):
                target_ids = self._function_nodes_by_name.get(call) or self._class_nodes_by_name.get(call)
                if target_ids and len(target_ids) == 1:
                    self._add_edge(node.id, target_ids[0], CodeEdgeKind.CALLS_STATIC, {"call": call})

    def _index_fastapi_runtime_routes(self) -> None:
        if self.app is None:
            return
        app = self.app
        for route in app.routes:
            if isinstance(route, APIRoute):
                methods = sorted(route.methods or [])
                endpoint = route.endpoint
            elif isinstance(route, APIWebSocketRoute):
                methods = ["WEBSOCKET"]
                endpoint = route.endpoint
            else:
                continue
            source_file = inspect.getsourcefile(endpoint)
            if source_file is None:
                continue
            path = Path(source_file).resolve()
            if not _is_relative_to(path, self.repo_root):
                continue
            rel_path = _safe_relative(path, self.repo_root)
            file_node_id = self._file_nodes_by_rel_path.get(rel_path)
            if file_node_id is None:
                file_node = CodeNodeData(
                    id=_node_id("file", rel_path),
                    kind=CodeNodeKind.FILE,
                    name=rel_path,
                    file_path=rel_path,
                )
                self._add_node(file_node)
                file_node_id = file_node.id
                self._file_nodes_by_rel_path[rel_path] = file_node_id
            try:
                _, line = inspect.getsourcelines(endpoint)
            except (OSError, TypeError):
                line = None
            function_id = _node_id("function", rel_path, endpoint.__name__, str(line or 0))
            if function_id not in self._nodes:
                function_node = CodeNodeData(
                    id=function_id,
                    kind=_function_kind(rel_path, endpoint.__name__, has_route=True),
                    name=endpoint.__name__,
                    file_path=rel_path,
                    start_line=line,
                    metadata={"source": "fastapi_runtime"},
                )
                self._add_node(function_node)
                self._function_nodes_by_name[endpoint.__name__].append(function_id)
                self._add_edge(file_node_id, function_id, CodeEdgeKind.CONTAINS)
            for method in methods:
                endpoint_node = CodeNodeData(
                    id=_node_id("endpoint", method, route.path, rel_path, endpoint.__name__),
                    kind=CodeNodeKind.ENDPOINT,
                    name=f"{method} {route.path}",
                    file_path=rel_path,
                    start_line=line,
                    metadata={
                        "method": method,
                        "path": route.path,
                        "handler": endpoint.__name__,
                        "source": "fastapi_runtime",
                    },
                )
                self._add_node(endpoint_node)
                self._add_edge(file_node_id, endpoint_node.id, CodeEdgeKind.CONTAINS)
                self._add_edge(endpoint_node.id, function_id, CodeEdgeKind.ROUTES_TO)

    def _add_node(self, node: CodeNodeData) -> None:
        existing = self._nodes.get(node.id)
        if existing is None:
            self._nodes[node.id] = node
            return
        merged = existing.model_copy()
        merged.metadata = {**existing.metadata, **node.metadata}
        if merged.start_line is None:
            merged.start_line = node.start_line
        if merged.end_line is None:
            merged.end_line = node.end_line
        self._nodes[node.id] = merged

    def _add_edge(
        self,
        source_id: str,
        target_id: str,
        kind: CodeEdgeKind,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        edge = CodeEdgeData(
            id=_edge_id(source_id, target_id, kind.value, metadata or {}),
            kind=kind,
            source_id=source_id,
            target_id=target_id,
            metadata=metadata or {},
        )
        self._edges[edge.id] = edge


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


def _function_kind(rel_path: str, name: str, *, has_route: bool) -> CodeNodeKind:
    normalized = rel_path.replace("\\", "/")
    if has_route or "/interfaces/api/routes/" in f"/{normalized}":
        return CodeNodeKind.CONTROLLER
    if "middleware" in normalized:
        return CodeNodeKind.MIDDLEWARE
    if "repository" in normalized or "repositories" in normalized or "persistence" in normalized:
        return CodeNodeKind.REPOSITORY
    if "service" in normalized or "services" in normalized or "use_cases" in normalized:
        return CodeNodeKind.SERVICE
    if normalized.endswith(".py") and Path(normalized).name.startswith("test_"):
        return CodeNodeKind.TEST
    if name.startswith("test_"):
        return CodeNodeKind.TEST
    return CodeNodeKind.FUNCTION


def _class_kind(rel_path: str, bases: Iterable[str]) -> CodeNodeKind:
    normalized = rel_path.replace("\\", "/")
    base_set = set(bases)
    if "BaseModel" in base_set:
        return CodeNodeKind.SCHEMA
    if "BaseSettings" in base_set or normalized.endswith("settings.py"):
        return CodeNodeKind.CONFIG
    if normalized.endswith("models.py") or "/domain/models/" in f"/{normalized}":
        return CodeNodeKind.MODEL
    if "repository" in normalized or "repositories" in normalized or "persistence" in normalized:
        return CodeNodeKind.REPOSITORY
    if "service" in normalized or "services" in normalized:
        return CodeNodeKind.SERVICE
    return CodeNodeKind.FUNCTION


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


def _node_id(*parts: str) -> str:
    raw = "|".join(parts)
    return f"node:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


def _edge_id(source: str, target: str, kind: str, metadata: dict[str, Any]) -> str:
    raw = "|".join([source, target, kind, repr(sorted(metadata.items()))])
    return f"edge:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
