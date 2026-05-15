# Decision Tree: Adicionar um Novo Comando Slash

## Pergunta inicial
> Preciso adicionar um novo comando `/comando` que o usuário pode invocar.

---

## Passo 1: Escolher o tipo

### Se é ação de UI (não vai ao LLM):
→ **Built-in Command**
- Exemplos: `/clear`, `/model`, `/skills`
- Arquivo: `domain/prompts/commands.py`

### Se é comportamento de agente (vai ao LLM):
→ **Prompt Command (arquivo Markdown)**
- Ou **Built-in Command** com `should_query=True`

---

## Passo 2: Built-in Command

### Arquivo: `domain/prompts/commands.py`

Adicionar a `BUILTIN_COMMANDS` @ `:260`:
```python
"novo": BuiltinCommand(
    name="novo",
    description="Descrição do comando.",
    argument_hint="[argumentos]",
    allowed_tools=("Read", "Grep"),  # Se for query
    should_query=True,               # False = ação UI apenas
    ui_action="nome_da_acao",       # Se should_query=False
),
```

### Se `should_query=False`:
- Implementar handler da UI action no Electron
- Adicionar a `window.electronAPI` no preload

---

## Passo 3: Prompt Command (arquivo Markdown)

### Criar arquivo:
```bash
touch .personagent/commands/novo.md
```

### Conteúdo:
```markdown
---
description: "Descrição do comando"
allowed-tools: ["Read", "Grep"]
argument-hint: "[argumentos]"
---
# Comando Novo

Comportamento quando o usuário invoca /novo.
Argumentos: $ARGUMENTS
```

### Não requer mudança de código!

---

## Passo 4: Testes

### Built-in:
1. `tests/unit/domain/prompts/test_commands.py`
2. Testar `CommandService.resolve_builtin("/novo args")`
3. Verificar `should_query` e `ui_action`

### Prompt Command:
1. Testar `CommandRegistry.resolve("/novo args")`
2. Verificar expansão de `$ARGUMENTS`

---

## Passo 5: Documentação

1. Atualizar `docs/ai-guides/backend/command-registry.md`
2. Se built-in com UI action, documentar no frontend

---

## Checklist

- [ ] Nome não conflita com comandos existentes
- [ ] Regex de parsing aceita o nome (`[A-Za-z0-9][A-Za-z0-9_.:/-]*`)
- [ ] `should_query` definido corretamente
- [ ] Testes de resolução passam
- [ ] Documentação atualizada
