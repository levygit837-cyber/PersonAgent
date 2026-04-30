#!/usr/bin/env python3
# ruff: noqa: E402
"""Live system-prompt benchmark runner for DeepSeek V4 Flash.

The runner intentionally exercises the PersonAgent application path:
ChatCompletionUseCase -> PromptBuilder -> DeepSeekAdapter -> read-only tools.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

BENCHMARK_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_DIR.parents[1]
BACKEND_SRC = REPO_ROOT / "@backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from personagent.application.dto.chat_dto import ChatRequestDTO  # noqa: E402
from personagent.application.tools import ToolRegistry, ToolRuntimeConfig  # noqa: E402
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase  # noqa: E402
from personagent.application.use_cases.context import BuildContextUseCase  # noqa: E402
from personagent.domain.models.conversation import Conversation, Role  # noqa: E402
from personagent.domain.repositories.conversation_repository import (
    ConversationRepository,  # noqa: E402
)
from personagent.infrastructure.llm.deepseek_adapter import DeepSeekAdapter  # noqa: E402
from personagent.infrastructure.persistence.context import InMemoryContextRepository  # noqa: E402
from personagent.infrastructure.tools import (  # noqa: E402
    create_glob_tool,
    create_grep_tool,
    create_read_file_tool,
)

READ_ONLY_TOOLS = {"Read", "Grep", "Glob"}
METRIC_NAMES = (
    "clarity_score",
    "completeness_score",
    "format_discipline_score",
    "evidence_grounding_score",
    "tool_behavior_score",
    "uncertainty_score",
)
SENSITIVE_KEY_PARTS = ("key", "token", "secret", "password", "authorization", "cookie")


class MemoryConversationRepository(ConversationRepository):
    """Small in-memory repository used by the benchmark run."""

    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}

    async def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        return list(self.conversations.values())[offset : offset + limit]

    async def update(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation
        return conversation

    async def delete(self, conversation_id: UUID) -> bool:
        return self.conversations.pop(conversation_id, None) is not None

    async def search(self, query: str, limit: int = 10) -> list[Conversation]:
        return [
            conversation
            for conversation in self.conversations.values()
            if query.lower() in conversation.title.lower()
        ][:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        default=str(REPO_ROOT),
        help="Workspace root exposed to PersonAgent context and read-only tools.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("DEEPSEEK_DEFAULT_MODEL", "deepseek-v4-flash"),
        help="DeepSeek model id. Defaults to deepseek-v4-flash.",
    )
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-tool-iterations", type=int, default=8)
    parser.add_argument("--tool-result-max-chars", type=int, default=12000)
    parser.add_argument("--timeout", type=float, default=float(os.getenv("DEEPSEEK_TIMEOUT", 240)))
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only a case id. Can be provided multiple times.",
    )
    return parser.parse_args()


def load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(REPO_ROOT / "@backend" / ".env")


def require_live_environment() -> None:
    if os.getenv("DEEPSEEK_LIVE_TESTS") != "1":
        raise SystemExit("Set DEEPSEEK_LIVE_TESTS=1 to run live DeepSeek benchmarks.")
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Set DEEPSEEK_API_KEY to run live DeepSeek benchmarks.")


def load_cases(case_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    path = BENCHMARK_DIR / "cases" / "system_prompt_eval_cases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = list(data.get("cases") or [])
    requested = set(case_ids or [])
    if requested:
        cases = [case for case in cases if case.get("id") in requested]
        missing = requested - {str(case.get("id")) for case in cases}
        if missing:
            raise SystemExit(f"Unknown benchmark case id(s): {', '.join(sorted(missing))}")
    _validate_cases(cases)
    return cases


def _validate_cases(cases: list[dict[str, Any]]) -> None:
    if not cases:
        raise SystemExit("No benchmark cases selected.")
    for case in cases:
        if not case.get("id"):
            raise SystemExit("Every benchmark case needs an id.")
        allowed = set(case.get("allowed_tools") or [])
        if case.get("tools_enabled") and not allowed.issubset(READ_ONLY_TOOLS):
            raise SystemExit(
                f"Case {case['id']} uses non-read-only tools: {sorted(allowed - READ_ONLY_TOOLS)}"
            )
        required = set(case.get("required_tools") or [])
        if not required.issubset(READ_ONLY_TOOLS):
            raise SystemExit(
                f"Case {case['id']} requires non-read-only tools: "
                f"{sorted(required - READ_ONLY_TOOLS)}"
            )


def build_use_case(
    *,
    workspace_root: Path,
    model: str,
    max_tokens: int,
    timeout: float,
    max_tool_iterations: int,
    tool_result_max_chars: int,
) -> tuple[ChatCompletionUseCase, DeepSeekAdapter, MemoryConversationRepository]:
    repo = MemoryConversationRepository()
    adapter = DeepSeekAdapter(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        default_model=model,
        default_max_tokens=max_tokens,
        timeout=timeout,
        stream_read_timeout=0.0,
    )
    registry = ToolRegistry([create_read_file_tool(), create_grep_tool(), create_glob_tool()])
    config = ToolRuntimeConfig.from_values(
        workspace_root=workspace_root,
        allowed_roots=(workspace_root,),
        max_tool_iterations=max_tool_iterations,
        result_max_chars=tool_result_max_chars,
    )
    use_case = ChatCompletionUseCase(
        conversation_repo=repo,
        llm_backend=adapter,
        tool_registry=registry,
        tool_runtime_config=config,
        build_context_use_case=BuildContextUseCase(
            workspace_root=workspace_root,
            context_repository=InMemoryContextRepository(),
        ),
        context_window_tokens=1_000_000,
        default_output_tokens=max_tokens,
    )
    return use_case, adapter, repo


async def run_case(
    *,
    case: dict[str, Any],
    use_case: ChatCompletionUseCase,
    repo: MemoryConversationRepository,
    run_id: str,
    workspace_root: Path,
    model: str,
    max_tokens: int,
    max_tool_iterations: int,
    tool_result_max_chars: int,
) -> dict[str, Any]:
    case_id = str(case["id"])
    trace_path = BENCHMARK_DIR / "tracing" / run_id / f"{case_id}.jsonl"
    result_path = BENCHMARK_DIR / "results" / run_id / f"{case_id}.json"
    prompt_path = BENCHMARK_DIR / "system_prompts" / run_id / f"{case_id}.md"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)

    request = case_request(
        case=case,
        workspace_root=workspace_root,
        model=model,
        max_tokens=max_tokens,
        max_tool_iterations=max_tool_iterations,
        run_id=run_id,
        tool_result_max_chars=tool_result_max_chars,
    )

    preview = await use_case.preview_prompt(request)
    prompt_path.write_text(render_prompt_artifact(case, preview), encoding="utf-8")
    append_trace(
        trace_path,
        {
            "event": "prompt_preview",
            "case_id": case_id,
            "sections": preview.get("sections"),
            "surfaces": preview.get("surfaces"),
            "agent_states": preview.get("agent_states"),
            "line_count": preview.get("line_count"),
            "char_count": preview.get("char_count"),
            "provider_data_boundary": preview.get("provider_data_boundary"),
        },
    )

    started = time.perf_counter()
    first_token_ms: int | None = None
    content_chunks: list[str] = []
    reasoning_chunks: list[str] = []
    conversation_id: str | None = None
    stream_error: str | None = None

    try:
        async for chunk in use_case.execute_stream(request):
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if conversation_id is None and chunk.metadata.get("event") == "conversation":
                raw_id = chunk.metadata.get("conversation_id")
                conversation_id = str(raw_id) if raw_id else None
            if first_token_ms is None and (chunk.content or chunk.reasoning_content):
                first_token_ms = elapsed_ms
            if chunk.content:
                content_chunks.append(chunk.content)
            if chunk.reasoning_content:
                reasoning_chunks.append(chunk.reasoning_content)
            append_trace(trace_path, stream_trace_event(chunk, elapsed_ms))
    except Exception as exc:
        stream_error = f"{type(exc).__name__}: {exc}"
        append_trace(trace_path, {"event": "stream_error", "error": stream_error})

    total_ms = int((time.perf_counter() - started) * 1000)
    conversation = await load_conversation(repo, conversation_id)
    final_content, final_reasoning = final_text_from_conversation(
        conversation=conversation,
        fallback_content="".join(content_chunks),
        fallback_reasoning="".join(reasoning_chunks),
    )
    tools_called, tool_call_names = tool_names_from_conversation(conversation)

    evaluation = evaluate_case(
        case=case,
        content=final_content,
        reasoning=final_reasoning,
        tools_called=tools_called,
        tool_call_names=tool_call_names,
        first_token_ms=first_token_ms,
        total_ms=total_ms,
        stream_error=stream_error,
    )
    result = {
        "run_id": run_id,
        "case_id": case_id,
        "level": case.get("level"),
        "provider": "deepseek",
        "model": model,
        "status": "failed" if evaluation["failed_reasons"] else "passed",
        "failed_reasons": evaluation["failed_reasons"],
        "scores": evaluation["scores"],
        "objective_metrics": evaluation["objective_metrics"],
        "expected_terms_hit": evaluation["expected_terms_hit"],
        "expected_terms_missing": evaluation["expected_terms_missing"],
        "required_tools_missing": evaluation["required_tools_missing"],
        "tools_called": tools_called,
        "tool_call_names": tool_call_names,
        "first_token_ms": first_token_ms,
        "total_ms": total_ms,
        "content": final_content,
        "reasoning_content": final_reasoning,
        "prompt_artifact": str(prompt_path.relative_to(BENCHMARK_DIR)),
        "trace_artifact": str(trace_path.relative_to(BENCHMARK_DIR)),
        "stream_error": stream_error,
    }
    write_json(result_path, result)
    append_trace(
        trace_path,
        {
            "event": "case_result",
            "status": result["status"],
            "scores": result["scores"],
            "objective_metrics": result["objective_metrics"],
            "failed_reasons": result["failed_reasons"],
        },
    )
    return result


def case_request(
    *,
    case: dict[str, Any],
    workspace_root: Path,
    model: str,
    max_tokens: int,
    max_tool_iterations: int,
    run_id: str,
    tool_result_max_chars: int,
) -> ChatRequestDTO:
    return ChatRequestDTO(
        message=str(case["message"]),
        stream=True,
        provider="deepseek",
        model=model,
        prompt_mode=str(case.get("prompt_mode") or "exploring"),
        tools_enabled=bool(case.get("tools_enabled")),
        allowed_tools=list(case.get("allowed_tools") or []),
        tool_context={
            "workspace_root": str(workspace_root),
            "limits": {"result_max_chars": tool_result_max_chars},
        },
        max_tokens=max_tokens,
        max_tool_iterations=max_tool_iterations,
        reasoning_level="high",
        metadata={"benchmark_run_id": run_id, "benchmark_case_id": case["id"]},
    )


def render_prompt_artifact(case: dict[str, Any], preview: dict[str, Any]) -> str:
    metadata = {
        "case_id": case["id"],
        "level": case.get("level"),
        "mode": preview.get("mode"),
        "provider": preview.get("provider"),
        "model": preview.get("model"),
        "sections": preview.get("sections"),
        "agent_states": preview.get("agent_states"),
        "line_count": preview.get("line_count"),
        "char_count": preview.get("char_count"),
    }
    return (
        "# System Prompt Preview\n\n"
        "```json\n"
        f"{json.dumps(metadata, indent=2, ensure_ascii=False)}\n"
        "```\n\n"
        "## System Prompt\n\n"
        "```text\n"
        f"{preview.get('system_prompt') or ''}\n"
        "```\n\n"
        "## User Context Message\n\n"
        "```text\n"
        f"{preview.get('user_context_message') or ''}\n"
        "```\n"
    )


def stream_trace_event(chunk: Any, elapsed_ms: int) -> dict[str, Any]:
    return {
        "event": "stream_chunk",
        "elapsed_ms": elapsed_ms,
        "content_chars": len(chunk.content or ""),
        "reasoning_chars": len(chunk.reasoning_content or ""),
        "finish_reason": chunk.finish_reason,
        "usage": redact(chunk.usage),
        "tool_calls": redact(chunk.tool_calls),
        "metadata": redact(chunk.metadata),
    }


async def load_conversation(
    repo: MemoryConversationRepository,
    conversation_id: str | None,
) -> Conversation | None:
    if conversation_id:
        try:
            conversation = await repo.get_by_id(UUID(conversation_id))
            if conversation is not None:
                return conversation
        except ValueError:
            pass
    if repo.conversations:
        return list(repo.conversations.values())[-1]
    return None


def final_text_from_conversation(
    *,
    conversation: Conversation | None,
    fallback_content: str,
    fallback_reasoning: str,
) -> tuple[str, str]:
    if conversation is None:
        return fallback_content.strip(), fallback_reasoning.strip()
    assistant_messages = [message for message in conversation.messages if message.role == Role.ASSISTANT]
    content = "\n\n".join(message.content for message in assistant_messages if message.content).strip()
    reasoning = "\n\n".join(
        str(message.metadata.get("reasoning_content") or "")
        for message in assistant_messages
        if message.metadata.get("reasoning_content")
    ).strip()
    return content or fallback_content.strip(), reasoning or fallback_reasoning.strip()


def tool_names_from_conversation(
    conversation: Conversation | None,
) -> tuple[list[str], list[str]]:
    if conversation is None:
        return [], []
    result_names: list[str] = []
    call_names: list[str] = []
    for message in conversation.messages:
        if message.role == Role.TOOL:
            name = message.metadata.get("tool_name")
            if isinstance(name, str):
                add_unique(result_names, name)
        if message.role == Role.ASSISTANT and message.tool_calls:
            for raw_call in message.tool_calls:
                function = raw_call.get("function") if isinstance(raw_call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                if isinstance(name, str):
                    add_unique(call_names, name)
    return result_names, call_names


def add_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def evaluate_case(
    *,
    case: dict[str, Any],
    content: str,
    reasoning: str,
    tools_called: list[str],
    tool_call_names: list[str],
    first_token_ms: int | None,
    total_ms: int,
    stream_error: str | None,
) -> dict[str, Any]:
    content_lower = content.lower()
    expected_terms = [str(term) for term in case.get("expected_terms") or []]
    expected_hit = [term for term in expected_terms if term.lower() in content_lower]
    expected_missing = [term for term in expected_terms if term not in expected_hit]
    required_tools = [str(tool) for tool in case.get("required_tools") or []]
    called_lower = {tool.lower() for tool in tools_called + tool_call_names}
    missing_tools = [tool for tool in required_tools if tool.lower() not in called_lower]
    bullet_count = count_bullet_lines(content)
    heading_count = count_headings(content)
    line_count = max(1, len(content.splitlines()))
    bullet_ratio = bullet_count / line_count
    content_chars = len(content)
    reasoning_chars = len(reasoning)
    min_chars = int(case.get("min_chars") or 1)
    max_chars = int(case.get("max_chars") or 1_000_000)
    max_bullet_ratio = float(case.get("max_bullet_ratio") or 1.0)
    max_headings = int(case.get("max_headings") or 100)
    max_bullet_lines = optional_int(case.get("max_bullet_lines"))
    max_table_lines = optional_int(case.get("max_table_lines"))
    max_non_dash_bullets = optional_int(case.get("max_non_dash_bullet_lines"))
    max_decorative_markers = optional_int(case.get("max_decorative_markers"))
    table_line_count = count_table_lines(content)
    non_dash_bullet_count = count_non_dash_bullet_lines(content)
    decorative_marker_count = count_decorative_markers(content)
    failed_reasons: list[str] = []

    if stream_error:
        failed_reasons.append(stream_error)
    if not content.strip():
        failed_reasons.append("empty_response")
    if content_chars < min_chars:
        failed_reasons.append(f"content_too_short:{content_chars}<{min_chars}")
    if content_chars > max_chars:
        failed_reasons.append(f"content_too_long:{content_chars}>{max_chars}")
    if missing_tools:
        failed_reasons.append(f"missing_required_tools:{','.join(missing_tools)}")
    if bullet_ratio > max_bullet_ratio and (
        max_bullet_lines is None or bullet_count > max_bullet_lines
    ):
        failed_reasons.append(f"bullet_ratio_exceeded:{bullet_ratio:.2f}>{max_bullet_ratio:.2f}")
    if heading_count > max_headings:
        failed_reasons.append(f"heading_limit_exceeded:{heading_count}>{max_headings}")
    if max_bullet_lines is not None and bullet_count > max_bullet_lines:
        failed_reasons.append(f"bullet_line_limit_exceeded:{bullet_count}>{max_bullet_lines}")
    if max_table_lines is not None and table_line_count > max_table_lines:
        failed_reasons.append(f"table_line_limit_exceeded:{table_line_count}>{max_table_lines}")
    if max_non_dash_bullets is not None and non_dash_bullet_count > max_non_dash_bullets:
        failed_reasons.append(
            f"non_dash_bullet_limit_exceeded:{non_dash_bullet_count}>{max_non_dash_bullets}"
        )
    if max_decorative_markers is not None and decorative_marker_count > max_decorative_markers:
        failed_reasons.append(
            f"decorative_marker_limit_exceeded:{decorative_marker_count}>{max_decorative_markers}"
        )

    clarity = bounded_score(1.0 - 0.2 * bool(stream_error) - 0.2 * (heading_count > max_headings))
    completeness = ratio_score(len(expected_hit), len(expected_terms))
    format_score = bounded_score(
        1.0
        - max(0.0, bullet_ratio - max_bullet_ratio) * 2.0
        - 0.15 * max(0, heading_count - max_headings)
        - 0.05 * max(0, bullet_count - limit_or_current(max_bullet_lines, bullet_count))
        - 0.1 * max(0, table_line_count - limit_or_current(max_table_lines, table_line_count))
        - 0.1
        * max(
            0,
            non_dash_bullet_count
            - limit_or_current(max_non_dash_bullets, non_dash_bullet_count),
        )
        - 0.1
        * max(
            0,
            decorative_marker_count
            - limit_or_current(max_decorative_markers, decorative_marker_count),
        )
    )
    tool_score = (
        ratio_score(len(required_tools) - len(missing_tools), len(required_tools))
        if required_tools
        else (1.0 if not tools_called and not tool_call_names else 0.75)
    )
    evidence_score = evidence_grounding_score(
        case=case,
        content_lower=content_lower,
        tool_score=tool_score,
    )
    uncertainty = uncertainty_score(case.get("level"), content_lower)
    scores = {
        "clarity_score": clarity,
        "completeness_score": completeness,
        "format_discipline_score": format_score,
        "evidence_grounding_score": evidence_score,
        "tool_behavior_score": tool_score,
        "uncertainty_score": uncertainty,
    }
    overall = sum(scores.values()) / len(scores)
    scores["overall_score"] = round(overall, 4)
    rounded_scores = {key: round(value, 4) for key, value in scores.items()}

    return {
        "scores": rounded_scores,
        "failed_reasons": failed_reasons,
        "required_tools_missing": missing_tools,
        "expected_terms_hit": expected_hit,
        "expected_terms_missing": expected_missing,
        "objective_metrics": {
            "bullet_line_count": bullet_count,
            "heading_count": heading_count,
            "table_line_count": table_line_count,
            "non_dash_bullet_line_count": non_dash_bullet_count,
            "decorative_marker_count": decorative_marker_count,
            "line_count": line_count,
            "bullet_ratio": round(bullet_ratio, 4),
            "content_chars": content_chars,
            "reasoning_chars": reasoning_chars,
            "first_token_ms": first_token_ms,
            "total_ms": total_ms,
            "tools_called": tools_called,
            "tool_call_names": tool_call_names,
        },
    }


def count_bullet_lines(text: str) -> int:
    pattern = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
    return sum(1 for line in text.splitlines() if pattern.match(line))


def count_non_dash_bullet_lines(text: str) -> int:
    pattern = re.compile(r"^\s*(?:[*+]|\d+[.)])\s+|^\s*-\s+\[[ xX]\]")
    return sum(1 for line in text.splitlines() if pattern.match(line))


def count_headings(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("#"))


def count_table_lines(text: str) -> int:
    table_separator = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
    return sum(
        1
        for line in text.splitlines()
        if (line.strip().startswith("|") and line.count("|") >= 2)
        or table_separator.match(line)
    )


def count_decorative_markers(text: str) -> int:
    pattern = re.compile(r"[\U0001F300-\U0001FAFF✅❌✔✖✗✘🔥📊📰🤖🥇⭐]")
    return len(pattern.findall(text))


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def limit_or_current(limit: int | None, current: int) -> int:
    return current if limit is None else limit


def ratio_score(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return bounded_score(numerator / denominator)


def evidence_grounding_score(
    *,
    case: dict[str, Any],
    content_lower: str,
    tool_score: float,
) -> float:
    if case.get("required_tools"):
        return tool_score
    evidence_terms = ("fonte", "evidencia", "arquivo", "teste", "validacao", "resultado")
    hits = sum(1 for term in evidence_terms if term in content_lower)
    return bounded_score(0.6 + min(0.4, hits * 0.1))


def uncertainty_score(level: Any, content_lower: str) -> float:
    if str(level) == "low":
        return 1.0
    terms = ("incerte", "risco", "assum", "limita", "bloque", "validacao", "tradeoff")
    hits = sum(1 for term in terms if term in content_lower)
    return bounded_score(hits / 2)


def bounded_score(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def summarize_results(run_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [result for result in results if result["status"] != "passed"]
    score_totals = dict.fromkeys((*METRIC_NAMES, "overall_score"), 0.0)
    for result in results:
        for name in score_totals:
            score_totals[name] += float(result["scores"].get(name, 0))
    averages = {
        name: round(total / max(1, len(results)), 4)
        for name, total in score_totals.items()
    }
    return {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "provider": "deepseek",
        "model": results[0]["model"] if results else None,
        "case_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "failed_cases": [
            {"case_id": result["case_id"], "failed_reasons": result["failed_reasons"]}
            for result in failed
        ],
        "average_scores": averages,
        "results": [
            {
                "case_id": result["case_id"],
                "status": result["status"],
                "overall_score": result["scores"]["overall_score"],
                "total_ms": result["total_ms"],
                "first_token_ms": result["first_token_ms"],
                "tools_called": result["tools_called"],
            }
            for result in results
        ],
    }


def ensure_output_dirs(run_id: str) -> None:
    for dirname in ("system_prompts", "results", "tracing"):
        (BENCHMARK_DIR / dirname / run_id).mkdir(parents=True, exist_ok=True)
    (BENCHMARK_DIR / "logs").mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=json_default), encoding="utf-8")


def append_trace(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False, default=json_default) + "\n")


def append_log(run_id: str, event: dict[str, Any]) -> None:
    path = BENCHMARK_DIR / "logs" / f"{run_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False, default=json_default) + "\n")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SENSITIVE_KEY_PARTS):
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = redact(nested)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def async_main() -> int:
    args = parse_args()
    load_dotenv_files()
    require_live_environment()
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    cases = load_cases(args.case_ids)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{args.model}"
    ensure_output_dirs(run_id)
    use_case, adapter, repo = build_use_case(
        workspace_root=workspace_root,
        model=args.model,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        max_tool_iterations=args.max_tool_iterations,
        tool_result_max_chars=args.tool_result_max_chars,
    )
    append_log(
        run_id,
        {
            "event": "run_started",
            "run_id": run_id,
            "workspace_root": str(workspace_root),
            "model": args.model,
            "case_count": len(cases),
        },
    )
    results: list[dict[str, Any]] = []
    try:
        for case in cases:
            result = await run_case(
                case=case,
                use_case=use_case,
                repo=repo,
                run_id=run_id,
                workspace_root=workspace_root,
                model=args.model,
                max_tokens=args.max_tokens,
                max_tool_iterations=args.max_tool_iterations,
                tool_result_max_chars=args.tool_result_max_chars,
            )
            results.append(result)
            append_log(
                run_id,
                {
                    "event": "case_finished",
                    "case_id": result["case_id"],
                    "status": result["status"],
                    "scores": result["scores"],
                    "failed_reasons": result["failed_reasons"],
                    "total_ms": result["total_ms"],
                    "first_token_ms": result["first_token_ms"],
                    "tools_called": result["tools_called"],
                },
            )
    finally:
        await adapter.close()

    summary = summarize_results(run_id, results)
    summary_path = BENCHMARK_DIR / "results" / run_id / "summary.json"
    write_json(summary_path, summary)
    append_log(run_id, {"event": "run_finished", **summary})
    print(f"Run id: {run_id}")
    print(f"Summary: {summary_path}")
    print(f"Passed: {summary['passed_count']} / {summary['case_count']}")
    return 1 if summary["failed_count"] else 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
