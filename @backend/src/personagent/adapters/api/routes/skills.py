"""Skill inventory, activation, and local marketplace routes."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from personagent.adapters.api.routes.workspace_grants import resolve_workspace_root
from personagent.adapters.composition import get_container
from personagent.domain.prompts.skills import (
    SkillDefinition,
    discover_skills,
    is_skill_enabled,
    load_skill_file,
    set_skill_activation,
    skill_source,
)

router = APIRouter(prefix="/skills", tags=["skills"])

MARKETPLACE_ROOT = Path(__file__).resolve().parent / "skill_marketplace"


class SkillSummary(BaseModel):
    name: str
    invocation_name: str
    slash_name: str
    description: str
    source: str
    path: str
    enabled: bool
    user_invocable: bool
    model_invocable: bool
    allowed_tools: list[str] = Field(default_factory=list)
    argument_hint: str | None = None
    when_to_use: str | None = None
    context: str


class SkillDetail(SkillSummary):
    content: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)


class SkillActivationRequest(BaseModel):
    enabled: bool


class SkillActivationResponse(BaseModel):
    invocation_name: str
    enabled: bool


class SkillMarketplaceItem(BaseModel):
    id: str
    name: str
    invocation_name: str
    slash_name: str
    description: str
    allowed_tools: list[str] = Field(default_factory=list)
    argument_hint: str | None = None
    when_to_use: str | None = None
    installed: bool


class SkillMarketplaceInstallResponse(BaseModel):
    item: SkillMarketplaceItem
    installed_path: str


@router.get("", response_model=list[SkillSummary])
async def list_skills(
    workspace_root: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
) -> list[SkillSummary]:
    root, extra_roots = _skill_context(workspace_root, workspace_id)
    skills = discover_skills(
        workspace_root=root,
        cwd=root,
        extra_roots=extra_roots,
        include_global=True,
    )
    return [
        _summary(skill, workspace_root=root, cwd=root, extra_roots=extra_roots)
        for skill in skills
    ]


@router.get("/marketplace", response_model=list[SkillMarketplaceItem])
async def list_marketplace_skills(
    workspace_root: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
) -> list[SkillMarketplaceItem]:
    installed = _installed_invocation_names(workspace_root, workspace_id)
    return [_marketplace_item(skill, installed) for _, skill in _marketplace_skills()]


@router.post("/marketplace/{item_id}/install", response_model=SkillMarketplaceInstallResponse)
async def install_marketplace_skill(
    item_id: str,
    workspace_root: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
) -> SkillMarketplaceInstallResponse:
    marketplace_item = _find_marketplace_item(item_id)
    if marketplace_item is None:
        raise HTTPException(status_code=404, detail=f"Marketplace skill not found: {item_id}")

    source_dir = marketplace_item[1].path.parent
    destination = Path.home() / ".personagent" / "skills" / marketplace_item[0]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copytree(source_dir, destination)

    set_skill_activation(marketplace_item[1].invocation_name, True)
    installed = _installed_invocation_names(workspace_root, workspace_id)
    installed.add(marketplace_item[1].invocation_name.lower())
    return SkillMarketplaceInstallResponse(
        item=_marketplace_item(marketplace_item[1], installed),
        installed_path=str(destination / marketplace_item[1].path.name),
    )


@router.get("/{invocation_name}", response_model=SkillDetail)
async def get_skill_detail(
    invocation_name: str,
    workspace_root: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
) -> SkillDetail:
    root, extra_roots = _skill_context(workspace_root, workspace_id)
    skill = _find_installed_skill(invocation_name, root, extra_roots)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {invocation_name}")
    summary = _summary(skill, workspace_root=root, cwd=root, extra_roots=extra_roots)
    return SkillDetail(
        **summary.model_dump(),
        content=skill.body,
        frontmatter=skill.metadata,
    )


@router.patch("/{invocation_name}/activation", response_model=SkillActivationResponse)
async def update_skill_activation(
    invocation_name: str,
    request: SkillActivationRequest,
    workspace_root: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
) -> SkillActivationResponse:
    root, extra_roots = _skill_context(workspace_root, workspace_id)
    skill = _find_installed_skill(invocation_name, root, extra_roots)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {invocation_name}")
    enabled = set_skill_activation(skill.invocation_name, request.enabled)
    return SkillActivationResponse(invocation_name=skill.invocation_name, enabled=enabled)


def _skill_context(
    workspace_root: str | None,
    workspace_id: str | None = None,
) -> tuple[str | None, tuple[str | Path, ...]]:
    container = get_container()
    runtime_config = container.get_tool_runtime_config()
    if workspace_root or workspace_id:
        try:
            root = str(resolve_workspace_root(workspace_id=workspace_id, workspace_root=workspace_root))
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    else:
        root = str(runtime_config.workspace_root)
    return root, tuple(runtime_config.skill_roots)


def _find_installed_skill(
    invocation_name: str,
    workspace_root: str | None,
    extra_roots: tuple[str | Path, ...],
) -> SkillDefinition | None:
    normalized = invocation_name.strip().lstrip("/").lower()
    for skill in discover_skills(
        workspace_root=workspace_root,
        cwd=workspace_root,
        extra_roots=extra_roots,
        include_global=True,
    ):
        if normalized in {
            skill.invocation_name.lower(),
            skill.slash_name.lstrip("/").lower(),
            skill.path.parent.name.lower(),
        }:
            return skill
    return None


def _summary(
    skill: SkillDefinition,
    *,
    workspace_root: str | None,
    cwd: str | None,
    extra_roots: tuple[str | Path, ...],
) -> SkillSummary:
    return SkillSummary(
        name=skill.name,
        invocation_name=skill.invocation_name,
        slash_name=skill.slash_name,
        description=skill.description,
        source=skill_source(
            skill,
            workspace_root=workspace_root,
            cwd=cwd,
            extra_roots=extra_roots,
        ),
        path=str(skill.path),
        enabled=is_skill_enabled(
            skill,
            workspace_root=workspace_root,
            cwd=cwd,
            extra_roots=extra_roots,
        ),
        user_invocable=skill.user_invocable,
        model_invocable=skill.model_invocable,
        allowed_tools=list(skill.allowed_tools),
        argument_hint=skill.argument_hint,
        when_to_use=skill.when_to_use,
        context=skill.context,
    )


def _marketplace_skills() -> list[tuple[str, SkillDefinition]]:
    if not MARKETPLACE_ROOT.is_dir():
        return []
    items: list[tuple[str, SkillDefinition]] = []
    for path in sorted(MARKETPLACE_ROOT.glob("*/SKILL.md")):
        skill = load_skill_file(path)
        if skill is not None:
            items.append((path.parent.name, skill))
    return items


def _find_marketplace_item(item_id: str) -> tuple[str, SkillDefinition] | None:
    for marketplace_id, skill in _marketplace_skills():
        if marketplace_id == item_id:
            return marketplace_id, skill
    return None


def _marketplace_item(
    skill: SkillDefinition,
    installed_invocation_names: set[str],
) -> SkillMarketplaceItem:
    return SkillMarketplaceItem(
        id=skill.path.parent.name,
        name=skill.name,
        invocation_name=skill.invocation_name,
        slash_name=skill.slash_name,
        description=skill.description,
        allowed_tools=list(skill.allowed_tools),
        argument_hint=skill.argument_hint,
        when_to_use=skill.when_to_use,
        installed=skill.invocation_name.lower() in installed_invocation_names,
    )


def _installed_invocation_names(
    workspace_root: str | None,
    workspace_id: str | None = None,
) -> set[str]:
    root, extra_roots = _skill_context(workspace_root, workspace_id)
    return {
        skill.invocation_name.lower()
        for skill in discover_skills(
            workspace_root=root,
            cwd=root,
            extra_roots=extra_roots,
            include_global=True,
        )
    }
