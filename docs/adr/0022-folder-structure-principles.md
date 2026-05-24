# ADR 0022: Folder Structure Principles (Backend)

Date: 2026-05-24
Status: Proposed

## Context

ADR-0001 set the four-layer Clean Architecture (`domain → application → infrastructure → interfaces`). Two years of growth later, the *layer model* is intact but the *folder structure inside each layer* has drifted:

- **5 single-file folders** exist purely to hold one file (`application/ports/`, `application/security/`, `domain/services/`, `interfaces/api/middleware/`, `interfaces/cli/commands/`). They add navigation cost without organizational benefit.
- **Bounded contexts inside `domain/` are inconsistent.** `memory/` and `context/` get the full mini-DDD treatment (`models/`/`repositories/`/`services/`), while `conversation`, `llm_backend`, `tenancy`, and other concepts live flat at `domain/models/` and `domain/repositories/`. There is no documented rule explaining the inconsistency.
- **`interfaces/api/` mixes routes with utilities.** Endpoint files (`action_approvals.py`, `state_events.py`, `workspace_grants.py`) live loose at the root of `api/` instead of in `api/routes/`, and `routes/security.py` collides in name with `api/security.py`.
- **Two "config" folders** with unrelated responsibilities — `interfaces/config/` (DI composition root) and `infrastructure/config/` (env settings) — make it hard to know which one to edit.
- **`use_cases/chat/` reached 20 files** after the chat_completion decomposition (PRs #7–#30). The same fate awaits `use_cases/team_chat/` and other large use cases as decomposition progresses.
- **The name `interfaces/`** is canonical in Clean Architecture (Uncle Bob, *Clean Architecture* ch.17, "interface adapters" layer) but conflicts with Python's vernacular use of *interface* = `Protocol` / `ABC`. New contributors regularly assume `interfaces/` holds contracts, not HTTP routes.

We need a single source of truth that captures the structural rules so every future PR (god-file decompositions, new bounded contexts, new entrypoints) follows them without re-litigating them each time. ADR-0001 covers the *layers*; this ADR covers the *folder rules inside the layers*.

## Decision

Adopt the following seven principles. Apply them consistently across `@backend/src/personagent/`.

### Principle 1 — Single-file folders are forbidden

If a folder would contain exactly one `.py` file (excluding `__init__.py`), it must be flattened. The file lives one level up.

> **Examples to fix**: `application/ports/foo.py` → `application/contracts.py`; `domain/services/__init__.py` empty → delete folder; `interfaces/cli/commands/__init__.py` empty → delete folder.

### Principle 2 — Bounded contexts in `domain/` follow a uniform shape

Every domain concept (conversation, memory, context, prompts, tenancy, llm_backend, tools, etc.) lives in its own sub-package under `domain/`:

```
domain/<concept>/
├── models.py              # or models/ if >7 files (see Principle 4)
├── repositories.py        # or repositories/ if >7 files
└── services.py            # optional; or services/ if >7 files
```

No concept stays at `domain/models/<thing>.py` or `domain/repositories/<thing>.py`. The current `domain/memory/` and `domain/context/` already follow this shape; the rest of the codebase migrates to match.

### Principle 3 — `adapters/api/` contains routes and middleware only

The HTTP entry layer has exactly three kinds of file:

- `main.py` (FastAPI app wiring) at the root.
- `errors.py` (FastAPI exception handlers, optional) at the root.
- `routes/<group>.py` for every endpoint group.
- `middleware/<name>.py` for every middleware.

No loose endpoint files at the layer root. Names of route files and middleware files do not collide (e.g. `middleware/auth.py` instead of a second `security.py`).

### Principle 4 — Use cases scale with sub-packages

The size of a use case determines its layout:

- **1 file**: stays a flat `application/use_cases/<name>.py`.
- **2 to 7 files**: 1 folder with flat files: `application/use_cases/<name>/foo.py`.
- **More than 7 files**: 1 folder with *thematic* sub-packages, never numbered/alphabetic ones. Each sub-package has 3–6 cohesive files.

Every god-file decomposition (PRs #7–#30 for chat_completion, PRs #14/#17/#21/#26/#27/#29 for team_chat) ends in a folder shaped by this rule.

### Principle 5 — Folder names tell the story

Generic names like `config/`, `utils/`, `helpers/`, `common/`, `misc/` are forbidden at any layer's root because they do not communicate purpose. Use concrete names instead:

- DI composition root: `composition/` (not `config/`).
- Env settings + Pydantic Settings: `settings/` (not `config/`).
- Domain-pure helpers shared across collaborators: lives inside the use case's folder as `helpers.py` (file, not folder, unless Principle 4 forces a folder).

### Principle 6 — `infrastructure/` mirrors external concerns

Each external driver gets its own sub-folder: `llm/`, `browser/`, `persistence/`, `tools/`, `mcp/`, `settings/`, etc. No `.py` file lives loose at the root of `infrastructure/` (current `artifacts.py` moves into `persistence/` or its own folder per this principle).

### Principle 7 — Rename `interfaces/` to `adapters/`

The Clean Architecture name "interfaces" (interface adapters) collides with Python's vernacular meaning of "interface" (Protocol/ABC). Rename the layer to `adapters/`. Side benefits:

- `application/ports/` (current single-file folder, see Principle 1) becomes meaningful when moved: ports define contracts, adapters implement them — the **Ports and Adapters / Hexagonal Architecture** vocabulary aligns naturally.
- No ambiguity for new contributors: `adapters/api/`, `adapters/cli/`, `adapters/composition/`.

ADR-0001 is **updated** (not superseded) by adding a footnote that the layer formerly called `interfaces` is now `adapters`; the dependency rule (`adapters → application → domain`) and the inward-only direction are unchanged.

## Target shape after migration

The migration PR (see *Validation*) produces:

```
@backend/src/personagent/
├── domain/
│   ├── conversation/             # bounded context — was flat in domain/models, domain/repositories
│   │   ├── models.py
│   │   └── repositories.py
│   ├── memory/                   # already correct
│   │   ├── models/               # >3 files, folder
│   │   ├── repositories.py
│   │   └── services/             # >3 files, folder
│   ├── context/                  # already correct
│   ├── prompts/
│   ├── tools/
│   ├── tenancy/                  # new bounded context — was domain/models/tenancy.py
│   ├── llm_backend/              # new — was domain/repositories/llm_backend_repository.py
│   └── exceptions.py             # cross-cutting, stays at root
│
├── application/
│   ├── use_cases/
│   │   ├── chat/                 # sub-pkged per Principle 4
│   │   │   ├── orchestrator.py   # was chat_completion.py
│   │   │   ├── state.py
│   │   │   ├── helpers.py
│   │   │   ├── prompt/
│   │   │   ├── tools/
│   │   │   ├── streaming/
│   │   │   ├── bookkeeping/
│   │   │   └── memory/
│   │   ├── team_chat/            # similar after Phase 1.3 closes
│   │   ├── context/
│   │   └── memory/
│   ├── services/
│   │   └── security.py           # was application/security/ (single-file folder)
│   ├── tools/
│   ├── jobs/
│   ├── state/
│   ├── qa/
│   ├── dto/
│   └── contracts.py              # was application/ports/ (single-file folder); pairs with adapters/
│
├── infrastructure/
│   ├── llm/
│   ├── browser/
│   ├── persistence/              # artifacts.py moves into here
│   ├── tools/
│   └── settings/                 # was infrastructure/config/, per Principle 5
│
└── adapters/                     # was interfaces/, per Principle 7
    ├── api/
    │   ├── main.py
    │   ├── errors.py
    │   ├── middleware/
    │   │   └── auth.py           # was api/security.py
    │   └── routes/
    │       ├── action_approvals.py  # was api/action_approvals.py
    │       ├── state_events.py      # was api/state_events.py
    │       ├── workspace_grants.py  # was api/workspace_grants.py
    │       └── ...                  # existing routes
    ├── cli/
    │   └── main.py               # commands/__init__.py folder deleted
    └── composition/              # was interfaces/config/, per Principle 5
        └── container.py
```

## Consequences

- **Easier**: any future PR has a deterministic answer to "where does this file go?". New bounded contexts add their own folder without arguing. Decomposition playbooks shrink because their "target layout" section follows Principle 4 mechanically.
- **Harder**: the migration PR touches ~200 imports across the codebase. Mitigated by doing it as a single mechanical PR (`git mv` + `ast-grep --rewrite` for imports) gated by ADR approval.
- **Risk**: the migration must happen during a quiet window — no open decomposition PRs, no in-flight feature work touching the renamed paths. Mitigated by scheduling it explicitly after Phase 1 close (team_chat 1.3 + lightpanda 1.5 merged).
- **Risk**: Principle 7 (`interfaces/` → `adapters/`) touches every external Python import path. Documentation, ADR-0001 wording, the dependency graph in `docs/ai-guides/backend/dependency-graph.md`, and CI gates (`pytest tests/test_api_security.py` etc.) all need a coordinated update in the migration PR.
- **Out of scope**: structural reorganization of `@desktop-electron/src/`. Frontend follows different conventions (component-driven, not layered); a separate ADR covers it if needed.

## Alternatives Considered

- **Status quo (no migration)**: rejected — the smells are real and compound. Each new god-file decomposition would inherit the inconsistency.
- **Flatten everything in `domain/`** (single `models/`, `repositories/`, `services/` for all concepts): rejected — `memory/` and `context/` already prove that bounded contexts scale better as they grow (memory alone has 9 service files; flat would create a 30+ file `domain/services/`).
- **Keep `interfaces/` name**: rejected — even with the rename being expensive, the cost of perpetual confusion ("interface" = Protocol vs entry-point) is higher long-term. The Hexagonal terminology (Ports + Adapters) is a strict superset of Clean Architecture and resolves the ambiguity.
- **Split into multiple ADRs (one per principle)**: rejected — the principles are coupled (Principle 1 + Principle 4 + Principle 5 jointly determine the chat sub-package shape; Principle 7 + ADR-0001 jointly define the layer model). One ADR is more navigable.
- **Do the migration incrementally across many PRs**: rejected — incremental migration leaves the codebase in inconsistent states between PRs (some files moved, others not). Inconsistency is the original problem this ADR fixes.

## Validation

- **Pre-migration** (during ADR approval): no code change. Validation is review-only.
- **Migration PR** (after Phase 1.3 + 1.5 close):
  1. `git mv` operations are deterministic and listed in a `scripts/restructure.sh` committed alongside the PR.
  2. Imports updated via `ast-grep --rewrite` (or manual `sed` per import group); the script is reproducible.
  3. `ruff check @backend/` clean.
  4. `mypy --config-file @backend/pyproject.toml @backend/` shows no new errors compared to pre-migration baseline.
  5. Full test suite passes: `uv run pytest @backend/tests/ -q` (706 unit + 11 integration team-chat + chat-completion gates).
  6. CI pinned-file gates updated to new paths (e.g. `tests/test_api_security.py` still runs against the renamed `adapters/api/`).
  7. `docs/ai-guides/backend/dependency-graph.md` regenerated to reflect new paths.
- **Post-migration**: a follow-up CI check enforces Principles 1, 5, and 6 mechanically — a small script (`scripts/check_folder_principles.py`) fails CI if a single-file folder is added, if `config/` appears as a folder name, or if a `.py` file lives loose at `infrastructure/` root.

## References

- ADR-0001: Clean Architecture (four-layer model) — refined here by Principles 2 and 7.
- *Clean Architecture* (Robert C. Martin), ch.17 "Interface Adapters" — origin of the layer-name conflict resolved by Principle 7.
- *Implementing Domain-Driven Design* (Vaughn Vernon), ch.4 "Architecture" — bounded context shape used in Principle 2.
- Hexagonal Architecture / Ports and Adapters (Alistair Cockburn, 2005) — vocabulary adopted by Principle 7.
- Audit report attached to session `c269376f0ba945f38c560bdf26534f8b` — empirical smell inventory.
