# Exploration Task Prompt Template

## Purpose
This template is used for every benchmark run. It guides the agent to explore without giving away the answer.

## Template

```
Explore the codebase at {workspace} and answer this question:

**Question**: {question}

Instructions:
- Use the available tools (Read, Grep, Glob, shell) to investigate thoroughly.
- Do NOT guess or assume — verify your findings by reading the actual source files.
- Follow import chains, trace execution paths, and understand how components interact.
- Read multiple relevant files before synthesizing your answer.
- If you get stuck or find contradictory information, try a different search strategy.
- Provide a clear, specific answer with file names and line references where applicable.
```

## Retry Prompt (injected when stuck or insufficient)

```
Your previous answer was insufficient or incomplete. Please continue exploring.

Files you've read so far: {files_so_far}
Steps taken: {steps}

The question is: {question}

Please dig deeper. Check files you haven't examined yet, follow more import chains, and verify your understanding before answering again.
```

## Retry Prompt (injected when stuck)

```
You seem to be stuck ({reason}). Please reconsider your approach and try a different strategy.
```

## Retry Prompt (injected at max steps)

```
You have reached the step limit. Please provide your best answer based on what you've found so far.
```
