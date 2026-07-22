# Context Collapse: Category-Based Timeline Summaries

Date: 2026-05-30
Status: Proposed

## Overview

This document proposes an alternative summary architecture for **Context Collapse** (Layer 4) that replaces the traditional "one unified summary per commit" with **multiple categorized summaries organized by timeline**. Each summary is typed by category (code, task, test, error, etc.) and linked via metadata, creating a navigable, token-efficient representation of collapsed conversation groups.

This approach is designed specifically for Context Collapse's grouped-turn model, where a single commit may span 15-30 turns of heterogeneous activity (code changes, tests, debugging, user requests). A unified summary forces all this information into a single narrative blob. Category-based summaries preserve the semantic structure while reducing token usage.

---

## The Problem with Unified Summaries

A unified summary for a group of turns must capture:
- Code changes and file modifications
- User goals and task progress
- Errors encountered and how they were fixed
- Tests written or run
- Research or exploration done
- Decisions made

All in a single block of text. This creates:

1. **Low scannability** — the model must read the entire summary to find relevant parts
2. **Information mixing** — code snippets sit next to user requests sit next to error logs
3. **No selective expansion** — expanding the unified summary brings back the entire group
4. **Narrative overhead** — transitions between topics consume tokens without adding information

---

## Core Concept: Category-Based Timeline Summaries

Instead of one summary per commit, produce **multiple typed summaries** — one per relevant category — each containing only information belonging to that category.

### Key Principles

1. **Chronological within category**: Within each category, summaries appear in timeline order
2. **Sparse categories**: Only categories with relevant content are emitted for a given commit
3. **Typed headers**: Each summary has a category prefix `[CodeSummary A]`, `[TaskSummary A]`, etc.
4. **Metadata linking**: Summaries reference related summaries across categories and commits
5. **Timeline ordering across commits**: `[CodeSummary A]` from Commit 1 precedes `[CodeSummary B]` from Commit 2

### Visual Representation

```
Commit 1 (Turns 1-15):
  [CodeSummary A]    → Created jwt_handler.py, token_rotation.py
  [TaskSummary A]    → Implement JWT auth with token rotation
  [ChangeSummary A]  → Files: +jwt_handler.py, +token_rotation.py, ~auth.py

Commit 2 (Turns 16-30):
  [TestSummary A]    → test_auth.py: 15 tests for login/logout/refresh
  [CodeSummary B]    → Updated API routes, added /auth/refresh endpoint
  [TaskSummary B]    → Fixed edge cases: token expiry, concurrent refresh race
  [ErrorSummary A]   → Race condition in refresh: fixed with atomic compare-and-swap

Commit 3 (Turns 31-40):
  [CodeSummary C]    → Refactored middleware to use new auth module
  [DecisionSummary A] → Decided to keep session fallback for legacy routes
```

**What the LLM sees:**
```
[CodeSummary A] Created jwt_handler.py...
[CodeSummary B] Updated API routes...
[CodeSummary C] Refactored middleware...
[TaskSummary A] Implement JWT auth...
[TaskSummary B] Fixed edge cases...
[DecisionSummary A] Decided to keep session fallback...
[TestSummary A] test_auth.py: 15 tests...
[ErrorSummary A] Race condition in refresh...
[ChangeSummary A] Files: +jwt_handler.py...
```

The LLM sees a **flat sequence** of typed summaries. Categories can be ordered strategically (e.g., Code first, then Tasks, then Decisions) to match how the model reasons.

---

## Comparison: Unified vs Categorized Summaries

### Scenario: 30-turn refactoring session

**Turns 1-5:** Read `auth.py`, `user_service.py`, `middleware.py`  
**Turns 6-10:** Created `jwt_handler.py`, `token_rotation.py`  
**Turns 11-15:** Refactored `login()`, added refresh logic  
**Turns 16-20:** Wrote tests in `test_auth.py`, `test_tokens.py`  
**Turns 21-25:** Updated API routes, added middleware integration  
**Turns 26-30:** Fixed edge cases (race condition, expiry), ran full test suite

---

### Approach A: Unified Summary (Traditional)

