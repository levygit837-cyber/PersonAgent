from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = REPO_ROOT / "benchmarks" / "sysprompts"


def test_sysprompt_benchmark_assets_are_versioned():
    expected_paths = [
        "README.md",
        "run_deepseek_v4_flash.py",
        "cases/system_prompt_eval_cases.json",
        "rubrics/response_quality_rubric.json",
        "system_prompts/.gitkeep",
        "results/.gitkeep",
        "logs/.gitkeep",
        "tracing/.gitkeep",
        ".gitignore",
    ]

    for relative_path in expected_paths:
        assert (BENCHMARK_ROOT / relative_path).exists(), relative_path


def test_sysprompt_eval_cases_cover_complexity_levels_and_metrics():
    cases_path = BENCHMARK_ROOT / "cases" / "system_prompt_eval_cases.json"
    rubric_path = BENCHMARK_ROOT / "rubrics" / "response_quality_rubric.json"
    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    rubric_data = json.loads(rubric_path.read_text(encoding="utf-8"))
    cases = cases_data["cases"]

    assert {case["level"] for case in cases} == {"low", "medium", "high"}
    assert "medium_real_project_concise_map" in {case["id"] for case in cases}
    assert cases_data["default_provider"] == "deepseek"
    assert cases_data["default_model"] == "deepseek-v4-flash"
    for metric_name in cases_data["required_metrics"]:
        if metric_name != "overall_score":
            assert metric_name in rubric_data["metrics"]
    for metric_name in (
        "table_line_count",
        "non_dash_bullet_line_count",
        "decorative_marker_count",
    ):
        assert metric_name in rubric_data["objective_metrics"]

    for case in cases:
        assert case.get("max_table_lines") == 0
        assert case.get("max_non_dash_bullet_lines") == 0
        assert case.get("max_decorative_markers") == 0


def test_project_reading_cases_allow_only_read_only_tools():
    cases_path = BENCHMARK_ROOT / "cases" / "system_prompt_eval_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    read_only_tools = {"Read", "Grep", "Glob"}

    for case in cases:
        allowed_tools = set(case.get("allowed_tools") or [])
        required_tools = set(case.get("required_tools") or [])
        assert allowed_tools <= read_only_tools
        assert required_tools <= read_only_tools
