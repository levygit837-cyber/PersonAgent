from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "team_mode_benchmark.py"
_SPEC = importlib.util.spec_from_file_location("team_mode_benchmark", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
team_mode_benchmark = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = team_mode_benchmark
_SPEC.loader.exec_module(team_mode_benchmark)

SCENARIOS = team_mode_benchmark.SCENARIOS
TARGETS = team_mode_benchmark.TARGETS
Scenario = team_mode_benchmark.Scenario
compare_runs = team_mode_benchmark.compare_runs
hard_gate_failures_for = team_mode_benchmark.hard_gate_failures_for
selected_scenarios = team_mode_benchmark.selected_scenarios


def test_benchmark_has_expanded_scenario_coverage():
    scenario_ids = {scenario.id for scenario in SCENARIOS}

    assert len(SCENARIOS) >= 10
    assert {
        "tool_read_write_audit",
        "conflict_resolution",
        "coverage_gap_redirect",
        "evidence_grounding",
        "latency_vote_skip",
        "memory_contamination_guard",
    } <= scenario_ids
    assert selected_scenarios("all") == list(SCENARIOS)


def test_hard_gates_fail_missing_tools_and_high_vote_overhead():
    scenario = Scenario(
        id="tool_case",
        name="Tool case",
        messages=("Use tools",),
        expected_terms=("tool",),
        requires_tools=True,
    )

    failures = hard_gate_failures_for(
        scenario=scenario,
        turn_index=1,
        status="team_run_completed",
        vote_overhead_ratio=TARGETS["vote_overhead_ratio"] + 0.01,
        independent_overlap=None,
        overlap_reduction=None,
        duplicate_claim_ratio=0.0,
        coverage_ratio=1.0,
        avg_coherency_score=1.0,
        tool_phase_count=0,
        tool_result_count=0,
        tool_proposal_count=0,
        workspace_memory_present=True,
        expected_term_hits=1,
        expected_term_total=1,
    )

    assert f"vote_overhead>{TARGETS['vote_overhead_ratio']}" in failures
    assert "tool_phase_missing" in failures
    assert "tool_result_missing" in failures
    assert "mutating_proposal_missing" in failures


def test_compare_runs_reports_quality_latency_and_token_delta():
    runs = [
        {
            "scenario_id": "s1",
            "repetition": 1,
            "turns": [
                {
                    "analysis": {
                        "score": 90,
                        "wall_ms": 2000,
                        "estimated_output_tokens": 1200,
                        "avg_agent_tps": 80,
                    }
                }
            ],
        }
    ]
    baselines = [
        {
            "scenario_id": "s1",
            "repetition": 1,
            "turns": [
                {
                    "analysis": {
                        "quality_score": 75,
                        "wall_ms": 1000,
                        "estimated_output_tokens": 400,
                        "tokens_per_second": 40,
                    }
                }
            ],
        }
    ]

    comparison = compare_runs(runs, baselines)[0]

    assert comparison["quality_gain_pct"] == 20.0
    assert comparison["latency_overhead_pct"] == 100.0
    assert comparison["token_overhead_pct"] == 200.0
    assert comparison["throughput_gain_pct"] == 100.0
