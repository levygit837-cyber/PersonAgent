# Decision Tree: Modificar Chunking da Memória


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Pergunta inicial
> Preciso ajustar como a memória operacional é dividida em chunks ou como é recallada.

---

## Passo 1: Identificar o pipeline

### Pipeline de memória:
```
Conversa → Extract → Chunk → Embed → Index → (tempo passa) → Recall
```

### Se o problema é na extração:
→ **Modificar ExtractMemoryWorker**
- Arquivo: `application/jobs/workers/extract_memory_worker.py`

### Se o problema é no chunking:
→ **Modificar OperationalMemoryChunker**
- Arquivo: `domain/memory/services/operational_memory.py`

### Se o problema é no recall:
→ **Modificar MemoryRecallSelector**
- Arquivo: `domain/memory/services/operational_memory.py`

### Se o problema é no embedding:
→ **Modificar OpenAICompatibleEmbeddingAdapter**
- Arquivo: `infrastructure/llm/embedding_adapter.py`

---

## Passo 2: Modificar Chunker

### Arquivo: `domain/memory/services/operational_memory.py`

`OperationalMemoryChunker`:
- Default: chunk size ~512 tokens, overlap ~50 tokens
- Modificar `chunk_size` e `overlap` no construtor

### Para mudar estratégia:
- Implementar novo método de chunking (semantic, sentence, fixed)
- Semantic chunking: quebra por sentenças
- Fixed chunking: quebra por tokens fixos

---

## Passo 3: Modificar Recall

### `MemoryRecallSelector`:
- Rankeia por: similaridade coseno + recency + token budget
- Modificar pesos em `rank_candidates()`

### Para adicionar novo critério:
1. Adicionar campo ao `RecallCandidate`
2. Modificar `rank_candidates()` para considerar novo campo
3. Atualizar `MemoryRecallSelector.__init__()` para aceitar config

---

## Passo 4: Testes

1. `tests/integration/test_memory.py`
2. Verificar:
   - Chunks têm tamanho esperado
   - Overlap é respeitado
   - Recall retorna os melhores candidatos
   - Token budget é respeitado

---

## Passo 5: Documentação

1. Atualizar ADR 0012 (Three-Layer Memory)
2. Atualizar `docs/app/memory.md`
3. Atualizar `docs/ai-guides/backend/memory-jobs.md`

---

## Checklist

- [ ] Chunk size é positivo e menor que max tokens do embedding
- [ ] Overlap é menor que chunk size
- [ ] Recall respeita token budget
- [ ] Testes de memória passam
- [ ] Documentação atualizada