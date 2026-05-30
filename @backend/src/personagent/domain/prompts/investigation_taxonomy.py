"""Unified investigation taxonomy — single source of truth for depth levels,
surfaces, and their policies.

All other modules that need investigation-depth constants or surface
definitions must import from here rather than hardcode their own.
"""

from __future__ import annotations

from typing import Literal

InvestigationDepth = Literal["light", "standard", "deep", "exhaustive"]

# The repository surfaces the evidence gate tracks.
SURFACES = ["entrypoints", "domain", "adapters", "tests", "config"]

# Per-depth policy.  Only ``max_tool_iterations`` and ``required_surfaces``
# live here; evidence-gate caps are handled by the unified loop budget.
DEPTH_POLICIES: dict[InvestigationDepth, dict[str, object]] = {
    "light": {
        "max_tool_iterations": 3,
        "required_surfaces": (),
    },
    "standard": {
        "max_tool_iterations": 6,
        "required_surfaces": ("domain", "tests"),
    },
    "deep": {
        "max_tool_iterations": 12,
        "required_surfaces": ("entrypoints", "domain", "adapters", "tests"),
    },
    "exhaustive": {
        "max_tool_iterations": 24,
        "required_surfaces": tuple(SURFACES),
    },
}
