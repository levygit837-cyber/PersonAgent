# Decomposition Protocol

Shared rules every god-file playbook in this directory follows. Read
this **once** before working any playbook, then use the per-file
playbooks as concrete checklists.

The protocol exists because we've already executed five slices of
this pattern on `chat_completion.py` (PRs #7–#11) and we want every
future slice — on the same file or any other god file — to follow
the same shape so reviewers can read the diff fast and so we never
break behavior.

## Hard rules (do not bend)

1. **No behavior changes per PR.** Extraction is pure reorganization.
   If you discover a bug, file an issue, do not fix it inside an
   extraction PR.
2. **One slice = one PR.** No "while I'm in here" cleanups. Smaller
   PRs land faster and have lower regression risk.
3. **Never modify existing tests.** You may *add* tests for the new
   module. Touching existing tests in the same PR muddies the diff
   and breaks the safety net.
4. **Never amend or force-push to `main`.** Use a fresh
   `refactor/<timestamp>-<name>` branch per slice.
5. **The full regression suite must pass before commit.** See
   "Validation gates" below — these are non-negotiable.
6. **Never silently drop side effects.** If the original method
   mutates `conversation.metadata`, the extracted module mutates
   `conversation.metadata`. If the original logs at WARNING, the
   extracted module logs at WARNING. Side effects are part of the
   contract.

## What counts as a "cohesive surface"

Before you can extract, you need to identify what to extract.
A cohesive surface satisfies **at least two** of these:

- **Shared collaborators**: a set of methods that all depend on the
  same 1–3 injected services (e.g., `OperationalMemoryService` +
  `MemoryJobScheduler`).
- **Shared verb**: methods that all do the same kind of work
  ("recall", "capture", "compact", "prepare prompt surface").
- **Shared state**: methods that read/write the same private
  attribute or the same well-known metadata keys.
- **Already-private cluster**: 3+ private methods that only call
  each other and have one or two public entry points.

If you can't justify the surface in one sentence ("extract X
because it owns the Y collaborator and the Z metadata key"), the
slice is wrong — pick a different one.

## Extraction pattern (per slice)

This is the proven seven-step pattern from PRs #7–#11. Don't
deviate.

### 1. Verify baseline is green

Before touching anything:

```bash
cd @backend
uv run ruff check src/ tests/
uv run mypy src/personagent/application/use_cases/chat \
            src/personagent/application/state \
            src/personagent/application/use_cases/context \
            src/personagent/domain/models/tenancy.py \
            src/personagent/domain/models/conversation.py
uv run pytest tests/unit tests/test_tool_loop_limit.py tests/test_alembic_setup.py \
              tests/test_conversations_api.py tests/test_team_chat_orchestrator.py \
              tests/test_action_approvals.py \
              -q --no-header \
              --deselect tests/unit/test_prompt_builder.py::TestPromptBuilder::test_agent_state_overlays_are_compact
```

Record the green test count. You're not allowed to land the PR
unless this number does not decrease.

### 2. Map the surface

Open the god file and tag every line that belongs to the slice:

- The methods you'll move (with line ranges).
- The constants / type aliases used only by those methods.
- The imports used only by those methods.
- The call sites (where the orchestrator calls into the surface).

Write this in a short notepad before you start coding. The PR
description will reuse it.

### 3. Create the module

New module path is the same package, one level down:

```
src/<package>/<feature>/<slice_name>.py
```

For chat_completion: `src/personagent/application/use_cases/chat/<slice_name>.py`.

The module exposes **one class** named after the verb
(`MemoryRecallCoordinator`, `OperationalMemoryCapture`,
`PromptSurfacePreparer`, …). Constructor takes the collaborators
explicitly:

```python
class FooCoordinator:
    def __init__(
        self,
        *,
        primary_dependency: PrimaryDep,
        optional_dependency: OptionalDep | None = None,
    ) -> None:
        self._primary = primary_dependency
        self._optional = optional_dependency
```

**Optional-collaborator policy**: if the original method had `if
self._foo is None: return ...` guards, the extracted module keeps
the same guards. Don't tighten the API surface during extraction.

### 4. Wire into the parent

In `__init__` of the god file, instantiate the new collaborator:

```python
self._foo_coordinator = FooCoordinator(
    primary_dependency=self._primary_dep,
    optional_dependency=optional_dep,
)
```

Then update every call site:

```python
# Before
result = await self._do_foo(request, conversation)
# After
result = await self._foo_coordinator.do_foo(request, conversation)
```

### 5. Delete the originals

After the call sites are updated, delete the original methods. Run
`ruff check --fix` — it removes unused imports automatically. Do
not leave behind shims, "compatibility methods", or pass-through
wrappers unless a separate downstream consumer imports them
directly (search to be sure).

### 6. Write the tests

In `tests/unit/test_<slice_name>.py`:

- **Stubs, not mocks**: define minimal classes that record their
  inputs (a `_FooServiceStub` with a `calls: list` attribute).
  Mocks lie about API shape; stubs force you to write what you
  mean.
- **15+ cases minimum** for non-trivial slices. Cover:
  - Happy path with all collaborators wired.
  - Each collaborator missing (when optional).
  - Each documented side effect (metadata mutations, scheduled
    background work, etc.).
  - Each failure mode (collaborator raises → caller does ___).
  - Each fallback (if primary returns empty, secondary runs).
  - Each edge case present in the original code (`if not foo:
    return`, special return values, etc.).
- **Pin the public contract, not internals.** Test through the
  public method; don't reach into private state to assert
  intermediate values.

### 7. Validation gates

Before commit:

```bash
cd @backend
uv run ruff check --fix src/ tests/   # auto-fix unused imports
uv run ruff check src/ tests/         # must end "All checks passed!"
uv run mypy <hardened module paths>   # must end "Success"
uv run pytest <regression command from step 1>
```

The test count must be **≥ baseline + number of new tests**. If
it's lower, you regressed something — find it and fix it before
committing.

### 8. Commit and open the PR

- Branch name: `refactor/$(date +%s)-<feature>-<slice-name>` (e.g.,
  `refactor/1779580519-chat-prompt-assembly-split`).
- Commit message subject: `refactor(<area>): extract <surface>
  into <ClassName>`.
- Commit body documents what moves, what changes in the parent,
  and the test count delta. Reuse the template at the bottom of
  this file.
- Fetch the PR template **before** calling `git_create_pr` — the
  tool refuses to create the PR if you skip this.
- PR body explicitly states "No behavior changes intended" and
  lists the before/after line counts of the god file.
- Wait for CI with `wait_mode="all"`. Address any failures before
  asking for human review.

## Validation gates (must-pass)

| Gate            | Command                                              | Expectation                |
| --------------- | ---------------------------------------------------- | -------------------------- |
| Lint            | `uv run ruff check src/ tests/`                      | `All checks passed!`       |
| Type-check      | `uv run mypy <hardened modules>`                     | `Success`                  |
| Backend tests   | `uv run pytest <regression command>`                 | ≥ baseline + new tests     |
| Frontend types  | `npm run typecheck` (in `@desktop-electron/`)        | exit 0                     |
| Frontend tests  | `npm test` (in `@desktop-electron/`)                 | ≥ baseline + new tests     |
| CI              | `git_pr_checks wait_mode="all"`                      | all checks green           |

## Anti-patterns (never do these)

- **Pass-through wrappers**: don't leave a deleted method as
  `def _foo(self, ...): return self._coord.foo(...)`. Either move
  it or don't.
- **Cross-layer imports in new code**: `application/` cannot
  import from `interfaces/`. `domain/` cannot import from
  anything outside `domain/`.
- **New circular imports**: run `python -c "import
  personagent.<module>"` after extraction.
- **`dict[str, Any]` proliferation in new code**: if the original
  used `dict[str, Any]`, keep it (don't make the diff larger). If
  you're creating a new return type, use a `@dataclass` or a
  `TypedDict`.
- **Modifying existing tests**: if a test breaks, it's because
  the extraction changed behavior. Fix the extraction, not the
  test.
- **Adding new dependencies**: if the original method needed
  three collaborators, the new module takes three collaborators
  — not "while we're at it, let's also inject a `Logger`".
- **Tightening types**: if the original took `dict | None`, the
  new module takes `dict | None`. Saving a type-check fight for
  later is fine; smuggling it into an extraction PR is not.
- **Renaming public methods**: keep the verb. If the original
  was `recall_relevant_memories`, the new method is
  `recall(...)` on `MemoryRecallCoordinator` — same noun, same
  verb. The class name conveys the noun, the method name conveys
  the verb.

## When you discover a behavior bug mid-extraction

You **will** find bugs. The pattern:

1. Stop extracting.
2. Land the extraction PR **with the bug preserved verbatim**.
   The new module's tests pin the buggy behavior so the next PR
   can fix it cleanly.
3. Open a follow-up issue or PR that fixes the bug and updates
   the now-named tests.

This keeps the diffs reviewable. Reviewers can spot "this looks
wrong" in the new module and confirm it's preserved from the
original via `git blame`.

## Commit / PR templates

### Commit message

```
refactor(<area>): extract <surface> into <ClassName>

<Nth> slice of <Phase>. <One-paragraph description of what was
tangled together and why the extraction helps.>

What moves out
  * `<path/to/new_module.py>` -- new `<ClassName>` constructed
    from <list collaborators>.
  * Public API: <list public methods>.
  * <Notable side effects preserved: metadata keys, log levels,
    fallback behaviors.>

What changes in `<god_file>.py`
  * `__init__` instantiates `self._<name>` from <collaborators>.
  * <N> call sites delegate to `self._<name>.<method>(...)`.
  * <N> private methods (<L> lines total) removed from the file.

Net diff: <before> -> <after> lines (-<delta> this PR).
Cumulative since <Phase>: <original> -> <current> (-<%>).

Tests
  * `tests/unit/test_<slice>.py` (new, <N> cases) covers <surface
    summary>: <bullet list of coverage areas>.
  * All previously green suites stay green: <N> passed (was <M>
    before, +<delta> new).

CI
  * Ruff clean.
  * Mypy --strict clean on the new module.

No behavior changes intended.
```

### PR body

Same structure as the commit body, plus:

```
## Review & Testing Checklist for Human

- [ ] Skim <new_module>.py against the deleted method
  (`git show <commit> -- <god_file>` shows the deletion). <Note
  any verbatim-preserved quirks.>
- [ ] Confirm <specific side effect> is preserved by
  `test_<name>` in the new file.

### Test plan

<commands from "Validation gates">

### Notes

- <Phase> PR chain: #<a> -> #<b> -> ... -> this PR. Next slice
  in this chain is <next slice candidate>.
- <Any deferred follow-ups discovered during extraction.>
```