**Commit 1 (Turns 1-15):**
```
[Summary] Previously we explored the authentication system by reading auth.py,
user_service.py, and middleware.py to understand the current session-based
flow. We identified that JWT tokens would replace session cookies for better
scalability. We created jwt_handler.py (200 lines) implementing encode/decode
with HS256 signing, 15-minute expiry, and audience validation. We created
token_rotation.py (150 lines) handling refresh token generation, storage
interface, and token family tracking. We refactored login() in auth.py
replacing session creation with JWT access token + refresh token response.
The user_service.py imports were updated. Full code sections:
[jwt_handler.py - 200 lines]
[token_rotation.py - 150 lines]
[auth.py diff - 80 lines]
```
**→ ~10K-14K tokens**

**Commit 2 (Turns 16-30):**
```
[Summary] We wrote comprehensive tests in test_auth.py (15 tests covering
login, logout, and refresh flows) and test_tokens.py (8 tests for rotation
and expiry edge cases). We updated API routes adding /auth/refresh endpoint
and integrated the new auth system into middleware.py. During testing we
encountered a race condition in concurrent refresh requests causing token
reuse. This was fixed by implementing atomic compare-and-swap in
token_rotation.py. We also handled edge cases where tokens expire mid-request.
The full test suite passes (142 tests). Files modified:
[test_auth.py - 180 lines]
[test_tokens.py - 120 lines]
[middleware.py diff - 60 lines]
```
**→ ~8K-12K tokens**

**Total in context:** ~18K-26K tokens for two summaries

**When agent expands Commit 1:** Gets back all 50K+ tokens of turns 1-15
**When agent needs only the JWT handler code:** Must expand entire Commit 1 and search through 50K tokens

---

### Approach B: Category-Based Summaries (Proposed)

**Commit 1 (Turns 1-15):**
```
[CodeSummary A] Created jwt_handler.py: encode/decode, HS256, 15min expiry,
audience validation. Created token_rotation.py: refresh generation, storage
interface, token family tracking. Refactored auth.py: login() now returns
JWT access + refresh tokens instead of session cookie.
→ ~600 tokens

[TaskSummary A] Goal: Implement JWT authentication system with token rotation
replacing session-based auth.
→ ~150 tokens

[ChangeSummary A] New: jwt_handler.py (200 loc), token_rotation.py (150 loc).
Modified: auth.py (login refactored), user_service.py (imports updated).
→ ~200 tokens
```
**Commit 1 total: ~950 tokens**

**Commit 2 (Turns 16-30):**
```
[TestSummary A] test_auth.py: 15 tests (login/logout/refresh flows).
test_tokens.py: 8 tests (rotation, expiry edge cases). All passing.
→ ~350 tokens

[CodeSummary B] Updated API routes: added /auth/refresh endpoint. Integrated
new auth into middleware.py (request handler now validates JWT).
→ ~300 tokens

[TaskSummary B] Fixed edge cases: token expiry during request, concurrent
refresh race condition. Full suite: 142 tests passing.
→ ~250 tokens

[ErrorSummary A] Race condition in concurrent refresh: token reuse detected.
Fixed with atomic compare-and-swap in token_rotation.py:refresh().
→ ~300 tokens
```
**Commit 2 total: ~1,200 tokens**

**Total in context:** ~2,150 tokens for two commits (vs 18K-26K unified)

**When agent expands [CodeSummary A]:** Gets only the code-related turns (~20K tokens from turns 6-10, 11-15)  
**When agent needs only the JWT handler:** Expands [CodeSummary A] and sees focused code content  
**When agent needs to understand the race condition:** Expands [ErrorSummary A] directly

---

### Direct Comparison Table

| Aspect | Unified Summary | Category-Based |
|--------|-----------------|----------------|
| Tokens per commit | 8K-15K | 1K-2K (sparse categories) |
| Total for 2 commits | 18K-26K | ~2,150 |
| Scannability | Low (mixed content) | High (typed headers) |
| Selective expansion | No (all-or-nothing) | Yes (by category) |
| Information density | Medium (narrative overhead) | High (focused per category) |
| Chronological clarity | Linear narrative | Explicit within each type |
| Cross-category links | Implicit in text | Explicit via metadata |

---

## Taxonomy of Categories

### Proposed Category Set

