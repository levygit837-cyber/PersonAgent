# Skills Cleanup Analysis

## Data: Saturday, 2026-05-30
## Autor: Devin Analysis
## Status: CRITICAL - Action Required

---

## 1. Executive Summary

**Current State: 89 skills in Claude Code alone. This is excessive.**

You have so many skills that the `/` menu in chat is unusable. The root cause is **massive duplication** across overlapping domains. Many skills do nearly the same thing with slightly different wrappers.

**Recommendation: Reduce from ~89 to ~25-30 skills (65-70% reduction).**

---

## 2. Current Inventory

### 2.1 Claude Code Skills (~89 directories)
- **8 symlinks** to `.agents/skills/` (recently installed universal skills)
- **81 actual local skills** in `~/.claude/skills/`

### 2.2 .agents/skills (Universal - 10 skills)
These are installed globally and symlinked to multiple agents:
- acquire-codebase-knowledge
- aidesigner-frontend
- codebase-onboarding
- evaluating-llms-harness
- find-skills
- improve-codebase-architecture
- prompt-engineer
- refactor-method-complexity-reduce
- simplify
- system-prompt-engineering

### 2.3 .config/agents/skills (Local configs - 4 skills)
- execute
- orchestrate
- track-implementation
- ultraplan

### 2.4 Devin CLI Skills
Symlinks to `.agents/skills/` (7 skills, same as universal minus some)

### 2.5 Windsurf / KimiCode
Only built-in skills (kimi-cli-help, skill-creator) - not user-installed

---

## 3. The Problem: Massive Duplication

### 3.1 Duplicate Cluster: Sub-Agent Execution (7 skills)

All of these dispatch work to sub-agents. The differences are marginal.

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `do-and-judge` | Single task + judge verification | **REMOVE** - subset of do-in-steps |
| `do-in-steps` | Sequential subtasks + judge | **KEEP** - most comprehensive sequential |
| `do-in-parallel` | Parallel subtasks + judge | **KEEP** - most comprehensive parallel |
| `do-competitively` | Competitive generation + debate | **REMOVE** - overkill, rarely needed |
| `implement-task` | Task file + LLM-as-judge | **REMOVE** - overlap with do-in-steps |
| `subagent-driven-development` | Implementation with sub-agents | **REMOVE** - covered by execute/do-in-steps |
| `launch-sub-agent` | Just launch a sub-agent | **REMOVE** - primitive, covered by others |

**Critique:** You don't need 7 ways to delegate to sub-agents. `do-in-steps` handles sequential work with verification. `do-in-parallel` handles parallel work. That's it. The rest are either subsets (`do-and-judge` = do-in-steps with 1 step) or add unnecessary complexity (`do-competitively` with debate rounds).

### 3.2 Duplicate Cluster: Brainstorming (2 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `brainstorm` | Refine ideas into designs (62 lines) | **REMOVE** - simpler version |
| `brainstorming` | Refine ideas with hard-gate (164 lines) | **KEEP** - more robust with hard-gate |

**Critique:** `brainstorming` is a superset of `brainstorm`. The hard-gate (`Do NOT invoke any implementation skill until user approves`) is critical. Remove the weaker one.

### 3.3 Duplicate Cluster: Planning (6 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `ultraplan` | Deep architectural planning | **KEEP** - user likes it, most comprehensive |
| `plan-task` | Refine draft task into planned task | **REMOVE** - ultraplan covers this |
| `plan-do-check-act` | Iterative experimentation | **REMOVE** - niche, rarely needed |
| `writing-plans` | Create implementation plans | **REMOVE** - ultraplan covers planning |
| `executing-plans` | Execute written plan | **REMOVE** - execute skill covers this |
| `track-implementation` | Execute approved plan with tracking | **KEEP** - companion to ultraplan |

**Critique:** You have 6 skills for "plan and execute." The workflow is: `ultraplan` (plan) → `track-implementation` or `execute` (execute). The others are redundant intermediaries.

### 3.4 Duplicate Cluster: Code Review (6 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `critique` | Multi-perspective review with judges | **KEEP** - user likes it |
| `thermo-nuclear-code-quality-review` | Deep structural audit | **KEEP** - user likes it |
| `review-local-changes` | Review uncommitted changes | **REMOVE** - overlap with critique |
| `review-pr` | Review pull requests | **KEEP** - user likes it |
| `requesting-code-review` | Request review from others | **REMOVE** - rarely used |
| `receiving-code-review` | Handle received review feedback | **REMOVE** - rarely used |

