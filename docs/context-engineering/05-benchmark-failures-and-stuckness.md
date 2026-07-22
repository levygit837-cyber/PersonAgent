# Benchmark Failures and Agent Stuckness

**Date:** 2026-05-30  
**Source:** 6 exploration benchmark runs across 3 projects (PersonAgent, pydantic, opencode)

---

## Results Summary

| Metric | Value |
|--------|-------|
| Benchmarks run | 6 |
| Success rate | 33.3% (2/6) |
| Failure rate | 66.7% (4/6) |
| #1 failure mode | Agent stuckness |
| Total tokens burned | ~3.9M |

---

## Failure Breakdown

### Failure Mode: Agent Stuckness (4/6 failures)

The agent enters a loop where it repeatedly calls the same tools without making progress. Common patterns:

**Pattern A: Identical tool call repetition**
```
Turn 8: Grep("class.*Model")
Turn 9: Grep("class.*Model")   ← same query
Turn 10: Grep("class.*Model")  ← same query
Result: No new files discovered. Agent is stuck.
```

**Pattern B: Alternating between two actions**
```
Turn 12: Read("src/models.py")
Turn 13: Grep("def validate")
Turn 14: Read("src/models.py")  ← already read
Turn 15: Grep("def validate")    ← already searched
Result: Ping-pong between two known locations.
```

**Pattern C: No new files in window**
```
Turn 20-28: Only reads files already seen in turns 1-19
No file path in turns 20-28 is new
Result: "No new files read in last 8 steps" = stuck
```

---

## Why Agents Get Stuck

### 1. Full History Contains Failed Attempts

The agent sees its own mistakes in the conversation history and repeats them:

```
[Assistant, Turn 5]: I'll search for the config file
[Tool result]: No matches for "config.py"

[Assistant, Turn 15]: Let me search for the config file
[Tool result]: No matches for "config.py"
```

The model sees that it tried "config.py" 10 turns ago and got nothing. But without progress tracking, it tries again.

### 2. No Exploration Progress Tracking

The harness does not track:
- Files already read
- Patterns already searched
- Directories already listed
- Tools already called with these arguments

```python
# What exists: none of this
visited_files: set[str] = set()
searched_patterns: set[str] = set()
explored_directories: set[str] = set()
```

Without this state, the agent has no memory of what it already tried.

### 3. Tool Results Are Not Actionable

When a tool returns "No matches" or an empty list, the agent does not learn from it:

```
[Grep result]: "No matches found for 'validate_email'"
[Agent response]: "Let me try a different pattern: 'validate_email'"
```

The agent receives "no matches" but does not update its internal model of the codebase.

### 4. No Retry Injection Works

The harness attempts to break stuckness by adding prompts like:
- "You seem stuck. Try a different approach."
- "Don't repeat the same search."

**These do not work** because:
- The model sees 10+ turns of context showing it doing exactly what the prompt says not to do
- The contradiction between the prompt instruction and the conversation history confuses the model
- The model defaults to its recent pattern (repetition) rather than the abstract instruction

---

## Specific Benchmark Failures

### Benchmark 1: PersonAgent Token Management
- **Status:** Failed (stuck)
- **Turns before stuck:** 14
- **Stuck pattern:** Repeated `Grep("token")` with different variations
- **Token burn:** ~580K

### Benchmark 2: Pydantic Model Validation
- **Status:** Failed (stuck)
- **Turns before stuck:** 11
- **Stuck pattern:** Alternating `Read("validators.py")` and `Grep("@validator")`
- **Token burn:** ~420K

### Benchmark 3: Opencode CLI Commands
- **Status:** Failed (stuck)
- **Turns before stuck:** 18
- **Stuck pattern:** `Glob("**/*.py")` → read 3 files → repeat
- **Token burn:** ~890K

### Benchmark 4: PersonAgent Context Building
- **Status:** Failed (stuck)
- **Turns before stuck:** 9
- **Stuck pattern:** `Read("context_builder.py")` at different offsets
- **Token burn:** ~310K

### Benchmark 5: Pydantic Config System
- **Status:** Success
- **Turns:** 8
- **Token burn:** ~180K

### Benchmark 6: Opencode Prompts
- **Status:** Success
- **Turns:** 6
- **Token burn:** ~95K

---

## Why Successful Benchmarks Succeeded

The 2 successful benchmarks had one thing in common: **the target was found early** (within 3-4 turns). Once the agent found the relevant file, it completed the task before entering a stuck loop.

