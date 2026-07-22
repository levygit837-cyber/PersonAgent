#!/usr/bin/env python3
"""Evaluate PersonAgent system prompt harness behavior using an external LLM.

This script sends the assembled system prompt + a test task to an LLM API
and evaluates whether the model follows the harness instructions correctly:
- Intent classification
- Exploration depth
- Tool use patterns
- Synthesis quality
- Hallucination resistance

Usage:
    export DEEPSEEK_API_KEY=sk-...
    python scripts/evaluate_prompt_with_llm.py --provider deepseek --model deepseek-v4-flash

    # Or with OpenAI:
    export OPENAI_API_KEY=sk-...
    python scripts/evaluate_prompt_with_llm.py --provider openai --model gpt-4o-mini

Requirements: httpx, tiktoken (already in project dependencies)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import tiktoken

# Add backend src to path so we can import the prompt builder
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from personagent.domain.prompts.prompt import (
    core_system_prompt_sections,
    get_mode_prompt_section,
)
from personagent.domain.prompts.sections.agent import (
    get_agent_sections,
    get_frontloaded_agent_sections,
)
from personagent.domain.prompts.sections.execution import get_execution_sections
from personagent.domain.prompts.sections.states import get_agent_state_sections
from personagent.domain.prompts.sections.tools import get_tool_sections


# ---------------------------------------------------------------------------
# Prompt assembly (mirrors PromptBuilder logic for testing)
# ---------------------------------------------------------------------------

def assemble_test_prompt(mode: str = "exploring", tools: list[str] | None = None) -> str:
    """Assemble a representative system prompt for evaluation."""
    tools = tools or ["Read", "Edit", "Write", "Glob", "Grep", "shell"]
    base = core_system_prompt_sections()
    front = get_frontloaded_agent_sections()
    mode_section = (get_mode_prompt_section(mode),)
    tool_secs = get_tool_sections(tools)
    exec_secs = get_execution_sections("manual")
    # Use a subset of agent states that are most common
    states = get_agent_state_sections(("intake", "context_discovery", "tool_execution", "finalization"))
    agent = get_agent_sections()

    all_sections = base + front + mode_section + tool_secs + exec_secs + states + agent
    parts: list[str] = []
    for section in all_sections:
        computed = section.compute()
        if isinstance(computed, str) and computed.strip():
            parts.append(computed.strip())
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM client wrappers
# ---------------------------------------------------------------------------

class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=60.0)

    async def chat(self, messages: list[dict[str, str]], model: str, temperature: float = 0.0) -> str:
        resp = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])


class OpenAIClient:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=60.0)

    async def chat(self, messages: list[dict[str, str]], model: str, temperature: float = 0.0) -> str:
        resp = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])


# ---------------------------------------------------------------------------
# Evaluation tasks
# ---------------------------------------------------------------------------

EVALUATION_TASKS = [
    {
        "id": "intent-classification-light",
        "user_message": "What time is it?",
        "expected_behavior": "Answer directly without claiming to use tools or read files. The prompt says 'ask only when a missing choice cannot be discovered and changes the outcome.'",
        "checks": ["no_tool_calls", "direct_answer", "no_file_refs"],
    },
    {
        "id": "intent-classification-codebase",
        "user_message": "How does the authentication system work in this repo?",
        "expected_behavior": "Classify as standard/deep investigation. Search for auth-related files, read entrypoints and domain logic, check tests, then synthesize with specific file names and line references.",
        "checks": ["uses_read_or_grep", "mentions_specific_files", "mentions_tests_or_config", "synthesis_not_transcript"],
    },
    {
        "id": "anti-silent-failure",
        "user_message": "Read the file src/main.py and tell me what it does.",
        "expected_behavior": "After receiving the tool result, the model MUST produce a substantive answer referencing the file contents. It must NOT say 'Done.' or 'OK.'",
        "checks": ["substantive_answer", "references_tool_results", "no_stub_response"],
    },
    {
        "id": "exploration-depth",
        "user_message": "Review the entire codebase architecture for security issues.",
        "expected_behavior": "Treat as deep or exhaustive. Read multiple surfaces (entrypoints, domain, adapters, tests, config). Do not stop after 1–2 files.",
        "checks": ["reads_multiple_files", "checks_tests", "checks_config", "mentions_blast_radius"],
    },
    {
        "id": "hallucination-resistance",
        "user_message": "Is there a function called process_payment in this repo?",
        "expected_behavior": "Use Grep to verify existence before claiming. If not found, say so. Do not hallucinate a file path or function signature.",
        "checks": ["uses_grep_before_claiming", "acknowledges_absence_if_missing", "no_fabricated_path"],
    },
    {
        "id": "mode-writing",
        "user_message": "Add a try/except block around the login function in src/auth.py",
        "expected_behavior": "Classify as writing mode. Inspect the file before editing. Use Edit with exact old_string match. Validate the change conceptually.",
        "checks": ["reads_before_editing", "uses_edit_tool", "exact_match_mentioned", "validation_attempted"],
    },
]


# ---------------------------------------------------------------------------
# Scoring rubric
# ---------------------------------------------------------------------------

def score_response(task: dict[str, str], response: str, tool_calls: list[dict] | None = None) -> dict:
    """Simple heuristic scoring. A real judge LLM would be more accurate."""
    text = response.lower()
    checks = task["checks"]
    results: dict[str, bool] = {}

    for check in checks:
        if check == "no_tool_calls":
            results[check] = not tool_calls
        elif check == "direct_answer":
            results[check] = len(response.split()) < 50 and "file" not in text
        elif check == "no_file_refs":
            results[check] = ".py" not in text and ".ts" not in text and "/src/" not in text
        elif check == "uses_read_or_grep":
            results[check] = bool(tool_calls and any(
                (tc.get("function", {}).get("name", "") in ("Read", "Grep", "Glob"))
                for tc in tool_calls
            ))
        elif check == "mentions_specific_files":
            results[check] = any(ext in text for ext in (".py", ".ts", ".tsx", ".js", ".json", ".toml"))
        elif check == "mentions_tests_or_config":
            results[check] = "test" in text or "config" in text or "pyproject" in text or "package.json" in text
        elif check == "synthesis_not_transcript":
            results[check] = "i read" not in text and "i searched" not in text and "the tool returned" not in text
        elif check == "substantive_answer":
            results[check] = len(response) > 80
        elif check == "references_tool_results":
            results[check] = "file" in text or "line" in text or "function" in text
        elif check == "no_stub_response":
            results[check] = response.strip().lower() not in {"done.", "ok.", "fixed.", "completed."}
        elif check == "reads_multiple_files":
            results[check] = bool(tool_calls and len(tool_calls) >= 2)
        elif check == "checks_tests":
            results[check] = bool(tool_calls and any("test" in str(tc) for tc in tool_calls))
        elif check == "checks_config":
            results[check] = bool(tool_calls and any("config" in str(tc) or ".toml" in str(tc) or ".json" in str(tc) for tc in tool_calls))
        elif check == "mentions_blast_radius":
            results[check] = "blast" in text or "impact" in text or "surface" in text or "affected" in text
        elif check == "uses_grep_before_claiming":
            results[check] = bool(tool_calls and any(tc.get("function", {}).get("name", "") == "Grep" for tc in tool_calls))
        elif check == "acknowledges_absence_if_missing":
            results[check] = "not found" in text or "no matches" in text or "does not exist" in text or "could not find" in text
        elif check == "no_fabricated_path":
            # Hard to detect heuristically; default True and let human review.
            results[check] = True
        elif check == "reads_before_editing":
            read_ids = {tc.get("id") for tc in (tool_calls or []) if tc.get("function", {}).get("name") == "Read"}
            edit_ids = {tc.get("id") for tc in (tool_calls or []) if tc.get("function", {}).get("name") == "Edit"}
            results[check] = bool(read_ids and (not edit_ids or min(read_ids) < min(edit_ids)))
        elif check == "uses_edit_tool":
            results[check] = bool(tool_calls and any(tc.get("function", {}).get("name") == "Edit" for tc in tool_calls))
        elif check == "exact_match_mentioned":
            results[check] = "old_string" in text or "exact" in text
        elif check == "validation_attempted":
            results[check] = "test" in text or "validate" in text or "check" in text
        else:
            results[check] = False

    score = sum(results.values()) / max(len(results), 1)
    return {"score": round(score, 2), "check_results": results}


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_evaluation(provider: str, model: str) -> None:
    if provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            print("ERROR: Set DEEPSEEK_API_KEY environment variable.", file=sys.stderr)
            sys.exit(1)
        client: DeepSeekClient | OpenAIClient = DeepSeekClient(key)
    elif provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            print("ERROR: Set OPENAI_API_KEY environment variable.", file=sys.stderr)
            sys.exit(1)
        client = OpenAIClient(key)
    else:
        print(f"ERROR: Unknown provider {provider}", file=sys.stderr)
        sys.exit(1)

    system_prompt = assemble_test_prompt(mode="exploring")
    enc = tiktoken.get_encoding("cl100k_base")
    prompt_tokens = len(enc.encode(system_prompt))
    print(f"\n=== System Prompt Stats ===")
    print(f"Chars: {len(system_prompt)}")
    print(f"Tokens (cl100k_base): {prompt_tokens}")
    print(f"Provider: {provider} | Model: {model}\n")

    results: list[dict] = []
    for task in EVALUATION_TASKS:
        print(f"--- Task: {task['id']} ---")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task["user_message"]},
        ]
        try:
            response = await client.chat(messages, model=model, temperature=0.2)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            continue

        # Note: We don't have real tool_call simulation here; the LLM may describe tools.
        # For a full evaluation, use the actual streaming executor with a mock LLM backend.
        scored = score_response(task, response, tool_calls=None)
        print(f"  Score: {scored['score']}")
        print(f"  Response preview: {response[:200].replace(chr(10), ' ')}...")
        results.append({"task_id": task["id"], **scored, "raw_response": response})

    overall = sum(r["score"] for r in results) / max(len(results), 1)
    print(f"\n=== Overall Harness Score: {overall:.2f} ===")

    out_path = Path("prompt_harness_eval_results.json")
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Detailed results written to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate PersonAgent prompt harness with an LLM")
    parser.add_argument("--provider", choices=["deepseek", "openai"], default="deepseek")
    parser.add_argument("--model", default="deepseek-v4-flash")
    args = parser.parse_args()
    asyncio.run(run_evaluation(args.provider, args.model))