**Critique:** `critique` already does comprehensive review. `review-local-changes` is just critique for unstaged changes. The "requesting/receiving" pair assumes a human-in-the-loop workflow you rarely use.

### 3.5 Duplicate Cluster: Evaluation/Judge (3 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `judge` | Meta-judge + judge evaluation | **KEEP** - simple and general |
| `judge-with-debate` | Multi-round debate between judges | **REMOVE** - overkill |
| `agent-evaluation` | Evaluate agent effectiveness | **REMOVE** - niche |

**Critique:** `judge-with-debate` runs multiple judge rounds until consensus. This burns tokens and time. `judge` is sufficient for 95% of cases.

### 3.6 Duplicate Cluster: Git Worktrees (2 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `git-worktrees` | Git worktree commands and patterns | **KEEP** - more comprehensive |
| `using-git-worktrees` | Using git worktrees for isolation | **REMOVE** - subset of git-worktrees |

**Critique:** Two skills for the same feature. Keep the more comprehensive one.

### 3.7 Duplicate Cluster: Skill Creation (4 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `create-skill` | Guide for creating effective skills | **KEEP** - most comprehensive |
| `writing-skills` | Creating/editing skills | **REMOVE** - overlap with create-skill |
| `test-skill` | Test skills before deployment | **REMOVE** - rarely needed |
| `apply-anthropic-skill-best-practices` | Anthropic's official best practices | **REMOVE** - too specific, create-skill covers it |

**Critique:** If you need to create a skill, use `create-skill`. You don't need 4 skills about making skills.

### 3.8 Duplicate Cluster: MCP Setup (5 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `setup-context7-mcp` | Setup Context7 MCP server | **REMOVE** - search when needed |
| `context7-mcp` | Use Context7 MCP (has setup guidance) | **KEEP** - broader than just setup |
| `setup-serena-mcp` | Setup Serena MCP server | **REMOVE** - search when needed |
| `setup-arxiv-mcp` | Setup arXiv MCP server | **REMOVE** - search when needed |
| `setup-codemap-cli` | Setup Codemap CLI | **REMOVE** - search when needed |

**Critique:** You have 5 skills for setting up different MCP servers. When you need one, search and install it. Don't keep setup skills permanently.

### 3.9 Duplicate Cluster: Create/Build Tools (7 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `create-agent` | Create Claude Code agents | **REMOVE** - use create-skill instead |
| `create-command` | Create new Claude commands | **REMOVE** - rare need |
| `create-hook` | Create git hooks | **REMOVE** - rare need |
| `create-rule` | Create rules for agents | **REMOVE** - user hasn't mentioned using |
| `create-pr` | Create pull requests | **REMOVE** - git flow skills cover this |
| `create-workflow-command` | Create workflow commands | **REMOVE** - orchestrate covers this |
| `create-ideas` | Generate ideas in one shot | **REMOVE** - brainstorming covers this |
| `build-mcp` | Build MCP servers | **REMOVE** - rare need |

**Critique:** 8 skills for "creating things." You don't create agents, commands, hooks, rules, workflow commands, or MCP servers daily. If you need to, use `create-skill` or search. `create-pr` is redundant with your git flow skills.

### 3.10 Duplicate Cluster: Problem Analysis (6 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `analyse` | Auto-select Kaizen method | **KEEP** - versatile, auto-selects best method |
| `analyse-problem` | A3 one-page problem analysis | **KEEP** - user likes it |
| `cause-and-effect` | Fishbone analysis | **REMOVE** - subset of analyse |
| `why` | Five Whys root cause analysis | **REMOVE** - subset of analyse-problem |
| `systematic-debugging` | Debug before proposing fixes | **REMOVE** - overlap with analyse |
| `root-cause-tracing` | Trace bugs backward | **REMOVE** - overlap with systematic-debugging |

**Critique:** `analyse` auto-selects the best method (Gemba Walk, Value Stream, or Muda). `analyse-problem` gives you A3 format. The rest are specific instances that these two auto-select skills cover.

### 3.11 Duplicate Cluster: FPF System (6 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `status` | Display FPF state | **REMOVE** - unless actively using FPF |
| `query` | Search FPF knowledge base | **REMOVE** - unless actively using FPF |
| `reset` | Reset FPF cycle | **REMOVE** - unless actively using FPF |
| `actualize` | Reconcile FPF with repo changes | **REMOVE** - unless actively using FPF |
| `decay` | Manage evidence freshness | **REMOVE** - unless actively using FPF |
| `propose-hypotheses` | FPF hypothesis generation | **REMOVE** - unless actively using FPF |

