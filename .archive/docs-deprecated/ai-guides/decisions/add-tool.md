# Decision Tree: Adicionar uma Nova Ferramenta


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Pergunta inicial
> Preciso adicionar uma nova ferramenta para o agente usar.

---

## Passo 1: Definir categoria

### Se é read-only (não modifica estado externo):
- `is_destructive=False`
- `is_concurrency_safe=True` (geralmente)
- Exemplos: `ReadFile`, `GrepFile`, `WebFetch`

### Se modifica estado (write, delete, shell, etc.):
- `is_destructive=True`
- `is_concurrency_safe=False` (geralmente)
- Exemplos: `EditFile`, `WriteFile`, `Shell`

### Se requer interação do usuário:
- `requires_user_interaction=True`
- Exemplo: `AskUserQuestion`

---

## Passo 2: Implementar a ferramenta

### Arquivo: `infrastructure/tools/<category>_tools.py` ou novo arquivo

1. Criar classe herdando de `Tool` (ou `BaseTool`):
   ```python
   class NovaTool(Tool):
       @property
       def definition(self) -> ToolDefinition:
           return ToolDefinition(
               name="NovaTool",
               description="...",
               parameters={...},  # JSON schema
               is_destructive=False,
               is_concurrency_safe=True,
               requires_user_interaction=False,
               group=ToolGroup.WORKSPACE,
           )

       async def call(self, arguments: dict[str, Any], context: ToolUseContext) -> ToolResult:
           ...

       def check_permissions(self, arguments: dict[str, Any], context: ToolUseContext) -> ToolPermissionResult:
           return ToolPermissionResult(behavior=ToolPermissionBehavior.ALLOW)

       def validate_input(self, arguments: dict[str, Any]) -> ToolInputValidationResult:
           return ToolInputValidationResult(valid=True)
   ```

2. Se a ferramenta precisa de permissão condicional, implementar `check_permissions()`
3. Se precisa de validação de input complexa, implementar `validate_input()`

---

## Passo 3: Registrar no ToolRegistry

### Arquivo: `infrastructure/tools/__init__.py` ou DIContainer

```python
def create_nova_tool(...) -> NovaTool:
    return NovaTool(...)
```

Registrar em `ToolRegistry` via DIContainer ou no factory de tools:
```python
registry.register(nova_tool)
```

---

## Passo 4: Adicionar ao prompt

Se a ferramenta deve ser mencionada no system prompt:

1. Verificar se `ToolRegistry` já a inclui automaticamente
2. Ou adicionar descrição custom em `domain/prompts/sections/tools.py`

---

## Passo 5: Testes

1. Criar `tests/unit/tools/test_nova_tool.py`
2. Testar:
   - `validate_input()` com args válidos e inválidos
   - `check_permissions()` com diferentes contexts
   - `call()` com mock de dependências
   - Erro handling (timeout, not found, etc.)

---

## Passo 6: Documentação

1. Atualizar ADR 0010 (Tool Orchestrator) se mudar comportamento do registry
2. Atualizar `docs/backend/tools-runtime.md`
3. Atualizar `docs/ai-guides/backend/llm-adapters-deep-dive.md` se afetar adapters

---

## Checklist

- [ ] Implementa interface `Tool`
- [ ] `definition` com schema JSON válido
- [ ] `call()` retorna `ToolResult`
- [ ] `check_permissions()` apropriado
- [ ] `validate_input()` apropriado
- [ ] Registrada no `ToolRegistry`
- [ ] Testes unitários passam
- [ ] Teste de integração em `test_tools.py`
- [ ] Documentação atualizada