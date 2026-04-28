"""Skill discovery helpers for prompt surfaces and the Skill tool."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from personagent.domain.prompts.frontmatter import (
    as_bool,
    as_string_list,
    parse_markdown_frontmatter,
)

SKILL_STATE_VERSION = 1
PERSONAGENT_SKILL_STATE_PATH_ENV = "PERSONAGENT_SKILL_STATE_PATH"


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
    include_global: bool = True,
) -> list[SkillDefinition]:
    """Discover local skills using PersonAgent and Codex-compatible roots."""

    roots = skill_roots(
        workspace_root=workspace_root,
        cwd=cwd,
        extra_roots=extra_roots,
        include_global=include_global,
    )
    skills: dict[str, SkillDefinition] = {}
    for root in roots:
        for path in _iter_skill_files(root):
            skill = load_skill_file(path)
            if skill is not None:
                skills.setdefault(skill.invocation_name.lower(), skill)
    return sorted(skills.values(), key=lambda item: item.invocation_name)


def discover_enabled_skills(
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
    state_path: str | Path | None = None,
) -> list[SkillDefinition]:
    """Discover skills that should be exposed to the model/user prompt."""

    state = load_skill_activation_state(state_path)
    roots = list(
        skill_roots(
            workspace_root=workspace_root,
            cwd=cwd,
            extra_roots=extra_roots,
            include_global=False,
        )
    )
    roots.append(Path.home() / ".personagent" / "skills")

    skills: dict[str, SkillDefinition] = {}
    for root in _unique_roots(roots):
        for path in _iter_skill_files(root):
            skill = load_skill_file(path)
            if skill is not None and is_skill_enabled(
                skill,
                workspace_root=workspace_root,
                cwd=cwd,
                extra_roots=extra_roots,
                state=state,
            ):
                skills.setdefault(skill.invocation_name.lower(), skill)

    # Codex-global skills are intentionally opt-in for prompt surfaces. Only scan
    # that large root when an activated skill was not found in the smaller roots.
    missing_enabled = {key for key, enabled in state.items() if enabled} - set(skills)
    if missing_enabled:
        for path in _iter_skill_files(Path.home() / ".codex" / "skills"):
            skill = load_skill_file(path)
            if (
                skill is not None
                and skill.invocation_name.lower() in missing_enabled
                and is_skill_enabled(
                    skill,
                    workspace_root=workspace_root,
                    cwd=cwd,
                    extra_roots=extra_roots,
                    state=state,
                )
            ):
                skills.setdefault(skill.invocation_name.lower(), skill)
    return sorted(skills.values(), key=lambda item: item.invocation_name)


def find_skill(
    name: str,
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
    include_global: bool = True,
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
        include_global=include_global,
    ):
        candidate_keys = {
            _normalize_skill_invocation(skill.name).lower(),
            _normalize_skill_invocation(skill.path.parent.name).lower(),
            skill.invocation_name.lower(),
        }
        if normalized_key in candidate_keys or skill.name == normalized:
            return skill
    return None


def find_enabled_skill(
    name: str,
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
    state_path: str | Path | None = None,
) -> SkillDefinition | None:
    normalized = _normalize_skill_invocation(name.strip().lstrip("/")).lower()
    if not normalized:
        return None
    for skill in discover_enabled_skills(
        workspace_root=workspace_root,
        cwd=cwd,
        extra_roots=extra_roots,
        state_path=state_path,
    ):
        candidate_keys = {
            _normalize_skill_invocation(skill.name).lower(),
            _normalize_skill_invocation(skill.path.parent.name).lower(),
            skill.invocation_name.lower(),
        }
        if normalized in candidate_keys or skill.name == name:
            return skill
    return None


def skill_roots(
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
    include_global: bool = True,
) -> tuple[Path, ...]:
    roots: list[Path] = []
    if workspace_root:
        roots.append(Path(workspace_root).expanduser() / ".personagent" / "skills")
    if cwd:
        roots.append(Path(cwd).expanduser() / ".personagent" / "skills")
    roots.extend(Path(root).expanduser() for root in extra_roots)
    if include_global:
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


def skill_activation_state_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    override = os.environ.get(PERSONAGENT_SKILL_STATE_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".personagent" / "skills" / "state.json"


def load_skill_activation_state(path: str | Path | None = None) -> dict[str, bool]:
    state_file = skill_activation_state_path(path)
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    activation = raw.get("activation") if isinstance(raw, dict) else None
    if activation is None and isinstance(raw, dict):
        activation = raw
    if not isinstance(activation, dict):
        return {}
    return {
        _normalize_skill_invocation(str(key)).lower(): bool(value)
        for key, value in activation.items()
        if _normalize_skill_invocation(str(key))
    }


def save_skill_activation_state(
    activation: dict[str, bool],
    path: str | Path | None = None,
) -> None:
    state_file = skill_activation_state_path(path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    normalized = {
        _normalize_skill_invocation(str(key)).lower(): bool(value)
        for key, value in activation.items()
        if _normalize_skill_invocation(str(key))
    }
    payload = {
        "version": SKILL_STATE_VERSION,
        "activation": dict(sorted(normalized.items())),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    tmp_file = state_file.with_suffix(f"{state_file.suffix}.tmp")
    tmp_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_file.replace(state_file)


def set_skill_activation(
    invocation_name: str,
    enabled: bool,
    path: str | Path | None = None,
) -> bool:
    normalized = _normalize_skill_invocation(invocation_name).lower()
    if not normalized:
        raise ValueError("Skill name is required.")
    state = load_skill_activation_state(path)
    state[normalized] = bool(enabled)
    save_skill_activation_state(state, path)
    return state[normalized]


def is_skill_enabled(
    skill: SkillDefinition,
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
    state: dict[str, bool] | None = None,
    state_path: str | Path | None = None,
) -> bool:
    activation = state if state is not None else load_skill_activation_state(state_path)
    key = skill.invocation_name.lower()
    if key in activation:
        return activation[key]
    return default_skill_enabled(
        skill,
        workspace_root=workspace_root,
        cwd=cwd,
        extra_roots=extra_roots,
    )


def default_skill_enabled(
    skill: SkillDefinition,
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
) -> bool:
    return skill_source(
        skill,
        workspace_root=workspace_root,
        cwd=cwd,
        extra_roots=extra_roots,
    ) != "codex"


def skill_source(
    skill: SkillDefinition,
    *,
    workspace_root: str | Path | None = None,
    cwd: str | Path | None = None,
    extra_roots: tuple[str | Path, ...] = (),
) -> str:
    skill_path = _safe_resolve(skill.path)
    workspace_roots = []
    if workspace_root:
        workspace_roots.append(Path(workspace_root).expanduser() / ".personagent" / "skills")
    if cwd:
        workspace_roots.append(Path(cwd).expanduser() / ".personagent" / "skills")
    for root in _unique_roots(workspace_roots):
        if _is_relative_to(skill_path, root):
            return "workspace"

    home_personagent = Path.home() / ".personagent" / "skills"
    if _is_relative_to(skill_path, home_personagent):
        return "personagent"

    home_codex = Path.home() / ".codex" / "skills"
    if _is_relative_to(skill_path, home_codex):
        return "codex"

    for root in _unique_roots(Path(path).expanduser() for path in extra_roots):
        if _is_relative_to(skill_path, root):
            return "configured"

    return "local"


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


def _unique_roots(roots: Any) -> tuple[Path, ...]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = Path(root).expanduser().resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(_safe_resolve(root))
        return True
    except ValueError:
        return False


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