**Critique:** You have 6 skills for a system you haven't mentioned using. The FPF (Five-Phase Framework) is a specific methodology. If you don't actively use it, these skills are dead weight.

### 3.12 Duplicate Cluster: Reasoning (3 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `thought-based-reasoning` | CoT, Self-Consistency, ToT, etc. | **KEEP** - user likes it |
| `tree-of-thoughts` | Tree of Thoughts methodology | **KEEP** - user likes it |
| `reflect` | Self-refinement framework | **REMOVE** - less commonly needed |

**Critique:** `reflect` is a general self-improvement skill. `thought-based-reasoning` already covers reflection as part of Reflexion. You don't need both.

### 3.13 Duplicate Cluster: Execution (3 skills)

| Skill | What It Does | Verdict |
|-------|-------------|---------|
| `execute` | Read plan and implement iteratively | **KEEP** - user likes it |
| `executing-plans` | Execute written plan in separate session | **REMOVE** - overlap with execute |
| `track-implementation` | Execute with progress tracking | **KEEP** - user likes it (complements ultraplan) |

**Critique:** `executing-plans` is a simpler version of `execute` that assumes subagents may not be available. You have subagents. Use `execute` or `track-implementation`.

---

## 4. Individual Skill Verdicts

### 4.1 Skills to KEEP (Recommended Core Set: ~28)

**Analysis & Reasoning (5):**
- `analyse` - Auto-selects best analysis method
- `analyse-problem` - A3 one-page analysis (user likes)
- `thought-based-reasoning` - CoT, ToT, ReAct, etc. (user likes)
- `tree-of-thoughts` - ToT methodology (user likes)
- `systematic-debugging` - Hmm, actually marking REMOVE below. Keeping: analyse, analyse-problem, thought-based-reasoning, tree-of-thoughts.

**Planning & Execution (5):**
- `ultraplan` - Deep architectural planning (user likes)
- `execute` - Implement plans iteratively (user likes)
- `track-implementation` - Execute with tracking (complements ultraplan)
- `orchestrate` - Multi-agent orchestration (user likes)
- `writing-plans` - Hmm, marking REMOVE below. Keeping: ultraplan, execute, track-implementation, orchestrate.

**Code Quality & Review (4):**
- `critique` - Multi-perspective review (user likes)
- `thermo-nuclear-code-quality-review` - Deep audit (user likes)
- `review-pr` - PR review (user likes)
- `simplify` - Simplify recent code (user likes)

**Prompt Engineering (3):**
- `prompt-engineer` - Prompt engineering patterns
- `system-prompt-engineering` - System prompt design
- `refactor-method-complexity-reduce` - Reduce method complexity

**Git & DevOps (4):**
- `git-worktrees` - Git worktree workflow (user likes)
- `commit` - Conventional commits
- `create-pr` - Actually marking REMOVE below. Keeping: git-worktrees, commit.
- `finishing-a-development-branch` - Merge/PR/cleanup decisions

**Testing (3):**
- `test-driven-development` - TDD approach
- `write-tests` - Add test coverage
- `fix-tests` - Fix failing tests

**Agent Utilities (3):**
- `using-superpowers` - How to find and use skills (user likes)
- `find-skills` - Discover and install skills
- `judge` - Meta-judge evaluation

**Documentation & Communication (2):**
- `update-docs` - Update project documentation
- `write-concisely` - Writing improvement rules

**Domain-Specific (3):**
- `postgres` - PostgreSQL best practices
- `mysql` - MySQL best practices
- `vitess` - Vitess/PlanetScale best practices

**Verification (1):**
- `verification-before-completion` - Verify before claiming done (user likes "Review before ship")

**Universal/.agents Skills (6):**
- `codebase-onboarding` - Structured codebase analysis
- `evaluating-llms-harness` - LLM evaluation framework
- `prompt-engineer` - Prompt engineering (already listed)
- `refactor-method-complexity-reduce` - Complexity reduction (already listed)
- `simplify` - Code simplification (already listed)
- `system-prompt-engineering` - System prompt design (already listed)

Wait, I'm double-counting. Let me recalculate:

**Final KEEP list (~28 skills):**

