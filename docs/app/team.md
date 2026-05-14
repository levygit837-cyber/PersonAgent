# Team Mode no PersonAgent

## Visão geral

Team Mode executa múltiplos agentes especializados em fases (debate, voto, síntese) para análise mais profunda de solicitações complexas.

## Preset padrão

| Agente | Função |
|--------|--------|
| Analyst | Análise técnica e requisitos |
| Critic | Identificação de riscos e gaps |
| Builder | Proposta de solução |
| Reviewer | Revisão final |
| Coordinator | Síntese e resposta final (não vota) |

## Fases

1. **Execution Contract**: Coordinator cria subproblemas e matriz de cobertura.
2. **Independent Round**: cada agente publica sua visão inicial.
3. **Blackboard Publish**: claims são deduplicados e pontuados.
4. **Debate Round**: agentes criticam e refinam.
5. **Coordinator Planning**: foco e redirecionamentos.
6. **Vote**: aprovação com 75% de consenso.
7. **Final Synthesis**: Coordinator streaming da resposta.

## Blackboard

- Estrutura em memória (`_Blackboard`) com entries, claim graph, coverage matrix.
- Persistido em PostgreSQL (`team_blackboard_events`) para auditoria.

## Tool Policy

- `guarded_autonomy`: leitura livre, mutação exige aprovação.

## Uso

```bash
curl -X POST http://localhost:8000/chat/team \
  -H "Content-Type: application/json" \
  -d '{"message": "Review this architecture", "team": "default"}'
```

## Referências

- ADR 0011: Team Mode
