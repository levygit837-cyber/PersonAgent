#!/usr/bin/env python3
"""Validate ADR-0022 folder structure principles.

Run manually (shows only NEW violations compared to baseline):
    cd @backend && python3 scripts/check_folder_principles.py

Run in strict mode (shows ALL violations):
    cd @backend && python3 scripts/check_folder_principles.py --strict

Update the baseline after intentional fixes:
    cd @backend && python3 scripts/check_folder_principles.py --update-baseline

Run via pre-commit (auto-installed):
    uv run pre-commit run --all-files

Exit 0 = clean (no new violations). Exit 1 = new violations found.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import NoReturn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SRC = Path(__file__).resolve().parent.parent / "src" / "personagent"
TESTS = Path(__file__).resolve().parent.parent / "tests"
BASELINE_PATH = Path(__file__).resolve().parent / "check_folder_principles_baseline.json"

# Principle 5 — forbidden generic folder names at layer roots
FORBIDDEN_ROOT_NAMES = {"config", "utils", "helpers", "common", "misc"}

# Principle 3 — allowed items at adapters/api/ root
API_ROOT_ALLOWLIST = {
    "main.py",
    "errors.py",
    "__init__.py",
    "__pycache__",
    "routes",
    "middleware",
}

# Principle 6 — allowed loose files at infrastructure/ root
INFRA_ROOT_ALLOWLIST: set[str] = {"__init__.py", "__pycache__"}

# ---------------------------------------------------------------------------
# Violation collector
# ---------------------------------------------------------------------------


class Violations:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, principle: str, path: str, detail: str) -> None:
        self.items.append(f"[{principle}] {path}: {detail}")

    def report(self, new_items: list[str] | None = None) -> NoReturn:
        display = new_items if new_items is not None else self.items
        if not display:
            if new_items is not None:
                print("✅ No new ADR-0022 violations. Baseline clean.")
            else:
                print("✅ All ADR-0022 principles satisfied.")
            sys.exit(0)

        if new_items is not None:
            print(f"❌ {len(display)} NEW ADR-0022 violation(s) found:\n")
        else:
            print(f"❌ {len(display)} ADR-0022 violation(s) found:\n")
        for item in display:
            print(f"  {item}")
        print()
        sys.exit(1)


V = Violations()

# ---------------------------------------------------------------------------
# Principle 1 — No single-file folders
# ---------------------------------------------------------------------------


def check_p1() -> None:
    """A folder with exactly one .py file (excluding __init__.py) and NO
    sub-folders (except __pycache__) is forbidden."""
    for root, dirs, files in os.walk(SRC):
        root_path = Path(root)
        rel = root_path.relative_to(SRC)

        # Skip __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]

        py_files = [f for f in files if f.endswith(".py") and f != "__init__.py"]

        # Skip if no .py files, or if the folder has sub-folders (it's a
        # natural container that may grow), or if more than 1 .py file.
        if len(py_files) != 1:
            continue
        if dirs:
            continue

        V.add(
            "P1",
            f"src/personagent/{rel}",
            f"single-file folder: only '{py_files[0]}' here; flatten to parent",
        )


# ---------------------------------------------------------------------------
# Principle 3 — adapters/api/ contains routes and middleware only
# ---------------------------------------------------------------------------


def check_p3() -> None:
    api_root = SRC / "adapters" / "api"
    if not api_root.exists():
        return

    for item in api_root.iterdir():
        if item.name in API_ROOT_ALLOWLIST:
            continue
        V.add(
            "P3",
            f"src/personagent/adapters/api/{item.name}",
            "loose file/folder at api/ root; move to routes/ or middleware/",
        )

    # Also check that routes/ doesn't have loose endpoint files
    routes_root = api_root / "routes"
    if routes_root.exists():
        for item in routes_root.iterdir():
            if item.is_dir() or item.name in {"__init__.py", "__pycache__"}:
                continue
            # Allow a small number of cross-cutting route files
            if item.name in {"conversations.py", "qa.py", "security.py", "skills.py"}:
                continue
            V.add(
                "P3",
                f"src/personagent/adapters/api/routes/{item.name}",
                "loose endpoint file; create a sub-folder or move to an existing group",
            )


# ---------------------------------------------------------------------------
# Principle 5 — No generic folder names at layer roots
# ---------------------------------------------------------------------------


def check_p5() -> None:
    layers = ["domain", "application", "infrastructure", "adapters"]
    for layer in layers:
        layer_path = SRC / layer
        if not layer_path.exists():
            continue
        for item in layer_path.iterdir():
            if item.is_dir() and item.name in FORBIDDEN_ROOT_NAMES:
                V.add(
                    "P5",
                    f"src/personagent/{layer}/{item.name}",
                    f"forbidden generic name '{item.name}'; use a concrete name",
                )


# ---------------------------------------------------------------------------
# Principle 6 — No loose .py files at infrastructure/ root
# ---------------------------------------------------------------------------


def check_p6() -> None:
    infra_root = SRC / "infrastructure"
    if not infra_root.exists():
        return

    for item in infra_root.iterdir():
        if item.is_file() and item.suffix == ".py" and item.name not in INFRA_ROOT_ALLOWLIST:
            V.add(
                "P6",
                f"src/personagent/infrastructure/{item.name}",
                "loose .py file at infrastructure/ root; move to a sub-folder",
            )


# ---------------------------------------------------------------------------
# Principle 7 — No personagent.interfaces imports remain
# ---------------------------------------------------------------------------


def check_p7() -> None:
    """Scan src/ and tests/ for any remaining 'personagent.interfaces' references."""
    targets = [SRC, TESTS]
    for base in targets:
        if not base.exists():
            continue
        for root, _dirs, files in os.walk(base):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = Path(root) / fname
                rel = fpath.relative_to(base.parent if base == TESTS else SRC.parent.parent.parent)
                try:
                    text = fpath.read_text(encoding="utf-8")
                except OSError:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if "personagent.interfaces" in line and not line.strip().startswith("#"):
                        V.add(
                            "P7",
                            str(rel) + f":{i}",
                            f"stale import: {line.strip()}",
                        )


# ---------------------------------------------------------------------------
# Baseline helpers
# ---------------------------------------------------------------------------


def load_baseline() -> set[str]:
    if not BASELINE_PATH.exists():
        return set()
    with BASELINE_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("violations", []))


def save_baseline(violations: list[str]) -> None:
    BASELINE_PATH.write_text(
        json.dumps({"violations": sorted(violations)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"📝 Baseline updated: {BASELINE_PATH}")
    print(f"   {len(violations)} violation(s) recorded as accepted.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate ADR-0022 folder structure principles.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Show ALL violations, not just new ones compared to baseline",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Regenerate the baseline with current violations",
    )
    args = parser.parse_args()

    if not SRC.exists():
        print(f"ERROR: source directory not found: {SRC}", file=sys.stderr)
        sys.exit(1)

    check_p1()
    check_p3()
    check_p5()
    check_p6()
    check_p7()

    if args.update_baseline:
        save_baseline(V.items)
        sys.exit(0)

    if args.strict:
        V.report()

    baseline = load_baseline()
    new_items = [item for item in V.items if item not in baseline]

    if new_items:
        print(f"❌ {len(new_items)} NEW ADR-0022 violation(s) found:")
        print(f"   (baseline has {len(baseline)} accepted violation(s))\n")
        for item in new_items:
            print(f"  {item}")
        print(f"\n  Run with --strict to see all {len(V.items)} violations.")
        print(f"  Run with --update-baseline after fixing intentional violations.")
        sys.exit(1)

    print("✅ No new ADR-0022 violations.")
    if baseline:
        print(f"   ({len(baseline)} accepted baseline violation(s) remain)")
    sys.exit(0)


if __name__ == "__main__":
    main()