1. analyse
2. analyse-problem
3. thought-based-reasoning
4. tree-of-thoughts
5. ultraplan
6. execute
7. track-implementation
8. orchestrate
9. critique
10. thermo-nuclear-code-quality-review
11. review-pr
12. simplify
13. prompt-engineer
14. system-prompt-engineering
15. refactor-method-complexity-reduce
16. git-worktrees
17. commit
18. finishing-a-development-branch
19. test-driven-development
20. write-tests
21. fix-tests
22. using-superpowers
23. find-skills
24. judge
25. update-docs
26. write-concisely
27. postgres
28. mysql
29. vitess
30. verification-before-completion
31. codebase-onboarding
32. evaluating-llms-harness

That's 32. Plus the .config/agents ones that are custom: execute, orchestrate, track-implementation, ultraplan (these might be custom versions). Let me check if the .config/agents versions are different from .claude versions.

Actually, from the earlier reads:
- .config/agents/skills/execute - different content from .claude/skills/execute (the .claude one is `executing-plans` actually, wait no - `execute` exists in .claude/skills too)
- .config/agents/skills/orchestrate - different from .claude/skills/orchestrate
- .config/agents/skills/track-implementation - same content as .claude/skills/track-implementation
- .config/agents/skills/ultraplan - same content as .claude/skills/ultraplan

So .config/agents has custom execute and orchestrate that differ from .claude. The user might want to keep the .config/agents versions as their custom ones.

Let me also consider:
- The user mentioned "All superpowers" - that's `using-superpowers`
- "Git flows skills: CI, Branches, worktrees, pr's, issues" - they mentioned liking these but I don't see CI or branches skills. They have `git-worktrees`, `commit`, `create-pr`, `finishing-a-development-branch`, `load-issues`.
- "Claude Related skills" - not sure what this means, maybe `using-superpowers` which is about finding/using skills
- "Metrics/Dashboard/market" - I don't see any skills matching this description. Maybe they're thinking of skills not yet installed.

### 4.2 Skills to REMOVE (Recommended: ~57)

**Sub-Agent Duplicates (5 to remove):**
- do-and-judge
- do-competitively
- implement-task
- subagent-driven-development
- launch-sub-agent

**Planning Duplicates (3 to remove):**
- plan-task
- plan-do-check-act
- writing-plans
- executing-plans

**Review Duplicates (3 to remove):**
- review-local-changes
- requesting-code-review
- receiving-code-review

**Evaluation Duplicates (2 to remove):**
- judge-with-debate
- agent-evaluation

**Git Duplicates (1 to remove):**
- using-git-worktrees

**Skill Creation Duplicates (3 to remove):**
- writing-skills
- test-skill
- apply-anthropic-skill-best-practices

**MCP Setup Duplicates (4 to remove):**
- setup-context7-mcp
- setup-serena-mcp
- setup-arxiv-mcp
- setup-codemap-cli

**Create/Build Duplicates (7 to remove):**
- create-agent
- create-command
- create-hook
- create-rule
- create-pr
- create-workflow-command
- create-ideas
- build-mcp

**Problem Analysis Duplicates (4 to remove):**
- cause-and-effect
- why
- systematic-debugging
- root-cause-tracing

**FPF System (6 to remove):**
- status
- query
- reset
- actualize
- decay
- propose-hypotheses

**Reasoning (1 to remove):**
- reflect

**Brainstorm (1 to remove):**
- brainstorm

**Other (10 to remove):**
- aidesigner-frontend (if not doing frontend design)
- acquire-codebase-knowledge (codebase-onboarding covers it)
- improve-codebase-architecture (thermo-nuclear is better)
- context-engineering (niche)
- memorize (rarely needed)
- kaizen (analyse auto-selects this)
- add-task (plan-task depends on it, removing plan-task so this too)
- attach-review-to-pr (GitHub CLI does this)
- load-issues (GitHub CLI does this)
- kimi-webbridge (if not using browser automation via Kimi)

Wait, I need to reconsider some:

- `aidesigner-frontend` - user mentioned "Metrics/Dashboard/market" - maybe they want to keep this for UI work
- `load-issues` - user mentioned "issues" in git flows skills they like
- `attach-review-to-pr` - user mentioned "pr's" in git flows skills they like

