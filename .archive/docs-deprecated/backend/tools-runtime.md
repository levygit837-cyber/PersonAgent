# Tools Runtime no PersonAgent

## Visão geral

O sistema de ferramentas permite ao agente interagir com o mundo exterior: ler arquivos, executar shell, navegar na web, usar LSP e MCP. A execução é segura, paralela quando possível, e sempre com controle de permissões.

## Componentes principais

| Componente | Arquivo | Função |
|------------|---------|--------|
| `ToolRegistry` | `application/tools/registry.py` | Registro central de todas as ferramentas |
| `ToolOrchestrator` | `application/tools/orchestrator.py` | Orquestra execução em batches serial/paralelo |
| `ToolRuntimeConfig` | `application/tools/runtime_config.py` | Limites de timeout, tamanho, concorrência |
| `ToolDefinition` | `domain/tools/contracts.py` | Metadados de cada ferramenta (schema, permissões, grupo) |

## Ciclo de vida de uma chamada

1. **Validação de entrada**: `tool.validate_input()` verifica sintaxe e limites.
2. **Permissão**: `tool.check_permissions()` retorna `ALLOW`, `DENY` ou `ASK`.
3. **Execução**: `tool.call()` roda a operação com timeout.
4. **Resultado**: `ToolResult` com conteúdo, status e metadados.
5. **Streaming**: eventos `tool_call_started`, `tool_progress`, `tool_result` via SSE.

## Grupos de ferramentas

- `WORKSPACE`: leitura/escrita de arquivos
- `SHELL`: execução de comandos (maior restrição)
- `WEB`: fetch, search
- `BROWSER`: controle de browser (LightPanda/CDP)
- `LSP`: language server protocol
- `MCP`: Model Context Protocol
- `PLANNING`: TodoWrite, plan mode
- `USER_INTERACTION`: input do usuário

## Concorrência

- Ferramentas `is_concurrency_safe=True` executam em paralelo (até 4 simultâneas).
- Ferramentas `is_destructive=True` ou `requires_user_interaction=True` são serializadas.

## Configuração de limites

```python
ToolRuntimeConfig(
    workspace_root=Path("/projeto"),
    max_concurrency=4,
    shell_timeout_ms=10_000,
    read_max_bytes=10_000_000,
    result_max_chars=60_000,
)
```

## Referências

- ADR 0010: Tool Registry + Orchestrator
- ADR 0020: Shell Path Safety
