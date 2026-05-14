# Mitigações de Risco no PersonAgent

## Visão geral

Documento de mitigações para os principais riscos identificados nos ADRs.

## Riscos e mitigações

### 1. Vazamento de secrets para providers hosted

| Risco | Mitigação |
|-------|-----------|
| Regex pode falhar | Revisão periódica das patterns; testes com secrets sintéticos |
| Usuário desativa política | Não permitido; política é hardcoded no backend |
| Secret em base64 | Regex cobre padrões comuns; não garante todos os encodings |

**Owner**: `@backend/src/personagent/infrastructure/security/provider_data_policy.py`

### 2. Execução arbitrária via shell tool

| Risco | Mitigação |
|-------|-----------|
| Bypass de allowlist | Allowlist é string-match; validação de path impede `../` |
| Symlink escape | Resolve symlinks antes de validar |
| Workspace grant excessivo | UI pede confirmação visual para novos workspaces |

**Owner**: `@backend/src/personagent/infrastructure/tools/shell_tool.py`

### 3. Falsificação de action approvals

| Risco | Mitigação |
|-------|-----------|
| Segredo vazado | Arquivo com `chmod 600`; nunca commitado |
| TTL curto demais | 300s equilibra UX e segurança |
| Clock skew | Desktop e backend devem usar NTP |

**Owner**: `@desktop-electron/electron/main.ts` (signing)

### 4. Modelo local não inicia

| Risco | Mitigação |
|-------|-----------|
| Binary não encontrado | Fallback para PATH e locais comuns |
| Modelo ausente | Log claro indicando caminho esperado |
| GPU OOM | Reduzir `n_gpu_layers` automaticamente (não implementado) |

**Owner**: `@backend/src/personagent/infrastructure/llm/process_manager.py`

### 5. RAG retorna conteúdo irrelevante

| Risco | Mitigação |
|-------|-----------|
| Chunk ruim | Tamanho de chunk ajustável; testes de recall |
| Embedding ruim | Fallback para modelos de embedding testados |
| Memória poluída | Filtro de recency e relevância no `MemoryRecallSelector` |

**Owner**: `@backend/src/personagent/application/services/operational_memory.py`

### 6. Documentação desatualizada

| Risco | Mitigação |
|-------|-----------|
| ADR obsoleto | Revisão em toda release (checklist) |
| Doc não reflete código | Fast Context deve encontrar ADR relevante antes de editar |
| Novo dev perdido | READMEs com links cruzados; ADRs numerados |

**Owner**: `docs/adr/README.md`, `docs/README.md`

## Revisão

Este documento deve ser revisado a cada release major ou quando um novo risco crítico é identificado.

## Referências

- ADRs 0017-0021 (Infra e Segurança)