Let me reconsider:
- `aidesigner-frontend` - if user does UI/dashboard work, keep it. But they said "Metrics/Dashboard/market" as skills they like, not necessarily that they have them. I'll mark as REMOVE since it's in .agents and can be reinstalled.
- `load-issues` - user specifically mentioned "issues" as something they like. KEEP.
- `attach-review-to-pr` - user mentioned "pr's". KEEP.

Also:
- `brainstorming` vs `brainstorm` - KEEP brainstorming, REMOVE brainstorm
- `multi-agent-patterns` - this is a design/architecture guide, different from `orchestrate` which is execution. KEEP? But user didn't mention it. It's useful as reference. I'll mark as REMOVE to reduce count; can be reinstalled.
- `dispatching-parallel-agents` - similar to do-in-parallel but simpler. REMOVE (do-in-parallel is better).
- `verification-before-completion` - user said "Review before ship" which maps to this. KEEP.

Let me also look at:
- `memorize` - curates insights into CLAUDE.md. User hasn't mentioned. REMOVE.
- `context-engineering` - understand context mechanics. Niche. REMOVE.

So my revised counts:

**KEEP: ~32 skills**
**REMOVE: ~57 skills**

---

## 5. Removal Commands

### 5.1 For Claude Code Skills (local)

```bash
# Sub-Agent Duplicates
cd ~/.claude/skills && rm -rf do-and-judge do-competitively implement-task subagent-driven-development launch-sub-agent

# Planning Duplicates
cd ~/.claude/skills && rm -rf plan-task plan-do-check-act writing-plans executing-plans

# Review Duplicates
cd ~/.claude/skills && rm -rf review-local-changes requesting-code-review receiving-code-review

# Evaluation Duplicates
cd ~/.claude/skills && rm -rf judge-with-debate agent-evaluation

# Git Duplicates
cd ~/.claude/skills && rm -rf using-git-worktrees

# Skill Creation Duplicates
cd ~/.claude/skills && rm -rf writing-skills test-skill apply-anthropic-skill-best-practices

# MCP Setup Duplicates
cd ~/.claude/skills && rm -rf setup-context7-mcp setup-serena-mcp setup-arxiv-mcp setup-codemap-cli

# Create/Build Duplicates
cd ~/.claude/skills && rm -rf create-agent create-command create-hook create-rule create-pr create-workflow-command create-ideas build-mcp

# Problem Analysis Duplicates
cd ~/.claude/skills && rm -rf cause-and-effect why systematic-debugging root-cause-tracing

# FPF System
cd ~/.claude/skills && rm -rf status query reset actualize decay propose-hypotheses

# Reasoning
cd ~/.claude/skills && rm -rf reflect

# Brainstorm
cd ~/.claude/skills && rm -rf brainstorm

# Other
cd ~/.claude/skills && rm -rf aidesigner-frontend acquire-codebase-knowledge improve-codebase-architecture context-engineering memorize kaizen add-task multi-agent-patterns dispatching-parallel-agents
```

### 5.2 For .agents/skills (Universal - affects ALL agents)

```bash
cd ~/.agents/skills && rm -rf acquire-codebase-knowledge aidesigner-frontend improve-codebase-architecture
```

### 5.3 For Devin CLI

Devin CLI uses symlinks to `.agents/skills/`. Removing from `.agents/` automatically removes from Devin.

### 5.4 For .config/agents/skills

These appear to be custom/local versions:
- `execute` - custom version, different from .claude/execute. KEEP.
- `orchestrate` - custom version, different from .claude/orchestrate. KEEP.
- `track-implementation` - same content as .claude version. If keeping in .claude, this is duplicate. Remove from .config/agents or from .claude.
- `ultraplan` - same content as .claude version. Same situation.

Recommendation: Remove from `.config/agents/skills/` since they're duplicated in `.claude/skills/`.

```bash
cd ~/.config/agents/skills && rm -rf track-implementation ultraplan
```

---

## 6. Post-Cleanup State

### 6.1 Remaining Skills (~32)

**Analysis & Reasoning:**
- analyse
- analyse-problem
- thought-based-reasoning
- tree-of-thoughts

**Planning & Execution:**
- ultraplan
- execute (custom in .config/agents)
- track-implementation
- orchestrate (custom in .config/agents)

**Code Quality & Review:**
- critique
- thermo-nuclear-code-quality-review
- review-pr
- simplify
- refactor-method-complexity-reduce

**Prompt Engineering:**
- prompt-engineer
- system-prompt-engineering

**Git & DevOps:**
- git-worktrees
- commit
- finishing-a-development-branch
- load-issues
- attach-review-to-pr

