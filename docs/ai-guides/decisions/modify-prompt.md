# Decision Tree: Modificar o Comportamento do Prompt

## Pergunta inicial
> Preciso mudar como o system prompt é montado ou como o agente se comporta.

---

## Passo 1: Identificar o tipo de mudança

### Se é sobre conteúdo do prompt (o que o LLM vê):
→ **Modificar PromptBuilder**
- Arquivo: `domain/prompts/services/prompt_builder.py`
- Adicionar/modificar seção em `domain/prompts/sections/`

### Se é sobre detecção de modo (auto/writing/exploring/research):
→ **Modificar PromptContextAnalyzer**
- Arquivo: `domain/prompts/services/context_analyzer.py`
- Ou adicionar novo modo em `domain/prompts/models.py`

### Se é sobre estado do agente (planning, debug, etc.):
→ **Modificar AgentStateResolver**
- Arquivo: `domain/prompts/services/agent_state_resolver.py`

### Se é sobre skills injetadas:
→ **Modificar SkillDefinition ou PromptBuilder**
- Arquivo: `domain/prompts/skills.py` (para formato de skill)
- Arquivo: `domain/prompts/services/prompt_builder.py` (para injeção)

### Se é sobre comandos slash:
→ **Modificar CommandRegistry**
- Arquivo: `domain/prompts/commands.py`
- Ou criar arquivo `.md` em `.personagent/commands/`

---

## Passo 2: Modificar PromptBuilder

### Para adicionar nova seção:
1. Criar arquivo em `domain/prompts/sections/<nova_secao>.py`
2. Implementar função que retorna string da seção
3. Registrar em `PromptBuilder`
4. Adicionar condição de inclusão (sempre? só quando X?)

### Para modificar seção existente:
1. Editar arquivo em `domain/prompts/sections/`
2. Verificar `cache_break=True` se a seção varia por turno

---

## Passo 3: Verificar cache

### Se a nova seção varia a cada turno:
- Marcar com `cache_break=True`
- Isso invalida o cache do prompt a cada turno

### Se é estática por sessão:
- Não precisa de `cache_break`
- PromptBuilder reutiliza seção memoizada

---

## Passo 4: Testes

1. `tests/unit/prompts/test_prompt_builder.py`
2. Verificar que prompt contém nova seção
3. Verificar que cache funciona (se aplicável)
4. Verificar que `cache_break` invalida corretamente

---

## Passo 5: Documentação

1. Atualizar ADR 0007 se mudar arquitetura de seções
2. Atualizar `docs/app/prompt-system.md`
3. Atualizar `docs/ai-guides/backend/` guides relevantes

---

## Checklist

- [ ] Seção adicionada/modificada
- [ ] Cache configurado corretamente
- [ ] Testes de prompt passam
- [ ] Testes de cache passam
- [ ] Documentação atualizada
