# Prompt System no PersonAgent

## Visão geral

O system prompt é montado dinamicamente a cada turno pelo `PromptBuilder`, combinando seções modulares com base no contexto, modo, ferramentas disponíveis e estado do agente.

## Componentes

| Componente | Função |
|------------|--------|
| `PromptBuilder` | Monta o system prompt completo |
| `PromptContextAnalyzer` | Classifica a intenção do usuário (auto-mode) |
| `AgentStateResolver` | Resolve o estado de execução atual |
| `PromptSurfaceRegistry` | Registra surfaces disponíveis |

## Modos de prompt

- `auto` (padrão): analisa a mensagem e escolhe `writing`, `exploring` ou `research`.
- `writing`: foco em geração de código/documentos.
- `exploring`: investigação de código, arquitetura.
- `research`: busca externa, análise profunda.

## Seções

1. **Base**: identidade, regras, compact mode.
2. **Tools**: descrição de ferramentas, search hints, rich tool prompts.
3. **Execution**: reasoning policy, output format, parallel tool use.
4. **Agent State**: instruções específicas do estado atual (planning, debug, etc.).
5. **Skills**: corpos de skills ativas.
6. **Context Attachments**: git status, persona.md, regras do projeto.

## Cache

- Seções sem `cache_break=True` são memoizadas por sessão.
- O cache key inclui: tools ativas, modo, provider, model, agent states.

## Exemplo de fluxo

```python
profile = await analyzer.analyze(message="refactor this function")
# -> PromptProfile(primary_mode="writing", confidence=0.92)

state_profile = resolver.resolve(prompt_profile=profile, ...)
# -> AgentStateProfile(states=("intake", "planning", "implementation"))

prompt = await builder.build(
    system_context=ctx,
    prompt_mode="auto",
    prompt_profile=profile,
    agent_state_profile=state_profile,
    available_tools=["Read", "Edit", "Grep"],
)
```

## Referências

- ADR 0007: Modular Prompt Engineering
- ADR 0008: Skills System
