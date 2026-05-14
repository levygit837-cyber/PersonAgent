# Pull Request

## Summary

<!-- Descreva o que mudou e por quê em 2-3 frases. -->

## Tipo de mudança

- [ ] Bug fix
- [ ] Nova feature
- [ ] Refatoração
- [ ] Documentação
- [ ] Dependências / build
- [ ] Testes

## Checklist

### Código

- [ ] Testes passam (`pytest`, `npm test`)
- [ ] Lint passa (`ruff`, `eslint`, `prettier`)
- [ ] Type check passa (`mypy`, `tsc`)
- [ ] Não há código morto ou `console.log`

### Documentação

- [ ] ADR atualizado se houve mudança arquitetural
- [ ] `docs/api/README.md` atualizado se rotas mudaram
- [ ] `docs/backend/*.md` ou `docs/app/*.md` atualizados se subsistemas mudaram
- [ ] `CHANGELOG.md` atualizado

### Segurança

- [ ] Não há novos secrets hardcoded
- [ ] Permissões de tools foram revisadas
- [ ] Provider data policy cobre novos campos sensíveis

## Screenshots / Logs

<!-- Se aplicável, anexe screenshots ou logs de execução. -->

## Notas para reviewer

<!-- Pontos específicos que o reviewer deve prestar atenção. -->
