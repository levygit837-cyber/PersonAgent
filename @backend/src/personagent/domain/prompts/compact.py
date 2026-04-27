"""Formal prompts for compaction, memory, and next-step suggestion."""

BASE_COMPACT_PROMPT = """You compact a conversation so agent work can continue safely.

Text only. Do not call tools. Do not invent details, decisions, files, test results, or user intent. Preserve the latest known state and mark uncertainty explicitly.

Return concise Markdown with exactly these sections:

## Primary Request
Summarize the user's durable goal and the active task.

## Key Decisions
List decisions, constraints, and explicit preferences.

## Files And Code
List concrete files, functions, APIs, commands, and runtime paths mentioned or changed.

## Errors And Fixes
Preserve errors, failed hypotheses, and corrections.

## Pending Tasks
List unresolved work and blockers.

## Current State
Describe what is currently true at the end of the provided messages.

## Next Step
State the most likely next action if it is evident; otherwise write "Unknown"."""

PARTIAL_COMPACT_PROMPT = BASE_COMPACT_PROMPT + """

Only compact the earlier portion provided by the user. Preserve enough detail for the
recent un-compacted messages to continue the task."""

COMPACT_UP_TO_PROMPT = BASE_COMPACT_PROMPT + """

Compact all messages up to the provided marker. Keep marker-related context if it is
needed to interpret later messages."""

SESSION_MEMORY_TEMPLATE = """# Session Title

Short title for the conversation.

# Current State

What is currently true and useful for continuation.

# Task Specification

User goals, constraints, acceptance criteria, and explicit decisions.

# Files and Functions

Concrete files, functions, classes, routes, commands, and config keys.

# Workflow

How the work is being approached and what has already been attempted.

# Errors and Corrections

Errors seen, root causes discovered, and fixes applied.

# Learnings

Reusable preferences, durable project facts, and patterns.

# Pending Tasks

Unresolved steps and likely next actions.

# Worklog

Brief chronological notes with evidence."""

SESSION_MEMORY_UPDATE_PROMPT = f"""You update a controlled session memory file.

Text only. Do not call tools. Preserve the exact Markdown headers and intent of the
template. Keep details dense, factual, and useful for future turns. Remove stale or
duplicated notes when the current transcript supersedes them. Mark contradicted or
obsolete notes as replaced by the newer fact instead of keeping both. Avoid sensitive data.

Template:

{SESSION_MEMORY_TEMPLATE}
"""

MEMORY_EXTRACTION_PROMPT = """Extract durable memories from the recent conversation.

Text only. Do not call tools. Identify only reusable preferences, project decisions,
corrections, stable file paths, or operational patterns that are likely to matter in
future sessions. Avoid secrets, credentials, personal sensitive data, and one-off
transient facts.

Return only compact JSON:
{"memories":[{"type":"user|feedback|project|reference","name":"snake_case","description":"short label","content":"durable fact"}]}

Return {"memories":[]} when nothing durable should be saved."""

NEXT_STEP_SUGGESTION_PROMPT = """Suggest what the user might naturally type next.

Text only. Do not call tools. Return 2-12 words. Do not include quotes, punctuation
unless needed, markdown, or explanation. Suppress by returning an empty string when
there is no obvious next step, the last turn ended in an error, a permission decision
is pending, or the user likely expects no suggestion."""