| Benchmark | Target Found At | Result |
|-----------|----------------|--------|
| Pydantic Config | Turn 3 | Success |
| Opencode Prompts | Turn 2 | Success |
| PersonAgent Token | Turn 8 | Failure (stuck at 14) |
| Pydantic Validation | Turn 6 | Failure (stuck at 11) |

**Key insight:** If the agent doesn't find the target within ~5 turns, it enters exploration mode. Without progress tracking, exploration mode becomes stuck mode.

---

## The Connection to Token Burn

Stuckness and token burn are **the same problem**:

1. Agent gets stuck in a loop
2. Each loop iteration adds tool results to history
3. History grows linearly with each failed attempt
4. Larger history = more tokens per turn
5. More tokens = slower responses = more time to get unstuck
6. More time = more loop iterations

**It's a positive feedback loop:**
```
Stuck → Repeat tool → History grows → Tokens increase → Slower → More stuck
```

The 4 failed benchmarks burned 2.2M tokens. The 2 successful benchmarks burned 275K tokens.

**Failed benchmarks burn 8× more tokens than successful ones.**

---

## Fixes for Stuckness

### Fix 1: Exploration Progress Tracking

Track what the agent has already done and inject it into the prompt:

```python
class ExplorationState:
    def __init__(self):
        self.visited_files: set[str] = set()
        self.searched_patterns: set[str] = set()
        self.explored_dirs: set[str] = set()

    def to_prompt(self) -> str:
        return f"""
Exploration progress so far:
- Files already read ({len(self.visited_files)}):
  {', '.join(sorted(self.visited_files))}
- Patterns already searched ({len(self.searched_patterns)}):
  {', '.join(sorted(self.searched_patterns))}
- Directories already explored ({len(self.explored_dirs)}):
  {', '.join(sorted(self.explored_dirs))}

DO NOT repeat any of the above. Try something new.
"""
```

### Fix 2: Stuck Detection and Intervention

Detect stuckness and force a different approach:

```python
class StuckDetector:
    def __init__(self, window: int = 5):
        self.window = window
        self.actions: deque = deque(maxlen=window)

    def is_stuck(self) -> tuple[bool, str]:
        if len(self.actions) < self.window:
            return False, ""

        # Check for identical repetition
        signatures = [a.signature for a in self.actions]
        if len(set(signatures)) == 1:
            return True, f"Repeated identical action: {signatures[0]}"

        # Check for no new files
        files_read = set()
        for a in self.actions:
            if a.tool == "Read":
                files_read.add(a.args.get("path", ""))
        if len(files_read) < 2:
            return True, "No new files in recent window"

        # Check for token waste without progress
        tokens_burned = sum(a.tokens_consumed for a in self.actions)
        if tokens_burned > 50_000:
            return True, f"Burned {tokens_burned} tokens with no clear progress"

        return False, ""
```

When stuck is detected:
1. Inject "You are stuck. Try a completely different approach."
2. Or: Force a `Glob("**/*")` to see the full directory structure
3. Or: Halt and report partial findings

### Fix 3: Tool Result Deduplication

Before executing a tool, check if it was already called with the same arguments:

```python
# Before executing tool
if (tool_name, json.dumps(arguments, sort_keys=True)) in self.executed_tools:
    return "[You already ran this tool with these exact arguments. The result was the same.]"
```

### Fix 4: Directory Structure First

Instead of letting the agent explore blindly, give it the full directory structure upfront:

```python
# Turn 0 (before user task)
tree = generate_directory_tree(workspace)
messages.append({
    "role": "system",
    "content": f"Project structure:\n{tree}"
})
```

This prevents the `Glob("**/*.py")` → read random files → get stuck pattern.

---

## Key Insight

**Stuckness is not a model problem. It's a system problem.**

The model is doing exactly what the system allows it to do:
- The system allows repeating the same tool call → model repeats it
- The system has no progress tracking → model has no memory of what it tried
- The system resends failed attempts in history → model learns from failures poorly

The fix is not "make the model smarter." The fix is "give the model the information it needs to not get stuck."

---

## Related Files

- Benchmark harness: `benchmarks/exploration-harness/harness.py`
- Stuck detection: `benchmarks/exploration-harness/harness.py:detect_stuck()`
- Trace harness (for token logging): `benchmarks/exploration-harness/token_trace_harness.py`
