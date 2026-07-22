# tree-of-thoughts vs thought-based-reasoning: Side-by-Side Comparison

## The Task (Same for Both)

> Design a REST API for user management (CRUD + auth).

---

## Approach A: thought-based-reasoning (Single-Agent CoT)

**What happens:** One agent receives the task and is told to "think step by step." It produces ONE solution with reasoning inline.

**Prompt used:**
```
Design a REST API for user management (CRUD + auth).

Let's think step by step.
```

**Typical output structure:**
```
Step 1: Identify resources
- Users are the core resource
- Need endpoints for CRUD operations
- Need authentication endpoints

Step 2: Design URL structure
- GET /users — list users
- GET /users/{id} — get user
- POST /users — create user
- PUT /users/{id} — update user
- DELETE /users/{id} — delete user
- POST /auth/login — authenticate
- POST /auth/register — register

Step 3: Define authentication strategy
- JWT tokens with refresh token rotation
- Password hashing with bcrypt

[...single solution continues...]
```

**Result:** One complete API design. Quality depends entirely on that single agent's first intuition.

---

## Approach B: tree-of-thoughts (Multi-Agent Exploration)

**What happens:** Multiple agents explore DIFFERENT regions of the solution space, judges score them, and the best is selected or synthesized.

### Phase 1: Exploration (3 agents in parallel)

**Agent A proposes:**
- Approach 1: Resource-based REST with nested routes (prob: 0.85)
- Approach 2: Flat REST with simple endpoints (prob: 0.80)
- Approach 3: gRPC with REST gateway (prob: 0.40)

**Agent B proposes:**
- Approach 1: Pure REST, HATEOAS-driven (prob: 0.75)
- Approach 2: Hybrid REST + GraphQL (prob: 0.60)
- Approach 3: Monolithic API with service-oriented internals (prob: 0.70)

**Agent C proposes:**
- Approach 1: REST+GraphQL hybrid (prob: 0.65)
- Approach 2: CQRS with separate read/write APIs (prob: 0.50)
- Approach 3: Event-sourced API with projections (prob: 0.30)

### Phase 2: Pruning (3 judges score all proposals)

Judge 1 votes: Resource-based REST, Pure REST, Monolithic  
Judge 2 votes: Pure REST, Hybrid, Resource-based REST  
Judge 3 votes: Resource-based REST, REST+GraphQL, Pure REST

**Selected for expansion:**
1. Resource-based REST (8 pts) — Agent A's approach
2. Pure REST (7 pts) — Agent B's approach
3. Monolithic with SO internals (4 pts) — Agent B's approach

### Phase 3: Expansion (3 agents build full solutions)

- **Solution A:** Full resource-based design with nested routes, JWT auth, rate limiting
- **Solution B:** Flat REST design with simple endpoints, session auth, pagination
- **Solution C:** Monolithic API with internal services, OAuth2, caching layer

### Phase 4: Evaluation (3 judges score full solutions)

```
Judge 1: VOTE=A, SCORES: A=4.2, B=3.8, C=3.4
Judge 2: VOTE=B, SCORES: A=3.9, B=4.1, C=3.5
Judge 3: VOTE=A, SCORES: A=4.3, B=3.6, C=3.2
```

### Phase 5: Synthesis (combine best elements)

**Final output:**
- Resource-based structure (from A) — judges praised discoverability
- Max 2-level nesting (from B) — judges criticized A's deep nesting
- Internal services pattern (from C) — clean separation of concerns

---

## Key Differences Visualized

```
thought-based-reasoning (CoT):
┌─────────────────┐
│   Task Input    │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Single Agent   │ ← "Let's think step by step"
│  Generates ONE  │
│   reasoning     │
│   chain +       │
│   solution      │
└────────┬────────┘
         ▼
┌─────────────────┐
│  Single Output  │
└─────────────────┘


tree-of-thoughts (Multi-Agent):
┌─────────────────┐
│   Task Input    │
└────────┬────────┘
         ▼
    ┌────┴────┬────────┐
    ▼         ▼        ▼
┌───────┐ ┌───────┐ ┌───────┐
│Agent A│ │Agent B│ │Agent C│ ← Each explores DIFFERENT
│3 props│ │3 props│ │3 props│   regions of solution space
└───┬───┘ └───┬───┘ └───┬───┘
    └────┬────┘         │
         ▼              │
    ┌─────────┐         │
    │ 3 Judges│ ← Score & vote for top 3
    └────┬────┘         │
         ▼              │
    ┌─────────┐         │
    │Expand 3 │ ← Build full solutions
    │solutions│         │
    └────┬────┘         │
         ▼              │
    ┌─────────┐         │
    │ 3 Judges│ ← Score full solutions
    └────┬────┘         │
         ▼              │
    ┌─────────┐         │
    │Synthesis│ ← Combine best elements
    └────┬────┘         │
         ▼              │
┌─────────────────┐     │
│  Final Output   │ ← Evidence-based, not first-guess
└─────────────────┘
```

---

## When to Use Which

| Scenario | Use |
|---|---|
| Quick decision, deadline tight | `thought-based-reasoning` — single CoT call is fast |
| Problem is well-understood, just need careful reasoning | `thought-based-reasoning` — CoT or PAL is sufficient |
| Don't know which architecture/approach is best | `tree-of-thoughts` — explores multiple approaches |
| High-stakes, hard to undo decision | `tree-of-thoughts` — judges catch blind spots |
| Creative task with no obvious solution | `tree-of-thoughts` — diversity of proposals helps |
| Math/computation problem | `thought-based-reasoning` — PAL (code generation) |
| Need external tools (search, APIs) | `thought-based-reasoning` — ReAct pattern |
| Iterative improvement from failures | `thought-based-reasoning` — Reflexion pattern |

---

## Token Cost Reality Check

| | thought-based-reasoning | tree-of-thoughts |
|---|---|---|
| Agent calls | 1 | 10+ (3 explorers + 2 meta-judges + 6 judges + 1 synthesizer) |
| Typical tokens | ~2-5K | ~50-150K |
| Time | Seconds | Minutes |
| Quality guarantee | Medium (one mind, one try) | High (multiple minds, peer review) |

**Rule of thumb:** If the wrong answer costs more than ~$0.50 in downstream problems, use `tree-of-thoughts`. If you just need to think through something clearly, use `thought-based-reasoning`.
