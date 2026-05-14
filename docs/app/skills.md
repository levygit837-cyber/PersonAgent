# Skills no PersonAgent

## Visão geral

Skills são extensões de comportamento baseadas em arquivos Markdown com frontmatter YAML. Permitem personalizar o agente por projeto sem modificar código.

## Formato

```markdown
---
name: python-refactor
version: "1.0.0"
description: "Regras de refatoração Python"
enabled: true
activation:
  - refactor
  - python
---
# Python Refactoring Skill

Ao refatorar Python, prefira...
```

## Discovery

O sistema busca skills em:

1. `workspace_root/.personagent/skills/`
2. `cwd/.personagent/skills/`
3. Caminhos extras (`tool_skill_root_paths`)
4. `~/.personagent/skills/` (global)
5. Built-in skills (embutidos)

## Ativação

- **Automática**: por keywords na mensagem do usuário.
- **Explícita**: via API (`skills: ["python-refactor"]`) ou slash command.
- Skills desativadas são descobertas mas não injetadas no prompt.

## Uso no Prompt

`PromptBuilder` injeta o corpo de skills ativas como seções adicionais do system prompt.

## API

| Endpoint | Descrição |
|----------|-----------|
| `GET /skills` | Lista skills disponíveis |
| `POST /skills/enable` | Ativa uma skill |
| `POST /skills/disable` | Desativa uma skill |

## Referências

- ADR 0008: Skills System