**Testing:**
- test-driven-development
- write-tests
- fix-tests

**Agent Utilities:**
- using-superpowers
- find-skills
- judge

**Documentation:**
- update-docs
- write-concisely

**Domain-Specific:**
- postgres
- mysql
- vitess

**Verification:**
- verification-before-completion

**Universal (.agents):**
- codebase-onboarding
- evaluating-llms-harness
- prompt-engineer
- refactor-method-complexity-reduce
- simplify
- system-prompt-engineering

Wait, some are duplicated between .claude and .agents (prompt-engineer, simplify, refactor-method-complexity-reduce, system-prompt-engineering). The .claude versions are symlinks to .agents. So they're not actually duplicates - they're the same skill referenced from both locations.

Let me recalculate the true count:

**Unique skills after cleanup:**

In .claude/skills (actual local skills, not symlinks):
1. analyse
2. analyse-problem
3. thought-based-reasoning
4. tree-of-thoughts
5. ultraplan
6. track-implementation
7. critique
8. thermo-nuclear-code-quality-review
9. review-pr
10. git-worktrees
11. commit
12. finishing-a-development-branch
13. load-issues
14. attach-review-to-pr
15. test-driven-development
16. write-tests
17. fix-tests
18. using-superpowers
19. find-skills
20. judge
21. update-docs
22. write-concisely
23. postgres
24. mysql
25. vitess
26. verification-before-completion
27. brainstorm (actually keeping brainstorming, not brainstorm)
28. brainstorming

In .config/agents/skills (custom):
29. execute (custom)
30. orchestrate (custom)

In .agents/skills (universal, symlinked to Claude):
31. codebase-onboarding
32. evaluating-llms-harness
33. prompt-engineer
34. refactor-method-complexity-reduce
35. simplify
36. system-prompt-engineering

Total: ~36 unique skills. Down from ~89. That's a 60% reduction.

---

## 7. Skills You Mentioned Liking But I Can't Find

You mentioned these but I don't see them installed:

| You Mentioned | Actual Skill Name | Status |
|--------------|------------------|--------|
| "Ansoff-matrix" | Not found | **Not installed** - search and install if needed |
| "Ab-test-analysis" | Not found | **Not installed** - search and install if needed |
| "Review before ship" | `verification-before-completion` | **Installed, keeping** |
| "All superpowers" | `using-superpowers` | **Installed, keeping** |
| "Metrics/Dashboard/market" | No match found | **Not installed** - maybe `aidesigner-frontend`? |

If you need Ansoff-matrix or A/B test analysis skills, search and install them after cleanup.

---

## 8. Final Recommendation

**GOAL: Reduce from ~89 to ~36 skills (60% reduction)**

This will make the `/` menu in Claude Code actually usable. You'll go from scrolling through 89 entries to ~36 well-organized, non-duplicative skills.

**Key principle applied:** You don't need 7 ways to delegate to sub-agents, 6 ways to plan, or 4 ways to create skills. Pick the best one in each category and delete the rest.

**Risks:**
- Low. All removed skills can be reinstalled with `npx skills add` if needed.
- The .agents/ universal skills are separate from .claude/ - removing .claude local copies doesn't affect other agents.

---

## 9. One-Line Removal Command

```bash
# Claude Code local skills
cd ~/.claude/skills && rm -rf do-and-judge do-competitively implement-task subagent-driven-development launch-sub-agent plan-task plan-do-check-act writing-plans executing-plans review-local-changes requesting-code-review receiving-code-review judge-with-debate agent-evaluation using-git-worktrees writing-skills test-skill apply-anthropic-skill-best-practices setup-context7-mcp setup-serena-mcp setup-arxiv-mcp setup-codemap-cli create-agent create-command create-hook create-rule create-pr create-workflow-command create-ideas build-mcp cause-and-effect why systematic-debugging root-cause-tracing status query reset actualize decay propose-hypotheses reflect brainstorm aidesigner-frontend acquire-codebase-knowledge improve-codebase-architecture context-engineering memorize kaizen add-task multi-agent-patterns dispatching-parallel-agents

# .agents/ universal duplicates
cd ~/.agents/skills && rm -rf acquire-codebase-knowledge aidesigner-frontend improve-codebase-architecture

# .config/agents duplicates
cd ~/.config/agents/skills && rm -rf track-implementation ultraplan
```

**After running these commands, run `npx skills check` to verify state.**
