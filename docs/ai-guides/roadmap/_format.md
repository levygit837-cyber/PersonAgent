# Roadmap document format

Every phase doc in this directory follows the same skeleton so the
roadmap stays auditable: a reviewer can scan any phase file and
immediately tell what was promised, what landed, and what is still
open. Don't invent new sections; if you need to add metadata, add it
to this template and propagate it to every phase doc.

## File naming

```
phase-<n>-<short-slug>.md
```

`<n>` is a single integer (no decimals). Sub-phases (e.g. 1.1, 1.2)
live inside the same file under explicit `## 1.1 …` / `## 1.2 …`
section headers. One file per phase keeps cross-references stable and
makes it easy to diff over time.

## Required sections (in order)

1. **Title** — `# Fase <n> — <short name>`
2. **Status header** — table with the keys below.
3. **Objetivo** — one paragraph: what user-visible / engineering-visible
   outcome this phase delivers. No implementation details.
4. **Contexto** — why this phase exists *now*. What pre-condition was
   established by previous phases? What is unblocked by this one?
5. **Decisões aplicáveis** — list of `DEC-XXX` IDs from
   `decisions.md` that constrain this phase. If you take a new
   architectural decision while executing the phase, add it to
   `decisions.md` and link here.
6. **Sub-fases** (optional) — one `## n.m` block per sub-phase, each
   with its own status table, deliverables, and PR list.
7. **Deliverables** — a checklist (`- [ ]`) of concrete, testable
   outcomes. Every item must be **observable from outside** (a passing
   test, a merged PR, a documented metric, a green CI check). No
   "research X" or "think about Y" items.
8. **Critérios de aceitação** — bullet list. Each bullet is a single
   verifiable statement. "Cobertura de testes para X aumentou de A
   para B", "Endpoint Y retorna 401 sem token", etc.
9. **Riscos & mitigações** — table: `| Risco | Mitigação |`.
10. **PRs vinculados** — table: `| PR | Título | Status | Notas |`.
    Updated as work lands.
11. **Notas operacionais** (optional) — anything a future agent
    picking this up needs to know that doesn't fit elsewhere.

## Status header keys

| Chave         | Valores válidos                                   |
| ------------- | ------------------------------------------------- |
| `Fase`        | `0`, `1`, `2`, `3`, …                             |
| `Status`      | `completed` / `in_progress` / `pending` / `paused` |
| `Owner`       | `repo-maintainer` por padrão                       |
| `Iniciada`    | `YYYY-MM-DD` ou `—`                                |
| `Concluída`   | `YYYY-MM-DD` ou `—`                                |
| `Depends on`  | Lista de fases pré-requisito (ex.: `Fase 0`)      |
| `Unblocks`    | Lista de fases que esta destrava                  |

## Audit rules

These are the rules a reviewer applies when checking the roadmap
during code review.

1. **Status reflects reality.** A phase is `completed` only when
   *every* deliverable checkbox is ticked and every PR in the table
   has merged. If even one checkbox is open, the phase is
   `in_progress` (or `paused`).
2. **No retroactive scope expansion.** If new work appears during a
   phase that wasn't in the original deliverables, it goes into a
   *follow-up phase* — never into the current one. The original phase
   doc must still describe what was actually planned, not what was
   actually done.
3. **One deliverable = one verifiable artifact.** Each `- [ ]` must
   point at something concrete (PR number, test name, doc path,
   metric). "Improve type safety" is not a deliverable; "Reduce mypy
   errors in `interfaces/api/routes/sessions.py` from 46 to 0" is.
4. **PRs are linked, not summarized.** The PR table holds the URL and
   one-line title; full context lives in the PR description itself,
   not the roadmap.
5. **Decisions are referenced, not duplicated.** When a phase relies
   on an architectural choice, link the `DEC-XXX` entry in
   `decisions.md`. Don't paste the rationale into the phase doc.
6. **Phases are independently shippable.** If Phase N is `completed`,
   the codebase must run end-to-end without Phase N+1 ever landing.
   No phase can leave the repo in a half-functional state.
7. **Closed phases are immutable.** Once a phase moves to
   `completed`, edit only typos and broken links. Substantive changes
   require a new phase.

## How to add a new phase

1. Copy `phase-0-anti-fogo.md` as a starting skeleton.
2. Set the status table to `pending`.
3. Fill in `Objetivo`, `Contexto`, `Decisões aplicáveis`.
4. Draft deliverables with checkboxes — but only items you can verify
   from outside. Anything you can't verify, drop or rephrase.
5. Add the new phase to `README.md`.
6. Reference any new architectural decisions in `decisions.md`.
7. Open a PR with `docs(roadmap): …` and merge before starting work.
