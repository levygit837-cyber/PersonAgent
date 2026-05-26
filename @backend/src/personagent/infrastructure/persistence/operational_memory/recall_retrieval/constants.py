"""Relevance constants for recall retrieval."""

from __future__ import annotations

_RELEVANCE_STOPWORDS = {
    "a", "as", "com", "como", "de", "da", "das", "do", "dos",
    "e", "em", "foi", "na", "no", "nos", "o", "os",
    "para", "por", "qual", "quais", "que",
    "the", "to", "was", "what", "which",
}

_RELEVANCE_CANONICAL_TERMS = {
    "arquitetura": "architecture",
    "arquiteturais": "architecture",
    "arquivo": "file",
    "arquivos": "file",
    "comando": "command",
    "comandos": "command",
    "decisao": "decision",
    "decisoes": "decision",
    "decisions": "decision",
    "dependencia": "dependency",
    "dependencias": "dependency",
    "duplicados": "duplicate",
    "duplicar": "duplicate",
    "erros": "error",
    "ferramenta": "tool",
    "ferramentas": "tool",
    "incidente": "incident",
    "incidentes": "incident",
    "marcador": "marker",
    "marcadores": "marker",
    "retries": "retry",
    "solucao": "resolution",
    "solucoes": "resolution",
    "usuario": "user",
}

_CONTEXT_ANCHOR_TERMS = {
    "architecture", "api", "auth", "backpressure", "benchmark", "budget",
    "canary", "chunk", "command", "conversation", "cookie",
    "decision", "dependency", "diff", "duplicate",
    "error", "executor",
    "fetch", "file", "fingerprint", "frontend",
    "header", "idempotency", "incident",
    "jwt",
    "marker",
    "planner",
    "registry", "retry",
    "tenant", "timeout", "tool",
    "workspace",
}

_WEAK_SINGLE_MATCH_TERMS = {"benchmark", "incident"}

_FOCUS_REQUIREMENTS = {
    "decision": {"auth", "cookie", "decision", "executor", "jwt", "planner"},
    "file": {"api", "backend", "file", "frontend", "path", "src"},
    "header": {"fingerprint", "header", "idempotency"},
    "marker": {"boundary", "canary", "marker", "tenant"},
}
