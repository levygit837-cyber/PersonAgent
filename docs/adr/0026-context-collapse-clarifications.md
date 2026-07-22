# ADR 0026: Context Collapse — Correções de Entendimento e Decisões Abertas

Date: 2026-05-30
Status: Proposed

## Context

Durante análise aprofundada da documentação de context engineering (especificamente `layer-04-context-collapse.md`), identificamos imprecisões e lacunas no entendimento de como o Context Collapse funciona na prática, especialmente em relação à mecanismos de expansão, custo de tokens de summaries, e o que "reversível" realmente significa para o modelo versus para o usuário.

Problemas identificados:

1. **"Expansão" é ambígua**: A documentação afirma que "user or model can ask to expand a collapsed section", mas não explica COMO o modelo faria isso. Não existe mecanismo documentado para o LLM solicitar expansão de uma seção colapsada.
2. **"Reversível" confunde armazenamento com contexto**: O fato de que a conversação completa é preservada no Collapse Store não significa que o modelo pode acessá-la. O modelo só vê a projected view. A reversibilidade é para o usuário (via UI/transcript) e para logs, não para o LLM em tempo de inferência.
3. **Não há mecanismo de expansão on-demand**: O modelo recebe summaries por padrão em toda turno. Não existe forma de o modelo dizer "mostre-me o código completo da seção 3" sem que isso seja implementado como uma ferramenta explícita.
4. **Prompt de summary é uma decisão em aberto**: Não existe evidência de que Context Collapse reutiliza o prompt de 9 seções do Auto-Compact. O prompt para gerar summaries de grupos de mensagens é uma decisão de design não documentada na análise do Claude Code.

## Decision

### Correções de Entendimento (Documentação)

1. **Expansão é "planned"/futura**: O mecanismo de expansão para o modelo não está implementado na análise do Claude Code. É um recurso arquiteturalmente suportado (dados originais existem no Collapse Store), mas requer uma ferramenta (`expand_context`, `view_collapsed_range`) ou ação de UI para ser funcional.

2. **Reversibilidade é para storage, não para contexto ativo**: O Collapse Store preserva os dados, mas o LLM só acessa via `projectView()`. O LLM não pode "desfazer" um collapse durante a conversação sem um mecanismo externo.

3. **Prompt de summary é aberto**: Não assumimos que Context Collapse usa o mesmo prompt do Auto-Compact. O prompt para summaries de grupos deve ser:
   - **Focado no grupo de turns** (não na sessão inteira)
   - **Consciente de timeline** ("durante turns 5-20, nós...")
   - **Otimizado para compressão de múltiplas mensagens** (não apenas uma síntese geral)
   - **Fallback**: Se nenhum prompt especializado for definido, pode-se reutilizar o prompt do Auto-Compact como base, mas adaptado para o contexto de grupo.

### Decisões de Design em Aberto

As seguintes decisões precisam ser tomadas antes de implementar Context Collapse no PersonAgent:

| Decisão | Opções | Status |
|---------|--------|--------|
| Arquitetura de summary | Unified (um summary por commit) vs Categorized (múltiplos summaries tipados) | Em aberto — ver proposta em `docs/context-engineering/context-collapse-categorized-summaries.md` |
| Taxonomia de categorias | Quais tipos de summary? Ex: CodeSummary, TaskSummary, TestSummary, ErrorSummary... | Em aberto — depende da decisão acima |
| Mecanismo de expansão | Tool call síncrona? Async? Re-injeção de mensagens? | Em aberto — ver proposta documentada |
| Prompt de summary | Prompt especializado por categoria? Prompt único genérico? | Em aberto |
| Formato de metadata/links | Como representar relacionamentos entre summaries? | Em aberto |

## Consequences

- **Easier**: Documentação precisa sobre como Context Collapse realmente funciona, sem promessas de "expansão automática" que não existem.
- **Easier**: Decisões de design estão explicitamente documentadas como abertas, evitando implementações baseadas em suposições.
- **Harder**: Requer análise e decisão sobre arquitetura de summaries antes de implementação.
- **Risk**: Se não definirmos prompt e taxonomia adequados, os summaries podem ser grandes demais ou pouco úteis para o modelo.

## Alternatives Considered

- **Manter documentação original sem correções**: rejeitado — documentação imprecisa leva a más decisões de arquitetura.
- **Assumir que prompt do Auto-Compact é o canonical para Context Collapse**: rejeitado — suposição sem evidência; grupos de mensagens provavelmente precisam de tratamento diferente de sessões inteiras.
- **Usar apenas Auto-Compact em vez de Context Collapse**: rejeitado — Context Collapse ainda é superior para organização granular e preservação de histórico.

## Validation

- Revisar documentação `layer-04-context-collapse.md` para refletir as correções deste ADR.
- Documentar proposta completa de Category-Based Summaries em documento separado (`docs/context-engineering/context-collapse-categorized-summaries.md`).
- Quando decisões forem tomadas, atualizar este ADR com status "Accepted" e detalhes da arquitetura escolhida.