| Category | Description | When Present |
|----------|-------------|--------------|
| `CodeSummary` | Code changes, file edits, refactors, new files | When files were modified or created |
| `TaskSummary` | Goals, objectives, what the user asked for | When user made a request or goal was stated |
| `TestSummary` | Tests written, test results, coverage changes | When tests were created or executed |
| `ErrorSummary` | Errors encountered, debugging steps, fixes applied | When errors or exceptions occurred |
| `DecisionSummary` | Architectural decisions, design choices, trade-offs | When explicit decisions were made |
| `ResearchSummary` | Exploration, investigation, grep/read results | When exploring unfamiliar code or docs |
| `ChangeSummary` | File inventory: what changed (new/modified/deleted) | Always present as lightweight index |
| `StateSummary` | Current state, progress tracking, checklist updates | When tracking multi-step progress |

### Classification Strategy

**Option 1: Per-turn classification**
- Each turn is classified into primary category
- Turns in same category are grouped into a single summary
- **Pros:** Accurate, handles hybrid turns well
- **Cons:** Requires classification step (LLM call or heuristic)

**Option 2: Content-based auto-classification**
- Look at tool calls: `file_edit` → CodeSummary, `test` → TestSummary
- Look at patterns: error text → ErrorSummary, user question → TaskSummary
- **Pros:** Cheap, deterministic
- **Cons:** May miss nuances (e.g., user request that includes code review)

**Option 3: Hybrid classification**
- Use heuristics for initial classification
- Use lightweight LLM call only for ambiguous turns
- **Pros:** Balance of accuracy and cost
- **Cons:** More complex implementation

### Hybrid Turns

A single turn may contain multiple category types. Example: user says "fix the auth bug and add tests for it."

**Resolution:**
- Primary classification based on dominant activity
- Or emit multiple summary entries: `[CodeSummary B]` + `[TestSummary B]` from same turn range
- Metadata links them: `[CodeSummary B](fixes:[ErrorSummary A], tests:[TestSummary B])`

---

## Expansion Mechanics (Accepted)

This section documents the **accepted** expansion mechanism for Category-Based Context Collapse.

### Core Mechanism

The model can request to see the **full content** of any collapsed section. This is implemented as a tool available to the agent.

### Expansion Tool

```typescript
interface ExpandContextTool {
  name: "expand_context";
  parameters: {
    section_id: string;        // e.g., "commit-1:CodeSummary-A" or "commit-2:TaskSummary-B"
    depth?: "summary" | "full"; // "summary" returns just the category summary
                                // "full" replaces with original message group
    reason?: string;            // Why the model wants to expand (for logging)
  };
}
```

### How It Works

1. **By default**: `projectView()` returns only category summaries for collapsed commits
2. **Model calls `expand_context`**: Specifies which summary to expand
3. **System response**:
   - Replaces that summary in the context with the **original messages** from the Collapse Store
   - OR injects the original messages immediately after the summary (keeping summary as header)
   - Marks the section as "expanded" for this turn
4. **Next turn**: Expanded sections are **re-collapsed** (summary only) unless the model calls `expand_context` again

### Selective Partial Expansion

The killer feature: the model can expand **specific categories** without bringing back the entire commit.

```
Model sees:
  [CodeSummary A] Created jwt_handler.py...
  [CodeSummary B] Updated API routes...
  [ErrorSummary A] Race condition in refresh...

Model thinks: "I need to see the code that fixed the race condition"
Model calls: expand_context("commit-2:ErrorSummary-A", depth="full")

System injects:
  [ErrorSummary A] Race condition in refresh...
  
  [ORIGINAL CONTENT — turns 26-28 where race condition was debugged and fixed]
  [User] The concurrent refresh seems to reuse tokens
  [Assistant] Let me check token_rotation.py...
  [Tool] Read token_rotation.py → ...
  [Assistant] I see — the refresh logic doesn't check if token was already used
  [Tool] Edit token_rotation.py → added atomic CAS check
  ...

Other categories (CodeSummary B, TestSummary A) remain collapsed as summaries.
```

### Re-Compaction Policy

Expanded sections automatically collapse again based on:
- **Turn-based**: After N turns (configurable, default 3-5)
- **Token-based**: When context reaches secondary threshold (e.g., 85% of window)
- **Explicit collapse**: Model can call `collapse_context(section_id)` to free tokens

---

## Linked Sessions: Graph Structure via Metadata

### The Problem with Flat Layouts

