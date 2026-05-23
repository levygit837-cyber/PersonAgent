# ADR 0008: Markdown Frontmatter Skills with Multi-Root Discovery and Activation

Date: 2025-06-10
Status: Accepted

## Context

Users want to extend PersonAgent behavior per-project without code changes: custom prompt snippets, workflow templates, domain-specific rules. A lightweight plugin system must be file-based, version-controllable, and discoverable from multiple roots (project, user global, built-in).

## Decision

Implement a **skills system** based on Markdown files with YAML frontmatter.

**File format**
```markdown
---
name: "python-refactor"
version: "1.0.0"
description: "Refactoring rules for Python codebases"
enabled: true
activation:
  - "refactor"
  - "python"
---
# Python Refactoring Skill

When refactoring Python code, prefer...
```

**Discovery**
- `discover_enabled_skills()` scans `workspace_root/.personagent/skills/`, extra roots from `tool_skill_root_paths`, and built-in skills.
- Frontmatter is parsed by `parse_markdown_frontmatter()` (small, tolerant YAML parser).

**Activation**
- Skills can be auto-activated by keyword hints in the user message.
- Explicit activation via API request or slash command.
- Disabled skills are discovered but not injected into the prompt.

**Injection**
- `PromptBuilder` appends active skill bodies to the system prompt as additional base sections.
- `SkillDefinition` carries metadata for the tool search index.

## Consequences

- **Easier**: users version-control skills with their repos; no package manager or registry required.
- **Harder**: frontmatter schema discipline is manual; large skills inflate the prompt token count.
- **Risk**: conflicting skill instructions can contradict base rules; activation hints may overlap.
- **Out of scope**: a public skill marketplace (local-only for now); runtime skill compilation or sandboxing.

## Alternatives Considered

- **Python package plugins**: rejected for the security surface and packaging overhead.
- **JSON configuration files**: rejected because Markdown is human-readable and renders well in Git diffs.

## Validation

- `@backend/src/personagent/domain/prompts/skills.py` has unit tests for discovery, frontmatter parsing, and activation matching.
