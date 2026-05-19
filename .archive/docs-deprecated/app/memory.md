# Memory no PersonAgent

## Visão geral

O sistema de memória é dividido em três camadas, cada uma com propósito, persistência e latência diferentes.

## Camadas

### 1. Session Memory
- **Onde**: `~/.cache/personagent/sessions/{conversation_id}.md`
- **O que**: resumo da sessão, scratchpad, notas temporárias
- **Quando**: a cada turno, se houver conteúdo
- **Como**: `SessionMemoryService` lê/escreve arquivos Markdown

### 2. Operational Memory (RAG)
- **Onde**: PostgreSQL + pgvector
- **O que**: chunks semânticos de conversas anteriores, conhecimento do projeto
- **Quando**: jobs diários (`EXTRACT_MEMORIES`, `AUTO_DREAM`)
- **Como**: `OperationalMemoryService` extrai, chunka, embedda e indexa

### Pipeline de RAG

1. **Extract**: `MemoryExtractionJob` analisa conversas e extrai fatos relevantes.
2. **Chunk**: divide em trechos de ~512 tokens.
3. **Embed**: `OpenAICompatibleEmbeddingAdapter` gera vetores via llama.cpp `--embedding`.
4. **Index**: armazena em `memory_embeddings` com HNSW index.
5. **Recall**: `MemoryRecallSelector` busca por similaridade coseno + recency + token budget.

### 3. Filesystem Memory
- **Onde**: arquivos do projeto (`persona.md`, `.personagent/rules`, `.cursor/rules`)
- **O que**: conhecimento estruturado do usuário sobre o projeto
- **Quando**: no início de cada conversa
- **Como**: `BuildContextUseCase` carrega e injeta no prompt

## Configuração

```yaml
memory:
  auto_memory_enabled: true
  operational_memory_enabled: true
  auto_dream_enabled: true
```

## Referências

- ADR 0012: Three-Layer Memory