If we just list summaries linearly, the model loses the relationships between them:
- The code in `[CodeSummary B]` implements the goal in `[TaskSummary A]`
- The tests in `[TestSummary A]` verify the code in `[CodeSummary A]`
- The fix in `[ErrorSummary A]` modifies the code in `[CodeSummary B]`

### Solution: Metadata References

Each summary contains metadata linking it to related summaries. The LLM sees these links inline.

### Link Format

```
[CodeSummary B](
  related: [TaskSummary A], [TestSummary A];
  implements: [TaskSummary A];
  tested_by: [TestSummary A];
  modified_by: [ErrorSummary A]
)
```

**What the LLM actually sees:**
```
[CodeSummary B] Updated API routes: added /auth/refresh endpoint. Integrated
new auth into middleware.py.
  → Related: [TaskSummary A], [TestSummary A]
  → Implements: [TaskSummary A]
  → Tested by: [TestSummary A]

[TaskSummary A] Goal: Implement JWT authentication system with token rotation
  → Implemented by: [CodeSummary A], [CodeSummary B]
  → Tests: [TestSummary A]

[TestSummary A] test_auth.py: 15 tests (login/logout/refresh flows)
  → Tests code: [CodeSummary A], [CodeSummary B]
  → Related task: [TaskSummary A]

[ErrorSummary A] Race condition in concurrent refresh: token reuse detected.
  → Affects: [CodeSummary B]
  → Fixed in: token_rotation.py
```

### Relationship Types

| Relation | Meaning | Direction |
|----------|---------|-----------|
| `implements` | Code implements a task/decision | Code → Task/Decision |
| `tested_by` | Code is tested by tests | Code → Test |
| `tests` | Tests verify code | Test → Code |
| `fixes` | Fix resolves an error | Error → Code |
| `caused_by` | Error caused by code | Error → Code |
| `related` | Semantically related (loose) | Any → Any |
| `depends_on` | Requires prior work | Any → Any |
| `supersedes` | Replaces earlier version | New → Old |

### Graph Navigation

The model doesn't "traverse" a graph structurally — it sees links in text and can request expansions:

```
Model: "What task does [CodeSummary B] implement?"
System: "[CodeSummary B] implements [TaskSummary A]"
Model: expand_context("commit-1:TaskSummary-A")
```

This is **implicit graph traversal** via text references and expansion tool.

### Cross-Commit Linking

Links can span commits:
```
[CodeSummary C] Refactored middleware to use new auth module
  → Depends on: [CodeSummary A] (commit-1), [CodeSummary B] (commit-2)
  → Related decision: [DecisionSummary A] (commit-3)
```

---

## Prompt Design for Category Summaries

### Open Design Decision

The prompt for generating category summaries is **not** assumed to be the same as Auto-Compact's 9-section prompt. Each category may have its own prompt optimized for that type of content.

### Proposed Prompt Strategy

**Base prompt** (fallback, similar to Auto-Compact but scoped to group):
```
Summarize the following conversation turns (turns X-Y) into a concise
summary focused on [CATEGORY]. Include only information relevant to
[CATEGORY]. Omit unrelated content. Be specific but brief.
```

**Specialized prompts per category:**

`CodeSummary`:
```
Extract all code changes from turns X-Y. For each change:
- File modified/created
- What changed (function, class, line range)
- Why it changed (if stated)
Do NOT include: user requests, errors, test results, decisions.
Format: "File: change description"
```

`TaskSummary`:
```
Extract all goals, user requests, and objectives from turns X-Y.
What was the user trying to accomplish? What did the agent commit to do?
Do NOT include: implementation details, code, errors.
Format: "Goal: description (status)"
```

`ErrorSummary`:
```
Extract all errors, exceptions, and debugging steps from turns X-Y.
For each error:
- What failed
- Root cause (if identified)
- How it was fixed
Format: "Error: description → Fix: solution"
```

`TestSummary`:
```
Extract all test-related activity from turns X-Y.
For each test file:
- What tests were added/modified
- What they test
- Results (pass/fail)
Format: "test_file.py: N tests (what they test) — result"
```

`DecisionSummary`:
```
Extract all explicit decisions, trade-offs, and architectural choices
from turns X-Y. Include reasoning if stated.
Format: "Decision: choice (reasoning)"
```

