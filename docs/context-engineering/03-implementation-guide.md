# Implementation Guide for PersonAgent

**Goal:** Fix token burn in the benchmark harness and improve production system scalability.

---

## Phase 1: Cap Tool Results (Immediate)

**Problem:** Tool results are unlimited. One grep can inject 203K characters (50K tokens).

**Fix:** Cap before adding to conversation history.

```python
MAX_TOOL_RESULT_CHARS = 5_000
MAX_TOOL_RESULT_LINES = 50

def cap_tool_result(result: str) -> str:
    if len(result) <= MAX_TOOL_RESULT_CHARS:
        return result
    
    # Truncate but preserve structure
    truncated = result[:MAX_TOOL_RESULT_CHARS].rstrip()
    omitted = len(result) - len(truncated)
    return f"{truncated}\n\n... [{omitted} chars truncated]"
```

**Impact:** Prevents the 50K → 65K token jump we saw in the trace.

---

## Phase 2: Add Token Counting from API Usage (Week 1)

**Problem:** PersonAgent uses rough `chars/4` estimation. Claude Code anchors to the last API response.

**Fix:** Track actual API usage and estimate only new messages.

```python
# After each API call
conversation.metadata["last_api_usage"] = {
    "prompt_tokens": response.usage.prompt_tokens,
    "completion_tokens": response.usage.completion_tokens,
    "timestamp": datetime.now(UTC).isoformat(),
}

def token_count_with_estimation(
    messages: list[Message],
    last_api_usage: dict | None = None,
) -> int:
    if last_api_usage:
        last_response_idx = find_last_assistant_message_index(messages)
        if last_response_idx is not None:
            base_count = last_api_usage["prompt_tokens"]
            new_messages = messages[last_response_idx + 1:]
            new_estimate = sum(rough_token_estimate(m) for m in new_messages)
            return base_count + new_estimate
    
    return sum(rough_token_estimate(m) for m in messages)
```

---

## Phase 3: Improve Compaction (Week 2)

**Problem:** The existing `ConversationCompactor` is basic compared to Claude's.

**Fix:** Port these specific improvements:

### 3.1 Better Summary Prompt

Replace the basic prompt with a structured 9-section variant:

```python
STRUCTURED_COMPACT_PROMPT = """\
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

Before your summary, wrap your analysis in <analysis> tags.

Your summary must include:
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections (with FULL code snippets)
4. Errors and fixes
5. Problem Solving
6. All user messages (non-tool results)
7. Pending Tasks
8. Current Work
9. Optional Next Step (with direct quotes)
"""
```

### 3.2 Circuit Breaker

```python
MAX_CONSECUTIVE_COMPACTION_FAILURES = 3

if conversation.metadata.get("compaction_failures", 0) >= MAX_CONSECUTIVE_COMPACTION_FAILURES:
    logger.warning("compaction_circuit_breaker_tripped")
    return False
```

### 3.3 Post-Compact Recovery

Restore recently read files after compaction:

```python
POST_COMPACT_MAX_FILES = 5
POST_COMPACT_TOKEN_BUDGET = 50_000
POST_COMPACT_MAX_TOKENS_PER_FILE = 5_000

def create_post_compact_attachments(tracker: FileReadTracker) -> list[dict]:
    attachments = []
    tokens_used = 0
    
    for entry in reversed(tracker.recent_reads):
        if len(attachments) >= POST_COMPACT_MAX_FILES:
            break
        
        content = entry.content
        estimated = len(content) // 4
        if estimated > POST_COMPACT_MAX_TOKENS_PER_FILE:
            content = content[:POST_COMPACT_MAX_TOKENS_PER_FILE * 4]
            content += "\n... [truncated for post-compact recovery]"
            estimated = POST_COMPACT_MAX_TOKENS_PER_FILE
        
        if tokens_used + estimated > POST_COMPACT_TOKEN_BUDGET:
            break
        
        attachments.append({
            "role": "system",
            "content": f"Recently read file (restored): {entry.path}\n\n{content}",
        })
        tokens_used += estimated
    
    return attachments
```

---

## Phase 4: Micro-Compaction (Week 3)

**Problem:** Old tool results accumulate forever. After 50 turns, conversation is 90% stale tool outputs.

**Fix:** Clear old tool results content, keep structure.

```python
COMPACTABLE_TOOLS = {
    "read_file", "shell", "grep", "glob",
    "web_search", "web_fetch", "file_edit", "file_write",
}

def microcompact_messages(messages: list[Message], keep_recent: int = 3) -> list[Message]:
    compactable_ids = [
        block.tool_use_id for msg in messages
        for block in msg.tool_results
        if block.tool_name in COMPACTABLE_TOOLS
    ]
    
    keep_set = set(compactable_ids[-keep_recent:])
    clear_set = set(compactable_ids) - keep_set
    
    for msg in messages:
        for block in msg.tool_results:
            if block.tool_use_id in clear_set:
                block.content = "[Old tool result content cleared]"
    
    return messages
```

