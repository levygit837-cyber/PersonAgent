"""Skill discovery helpers for prompt surfaces and the Skill tool."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personagent.domain.prompts.frontmatter import (
    as_bool,
    as_string_list,
    parse_markdown_frontmatter,
)


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    """Metadata and body for a local SKILL.md file."""

    name: str
    body: str
    path: Path
    description: str = ""
    allowed_tools: tuple[str, ...] = ()
    argument_hint: str | None = None
    model: str | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    model_invocable: bool = True
    when_to_use: str | None = None
    context: str = "inline"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def invocation_name(self) -> str:
        return _normalize_skill_invocation(self.name) or _normalize_skill_invocation(
            self.path.parent.name
        )

    @property
    def slash_name(self) -> str:
        return f"/{self.invocation_name}"

    def to_inventory_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "invocation_name": self.invocation_name,
            "slash_name": self.slash_name,
            "description": self.description,
            "allowed_tools": list(self.allowed_tools),
            "argument_hint": self.argument_hint,
            "model": self.model,
            "disable_model_invocation": self.disable_model_invocation,
            "user_invocable": self.user_invocable,
            "model_invocable": self.model_invocable,
            "when_to_use": self.when_to_use,
            "context": self.context,
            "path": str(self.path),
        }


def discover_skills(
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
) -> list[SkillDefinition]:
    """Discover local skills using PersonAgent and Codex-compatible roots."""

    roots = skill_roots(workspace_root=workspace_root, cwd=cwd, extra_roots=extra_roots)
    skills: dict[str, SkillDefinition] = {}
    for root in roots:
        for path in _iter_skill_files(root):
            skill = load_skill_file(path)
            if skill is not None:
                skills.setdefault(skill.invocation_name.lower(), skill)
    return sorted(skills.values(), key=lambda item: item.invocation_name)


def find_skill(
    name: str,
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
) -> SkillDefinition | None:
    """Find a skill by frontmatter name or directory name."""

    normalized = name.strip().lstrip("/")
    if not normalized:
        return None
    normalized_key = _normalize_skill_invocation(normalized).lower()
    for skill in discover_skills(
        workspace_root=workspace_root,
        cwd=cwd,
        extra_roots=extra_roots,
    ):
        candidate_keys = {
            _normalize_skill_invocation(skill.name).lower(),
            _normalize_skill_invocation(skill.path.parent.name).lower(),
            skill.invocation_name.lower(),
        }
        if normalized_key in candidate_keys or skill.name == normalized:
            return skill
    return None


def skill_roots(
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
) -> tuple[Path, ...]:
    roots: list[Path] = []
    if workspace_root:
        roots.append(Path(workspace_root).expanduser() / ".personagent" / "skills")
    if cwd:
        roots.append(Path(cwd).expanduser() / ".personagent" / "skills")
    roots.extend(Path(root).expanduser() for root in extra_roots)
    roots.extend(
        [
            Path.home() / ".personagent" / "skills",
            Path.home() / ".codex" / "skills",
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def load_skill_file(path: Path) -> SkillDefinition | None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    frontmatter, body = parse_markdown_frontmatter(content)
    if not body.strip():
        return None
    name = str(frontmatter.get("name") or path.parent.name).strip()
    if not name:
        return None
    description = str(frontmatter.get("description") or "").strip()
    return SkillDefinition(
        name=name,
        body=body,
        path=path,
        description=description,
        allowed_tools=as_string_list(frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools")),
        argument_hint=_optional_str(
            frontmatter.get("argument-hint") or frontmatter.get("argument_hint")
        ),
        model=_optional_str(frontmatter.get("model")),
        disable_model_invocation=as_bool(
            frontmatter.get("disable-model-invocation")
            or frontmatter.get("disable_model_invocation")
        ),
        user_invocable=as_bool(
            frontmatter.get("user-invocable") or frontmatter.get("user_invocable"),
            default=True,
        ),
        model_invocable=not as_bool(
            frontmatter.get("disable-model-invocation")
            or frontmatter.get("disable_model_invocation")
        ),
        when_to_use=_optional_str(frontmatter.get("when_to_use") or frontmatter.get("when-to-use")),
        context=str(frontmatter.get("context") or "inline"),
        metadata=frontmatter,
    )


def _iter_skill_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    candidates: set[Path] = set()
    candidates.update(path for path in root.glob("*.md") if path.is_file())
    for name in ("SKILL.md", "skill.md"):
        candidates.update(path for path in root.rglob(name) if path.is_file())
    return sorted(candidates)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_skill_invocation(value: str) -> str:
    normalized = value.strip().strip("/")
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized.lower()
