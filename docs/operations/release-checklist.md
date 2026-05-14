# Release Checklist no PersonAgent

## Pré-release

- [ ] Todos os testes passam (`pytest`, `npm test`)
- [ ] Lint sem erros (`ruff`, `eslint`, `prettier`)
- [ ] Type check (`mypy`, `tsc`)
- [ ] ADRs atualizados se houver mudança arquitetural
- [ ] Docs operacionais sincronizadas com código
- [ ] `config.example.yaml` reflete novas opções
- [ ] `.env.example` atualizado
- [ ] CHANGELOG.md atualizado

## Build

- [ ] Backend: `docker build -t personagent-backend .`
- [ ] Desktop: `cd @desktop-electron && npm run dist`
- [ ] llama.cpp: build para Linux, macOS, Windows

## Testes de integração

- [ ] Chat simples (sem tools)
- [ ] Chat com tools (Read, Grep, Shell)
- [ ] Plan mode (aprovar/cancelar)
- [ ] Team mode (4 agentes)
- [ ] Browser (abrir, extrair, screenshot)
- [ ] Memory (recall de sessão anterior)
- [ ] QA tracing (indexar + executar request)
- [ ] SSE reconexão após restart

## Deploy

- [ ] Tag Git: `git tag -a vX.Y.Z -m "Release X.Y.Z"`
- [ ] Push tag: `git push origin vX.Y.Z`
- [ ] GitHub Release com assets
- [ ] Docker Hub push (se aplicável)

## Pós-release

- [ ] Verificar telemetria de erros (primeiras 24h)
- [ ] Monitorar logs de provider (rate limits)
- [ ] Responder a issues reportadas

## Rollback

- [ ] Docker: `docker compose down && docker compose up` com imagem anterior
- [ ] Desktop: reinstalar versão anterior
- [ ] Banco: schema é forward-only; não há downgrade automático

## Referências

- `docs/operations/README.md`