### Cost of Multiple Prompts

Generating 3-4 category summaries per commit requires:
- **3-4 LLM calls** (or 1 call with structured output)
- **Total tokens generated**: May be similar to one big summary because each is focused
- **Quality**: Higher because each summary has a clear, narrow scope

**Alternative:** Single LLM call with structured output:
```json
{
  "CodeSummary": "...",
  "TaskSummary": "...",
  "TestSummary": "...",
  "ErrorSummary": "..."
}
```

---

## Simulation: Full Session with Both Approaches

### Session: Implement OAuth2 + JWT Auth

**Turns 1-10:** Research existing auth, read RFC 6749, look at current auth code  
**Turns 11-20:** Implement OAuth2 flow in `oauth_handler.py`, `token_manager.py`  
**Turns 21-30:** Write tests, hit bug in token refresh, fix it  
**Turns 31-40:** Update API routes, integrate middleware, user reviews  
**Turns 41-50:** Fix edge cases, final tests, documentation

---

### Simulation A: Unified Summary (Collapsed State)

**What the LLM sees after 50 turns (3 commits collapsed):**
```
[Summary 1] We researched OAuth2 and JWT by reading RFC 6749 and the current
auth code. We implemented the OAuth2 authorization code flow in oauth_handler.py
(300 lines) and token management in token_manager.py (250 lines). We wrote tests
for the OAuth flow and encountered a bug in token refresh where expired tokens
were incorrectly validated. We fixed this by adding expiry checking in
token_manager.py:validate(). We updated API routes and integrated the new auth
into middleware. The user reviewed and requested PKCE support. We added PKCE to
the authorization flow, fixed additional edge cases with client_id validation,
and wrote final tests. All 200 tests pass. Full code:
[oauth_handler.py - 300 lines]
[token_manager.py - 250 lines]
[test_oauth.py - 200 lines]
```
**→ ~15K tokens for one summary**

**When model needs to know about PKCE:**  
→ Must expand entire commit, get 50K+ tokens, search for "PKCE"

---

### Simulation B: Category-Based (Collapsed State)

**What the LLM sees:**
```
[ResearchSummary A] Read RFC 6749 (OAuth2 spec). Explored current auth code:
auth.py, middleware.py, user_service.py use session cookies.
→ ~300 tokens

[CodeSummary A] Created oauth_handler.py: authorization code flow, token
exchange, redirect URI validation. Created token_manager.py: JWT generation,
validation, expiry checking.
→ ~500 tokens

[TaskSummary A] Implement OAuth2 + JWT replacing session auth
  → Implemented by: [CodeSummary A]
→ ~150 tokens

[TestSummary A] test_oauth.py: 20 tests (auth flow, token exchange, expiry)
→ ~300 tokens

[ErrorSummary A] Token refresh bug: expired tokens validated as valid.
Fixed in token_manager.py:validate() — added explicit expiry check.
→ ~350 tokens

[CodeSummary B] Updated API routes: OAuth endpoints (/auth/authorize,
/auth/token, /auth/refresh). Integrated middleware with JWT validation.
→ ~400 tokens

[TaskSummary B] User requested PKCE support for mobile clients
  → Implemented by: [CodeSummary C]
→ ~200 tokens

[CodeSummary C] Added PKCE to authorization flow: code_challenge, code_verifier
validation. Fixed client_id validation edge case (empty string).
→ ~450 tokens

[TestSummary B] Final tests: 200 tests passing. Added PKCE tests,
client_id edge case tests.
→ ~350 tokens

[DecisionSummary A] Decided to keep session fallback for legacy routes
  → Implemented: [CodeSummary B]
→ ~200 tokens
```
**Total: ~3,200 tokens for entire collapsed history**

**When model needs to know about PKCE:**  
→ `expand_context("commit-3:TaskSummary-B")` → sees user request  
→ `expand_context("commit-3:CodeSummary-C")` → sees PKCE implementation  
**Total expansion: ~2K tokens, not 50K**

**When model needs to debug token refresh:**  
→ `expand_context("commit-2:ErrorSummary-A")` → sees full debugging context  
**Targeted expansion: ~5K tokens, focused on the bug**

---

## Implementation Considerations

### Storage Format

