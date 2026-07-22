# Alternatives to Compaction

If compaction (summarizing old messages) is too expensive or complex, here are other ways to manage context growth.

## 1. Truncation (Simple Deletion)

**What:** Delete old messages. No summary. No replacement.

```python
messages = messages[-10:]  # Keep only last 10
```

**When to use:** Simple chatbots where old context doesn't matter.

| Pros | Cons |
|------|------|
| Zero cost | Loses all old context |
| Simple | Agent forgets everything |

## 2. Sliding Window

**What:** Keep a fixed number of recent turns (4-10).

```python
WINDOW_SIZE = 6
messages = messages[-WINDOW_SIZE:]
```

**When to use:** Short tasks where only recent context matters.

## 3. Key-Value Memory

**What:** Extract facts from conversation and store in a structured database.

```python
memory_store.set("current_file", "src/main.py")
memory_store.set("last_error", "NullPointerException at line 42")

# Before each turn, prepend memory
system_prompt += f"Known facts:\n{memory_store.format()}"
```

**When to use:** Stateful tasks with clear variables (current file, last error, user preferences).

| Pros | Cons |
|------|------|
| Very compact | Requires knowing what to extract |
| Instant retrieval | Schema design overhead |

## 4. Retrieval-Augmented Generation (RAG)

**What:** Store messages in a vector DB. Retrieve relevant ones for each query.

```python
# Store
for message in conversation:
    embedding = embed(message.content)
    vector_db.store(embedding, message)

# Retrieve
relevant = vector_db.search(embed(current_query), top_k=5)
messages = [system_prompt, *relevant, *recent_turns]
```

**When to use:** Large knowledge bases, document Q&A.

**Not ideal for coding:** Coding requires sequential reasoning ("I read file A, then realized it imports file B..."). RAG can miss causal chains.

## 5. Hierarchical Summarization

**What:** Multiple summary levels. Recent = detailed, old = coarse.

```python
# Level 0: Last 4 turns (verbatim)
# Level 1: Summary of turns 5-10
# Level 2: Summary of turns 11-20
# Level 3: Summary of turns 21-50

messages = [
    system_prompt,
    f"Overall: {level_3_summary}",
    f"Recent work: {level_2_summary}",
    f"This session: {level_1_summary}",
    *last_4_turns,
]
```

**When to use:** Very long sessions (100+ turns).

## 6. Explicit State

**What:** Maintain a structured state object instead of relying on conversation history.

```python
@dataclass
class AgentState:
    current_task: str
    files_opened: list[str]
    last_error: str | None
    decisions_made: list[str]
    next_steps: list[str]
```

**When to use:** Well-defined workflows (bug fixing pipeline, deployment process).

## 7. Prompt Caching

**What:** API caches the prompt prefix. You pay less for cached tokens.

**Important:** This is **not** a solution to context size. You still send the full history. You just pay less for the cached portion.

## Comparison

| Method | Token Savings | Context Quality | Best For |
|--------|--------------|-----------------|----------|
| Compaction | High | High | Coding agents |
| Truncation | Maximum | Zero | Independent queries |
| Sliding Window | High | Low | Short tasks |
| Key-Value Memory | Very High | Medium | Stateful workflows |
| RAG | Very High | Medium | Knowledge bases |
| Hierarchical Summary | Very High | High | Very long sessions |
| Explicit State | Maximum | Medium | Well-defined workflows |

## Recommended Hybrid for PersonAgent

For a coding agent, combine:

1. **Sliding window floor** — always keep last 6-8 messages verbatim
2. **Compaction for older context** — summarize everything before the window
3. **Key-value memory for critical facts** — current file, last error, user preferences
4. **Tool result clearing** — replace old tool outputs with placeholders

This is cheaper than pure compaction (less to summarize), preserves recent context perfectly, and never loses critical facts.