**Impact:** 20-60% token savings on long sessions.

---

## Phase 5: Reactive Compact (Week 4)

**Problem:** When API returns "prompt too long", PersonAgent shows an error.

**Fix:** Catch and recover by dropping oldest messages.

```python
async def chat_with_reactive_compact(
    self, messages: list[dict], **kwargs
) -> APIResponse:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await self._api_call(messages, **kwargs)
        except PromptTooLongError:
            if attempt >= max_retries - 1:
                raise
            
            groups = group_messages_by_turn(messages)
            drop_count = max(1, len(groups) // 5)  # Drop 20%
            remaining = groups[drop_count:]
            
            if remaining and remaining[0]["role"] == "assistant":
                remaining.insert(0, {
                    "role": "user",
                    "content": "[earlier conversation truncated]",
                })
            
            messages = [msg for group in remaining for msg in group]
```

---

## Phase 6: Agent Framework Token Efficiency (Week 4-5)

**Problem:** The agent framework has zero token awareness.

**Fix:** Add budgets, shared caches, and smart reading.

### 6.1 Token Budget Per Agent

```python
@dataclass
class AgentBudget:
    total_tokens: int
    used: int = 0
    warning_threshold: float = 0.7
    compact_threshold: float = 0.8
    halt_threshold: float = 0.95

    def check_action(self, estimated_cost: int) -> str:
        projected = self.used + estimated_cost
        if projected > self.total_tokens * self.halt_threshold:
            return "HALT"
        if projected > self.total_tokens * self.compact_threshold:
            return "COMPACT_FIRST"
        return "OK"
```

### 6.2 Shared File Cache

```python
class SharedExplorationState:
    def __init__(self):
        self.file_cache: dict[str, FileCacheEntry] = {}
        self.tokens_used: int = 0

    async def read_file(self, path: str, agent_id: str) -> str:
        if path in self.file_cache:
            return self.file_cache[path].content
        
        content = await read_file_from_disk(path)
        self.file_cache[path] = FileCacheEntry(content=content)
        self.tokens_used += len(content) // 4
        return content
```

### 6.3 Smart File Reading

```python
class SmartFileReader:
    OUTLINE_THRESHOLD_TOKENS = 1000
    
    async def read(self, path: str) -> str:
        size = get_file_size(path)
        estimated = size // 4
        
        if estimated <= self.OUTLINE_THRESHOLD_TOKENS:
            return await read_full_file(path)
        
        outline = await self.generate_outline(path)
        return f"""File: {path} (~{estimated} tokens)

Outline:
{outline}

This file is large. Use Read(path="{path}", offset=..., limit=...) for specific sections.
"""
```

### 6.4 Stuck Detection

```python
class StuckDetector:
    def __init__(self, window: int = 5):
        self.window = window
        self.actions: deque = deque(maxlen=window)
    
    def is_stuck(self) -> tuple[bool, str]:
        if len(self.actions) < self.window:
            return False, ""
        
        signatures = [a.signature for a in self.actions]
        if len(set(signatures)) == 1:
            return True, f"Repeated {signatures[0]} {self.window} times"
        
        tokens_in_window = sum(a.tokens_consumed for a in self.actions)
        if tokens_in_window > 50_000:
            return True, f"Burned {tokens_in_window} tokens with no clear progress"
        
        return False, ""
```

---

## Phase 7: History Snip (Week 6)

**Problem:** Sometimes compaction itself is too expensive.

**Fix:** Pure deletion of oldest messages as emergency relief.

```python
def snip_compact(messages: list[Message], threshold: int) -> list[Message]:
    estimated = estimate_context_tokens(messages)
    if estimated <= threshold:
        return messages
    
    groups = group_messages_by_turn(messages)
    drop_count = 0
    
    for group in groups:
        group_tokens = sum(rough_token_estimate(m) for m in group)
        if estimated - sum(rough_token_estimate(m) for g in groups[drop_count:] for m in g) <= threshold:
            break
        drop_count += 1
    
    remaining = groups[drop_count:]
    if remaining and remaining[0].role == Role.ASSISTANT:
        remaining.insert(0, Message(
            role=Role.USER,
            content="[earlier conversation truncated for length]",
        ))
    
    return [msg for group in remaining for msg in group]
```

---

## Integration Order

```
Phase 1: Cap tool results (immediate — prevents explosions)
Phase 2: API-anchored token counting (Week 1)
Phase 3: Improve compaction (Week 2)
Phase 4: Micro-compaction (Week 3)
Phase 5: Reactive compact (Week 4)
Phase 6: Agent framework efficiency (Week 4-5)
Phase 7: History snip (Week 6)
```

## Metrics to Track

| Metric | Target |
|--------|--------|
| Benchmark tokens/run | < 50K |
| Max context per turn | < 30K |
| Tool result peak size | < 5K chars |
| Compaction cost | < 50K tokens |
| PTL error rate | < 0.1% |
