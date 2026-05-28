#!/usr/bin/env python3
"""CLI entry point for running stress tests with reporting.

Usage:
    python -m scripts.run_stress_tests --layers 1,2,3,4
    python -m scripts.run_stress_tests --layers 1,2 --report markdown
    python -m scripts.run_stress_tests --layers all --output-dir .benchmarks/stress
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


LAYER_MAP = {
    "1": "tests/stress/layer1_micro",
    "2": "tests/stress/layer2_pipeline",
    "3": "tests/stress/layer3_concurrency",
    "4": "tests/stress/layer4_scenarios",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PersonAgent stress tests")
    parser.add_argument(
        "--layers",
        default="all",
        help="Comma-separated layer numbers (1,2,3,4) or 'all'",
    )
    parser.add_argument(
        "--report",
        default="markdown,json",
        help="Report formats: json, markdown, or both (comma-separated)",
    )
    parser.add_argument(
        "--output-dir",
        default=".benchmarks/stress",
        help="Output directory for reports",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose pytest output",
    )
    parser.add_argument(
        "--benchmark-disable",
        action="store_true",
        help="Disable pytest-benchmark (faster runs)",
    )
    args = parser.parse_args()

    layers = parse_layers(args.layers)
    report_formats = [f.strip() for f in args.report.split(",")]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_label = f"stress_report_{timestamp}"

    print(f"Running stress tests for layers: {', '.join(layers)}")
    print(f"Output directory: {output_dir}")
    print()

    all_results = {}
    total_passed = 0
    total_failed = 0

    for layer_num in layers:
        layer_dir = LAYER_MAP[layer_num]
        print(f"--- Layer {layer_num}: {layer_dir} ---")

        cmd = [
            sys.executable, "-m", "pytest",
            layer_dir,
            "-v" if args.verbose else "--no-header",
            "-x",
            "--tb=short",
            "-m", "stress",
        ]
        if args.benchmark_disable:
            cmd.append("--benchmark-disable")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        passed = result.stdout.count(" PASSED")
        failed = result.stdout.count(" FAILED")
        total_passed += passed
        total_failed += failed

        all_results[f"layer_{layer_num}"] = {
            "passed": passed,
            "failed": failed,
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-2000:] if result.stdout else "",
            "stderr_tail": result.stderr[-1000:] if result.stderr else "",
        }

        status = "PASS" if result.returncode == 0 else "FAIL"
        print(f"  [{status}] {passed} passed, {failed} failed")
        if result.returncode != 0 and result.stderr:
            for line in result.stderr.strip().split("\n")[-5:]:
                print(f"  ! {line}")
        print()

    # Summary
    print("=" * 60)
    print(f"TOTAL: {total_passed} passed, {total_failed} failed")
    print("=" * 60)

    # Generate reports
    if "json" in report_formats:
        json_path = output_dir / f"{report_label}.json"
        report_data = {
            "timestamp": timestamp,
            "layers": layers,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "results": all_results,
        }
        json_path.write_text(json.dumps(report_data, indent=2, default=str))
        print(f"\nJSON report: {json_path}")

    if "markdown" in report_formats:
        md_path = output_dir / f"{report_label}.md"
        md = generate_markdown(timestamp, layers, all_results, total_passed, total_failed)
        md_path.write_text(md)
        print(f"Markdown report: {md_path}")

    sys.exit(1 if total_failed > 0 else 0)


def parse_layers(layers_str: str) -> list[str]:
    if layers_str.strip().lower() == "all":
        return ["1", "2", "3", "4"]
    return [l.strip() for l in layers_str.split(",") if l.strip() in LAYER_MAP]


def generate_markdown(
    timestamp: str,
    layers: list[str],
    results: dict,
    total_passed: int,
    total_failed: int,
) -> str:
    lines = [
        f"# Stress Test Report — {timestamp}",
        "",
        f"**Total**: {total_passed} passed, {total_failed} failed",
        "",
    ]

    for layer_num in layers:
        key = f"layer_{layer_num}"
        r = results.get(key, {})
        status = "PASS" if r.get("returncode") == 0 else "FAIL"
        lines.append(f"## Layer {layer_num}: {LAYER_MAP[layer_num]} — [{status}]")
        lines.append(f"- Passed: {r.get('passed', 0)}")
        lines.append(f"- Failed: {r.get('failed', 0)}")
        lines.append("")

        # Extract benchmark summary if present
        stdout = r.get("stdout_tail", "")
        if "benchmark:" in stdout:
            lines.append("### Benchmark Summary")
            lines.append("```")
            for line in stdout.split("\n"):
                if "Name (" in line or "-----" in line or "Legend:" in line or "Outliers" in line:
                    continue
                if any(c in line for c in ["(1.0)", "(0.00)"]) or "benchmark:" in line.lower():
                    lines.append(line.strip())
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
name__ == "__main__":
    main()