```typescript
interface CategorySummary {
  id: string;              // e.g., "commit-1:CodeSummary-A"
  commit_id: string;       // Which commit this belongs to
  category: CategoryType;  // "CodeSummary", "TaskSummary", etc.
  sequence: number;        // A, B, C within category
  content: string;         // The summary text
  metadata: {
    related?: string[];
    implements?: string[];
    tested_by?: string[];
    fixes?: string[];
    depends_on?: string[];
  };
  token_count: number;     // Cached token count for budget calculations
  created_at: Date;
}

interface CollapseCommit {
  id: string;
  turn_range: [number, number];      // Which turns this commit covers
  summaries: CategorySummary[];     // All summaries for this commit
  original_messages: Message[];     // Full messages (in Collapse Store)
  created_at: Date;
}
```

### projectView() with Categories

```typescript
function projectView(messages: Message[], collapseStore: CollapseStore): Message[] {
  const view: Message[] = [];
  let current_turn = 0;

  for (const commit of collapseStore.commits) {
    // Add non-collapsed messages before this commit
    while (current_turn < commit.turn_range[0]) {
      view.push(messages[current_turn]);
      current_turn++;
    }

    // Add category summaries for this commit (sorted by category priority)
    for (const summary of sortByCategoryPriority(commit.summaries)) {
      view.push(createSummaryMessage(summary));
    }

    current_turn = commit.turn_range[1] + 1;
  }

  // Add remaining non-collapsed messages
  while (current_turn < messages.length) {
    view.push(messages[current_turn]);
    current_turn++;
  }

  return view;
}

function sortByCategoryPriority(summaries: CategorySummary[]): CategorySummary[] {
  const priority: Record<CategoryType, number> = {
    TaskSummary: 1,      // Goals first (context for everything else)
    DecisionSummary: 2,  // Decisions shape understanding
    CodeSummary: 3,      // Implementation details
    TestSummary: 4,      // Verification
    ErrorSummary: 5,     // Fixes and debugging
    ResearchSummary: 6,  // Background (lowest priority)
    ChangeSummary: 7,    // File inventory (reference)
    StateSummary: 8,     // Progress tracking
  };
  return summaries.sort((a, b) => priority[a.category] - priority[b.category]);
}
```

### Category Priority Rationale

1. **TaskSummary first** — gives the model the "why" before the "what"
2. **DecisionSummary second** — architectural context shapes interpretation
3. **CodeSummary third** — implementation after understanding goals
4. **TestSummary fourth** — verification of what was built
5. **ErrorSummary fifth** — fixes (usually relevant only if debugging)
6. **ResearchSummary sixth** — background knowledge
7. **ChangeSummary seventh** — file inventory (can be looked up)
8. **StateSummary eighth** — progress tracking (least often needed)

---

## Open Questions

1. **Category completeness**: Is the proposed taxonomy sufficient? Do we need `DocSummary`, `RefactorSummary`, `PerformanceSummary`?
2. **Classification accuracy**: How do we handle turns that don't fit neatly into one category?
3. **Cross-commit link generation**: Should links be auto-generated by analyzing content, or manually curated?
4. **Summary aging**: Should older summaries be "compressed" further (e.g., `[CodeSummary A]` from 10 commits ago gets a one-line version)?
5. **User vs model view**: Should the user see the same category-based view, or a more narrative UI representation?
6. **Fallback to unified**: Should the system fall back to a unified summary if category generation fails or produces low-quality results?

---

## Relation to Other Layers

| Layer | How Category-Based Collapse Interacts |
|-------|--------------------------------------|
| Layer 1 (Tool Result Budget) | Still caps individual tool results before collapse |
| Layer 2 (Microcompact) | Can run before collapse to clear old tool results |
| Layer 3 (History Snip) | Drops oldest messages before collapse if needed |
| Layer 5 (Auto-Compact) | **Replaced** by Context Collapse when active |
| Layer 6 (Reactive Compact) | Fallback if collapse + expansion still overflow |
| Layer 7 (Session Memory) | Can pre-populate category summaries from session memory |

---

## References

- ADR 0026: Context Collapse — Correções de Entendimento e Decisões Abertas
- `layer-04-context-collapse.md`: Base Context Collapse documentation
- `layer-05-auto-compact.md`: Auto-Compact summary structure (fallback reference)
