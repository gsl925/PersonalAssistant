"""Agents API router — list, inspect, and toggle SKILL.md-defined agents."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import frontmatter
from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel

from backend.config import settings
from backend.skills_loader import SkillDefinition, SkillsLoader

router = APIRouter(prefix="/api/agents", tags=["agents"])

_SKILL_FILENAME = "SKILL.md"


# ---------------------------------------------------------------------------
# Dependency: skills loader
# ---------------------------------------------------------------------------


def _get_skills_loader() -> SkillsLoader:
    from backend.main import get_skills_loader
    return get_skills_loader()


SkillsDep = Annotated[SkillsLoader, Depends(_get_skills_loader)]


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AgentOut(BaseModel):
    name: str
    description: str
    model: str
    tools: list[str]
    enabled: bool
    output_schema: str
    version: str
    skill_dir: str


class AgentToggleResponse(BaseModel):
    name: str
    enabled: bool
    message: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _skill_to_out(skill: SkillDefinition) -> AgentOut:
    return AgentOut(
        name=skill.name,
        description=skill.description,
        model=skill.model,
        tools=skill.tools,
        enabled=skill.enabled,
        output_schema=skill.output_schema,
        version=skill.version,
        skill_dir=str(skill.skill_dir),
    )


def _toggle_skill_md(skill: SkillDefinition, enabled: bool) -> None:
    """Rewrite the SKILL.md frontmatter's `enabled` field in-place."""
    skill_md_path = skill.skill_dir / _SKILL_FILENAME
    try:
        post = frontmatter.load(str(skill_md_path))
    except Exception as exc:
        raise RuntimeError(f"Cannot read {skill_md_path}: {exc}") from exc

    post.metadata["enabled"] = enabled

    try:
        with skill_md_path.open("w", encoding="utf-8") as fh:
            fh.write(frontmatter.dumps(post))
    except Exception as exc:
        raise RuntimeError(f"Cannot write {skill_md_path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[AgentOut])
async def list_agents(loader: SkillsDep) -> list[AgentOut]:
    """Return all loaded skills with their current status."""
    # Reload from disk on each call so edits are reflected immediately.
    all_skills = loader.reload()
    return [_skill_to_out(s) for s in all_skills.values()]


@router.get("/{agent_name}", response_model=AgentOut)
async def get_agent(agent_name: str, loader: SkillsDep) -> AgentOut:
    """Return details for a single skill by name."""
    # Ensure cache is fresh.
    loader.reload()
    skill = loader.get_skill(agent_name)
    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found.",
        )
    return _skill_to_out(skill)


@router.patch("/{agent_name}/toggle", response_model=AgentToggleResponse)
async def toggle_agent(agent_name: str, loader: SkillsDep) -> AgentToggleResponse:
    """Enable the skill if it is currently disabled, or disable it if enabled.

    The change is persisted by rewriting the ``enabled`` field in the
    corresponding SKILL.md frontmatter.
    """
    loader.reload()
    skill = loader.get_skill(agent_name)
    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found.",
        )

    new_state = not skill.enabled
    logger.info(
        "Toggling agent '{}': {} → {}",
        agent_name,
        skill.enabled,
        new_state,
    )

    try:
        _toggle_skill_md(skill, new_state)
    except RuntimeError as exc:
        logger.exception("Failed to toggle agent '{}': {}", agent_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # Reload so the in-memory cache reflects the new state.
    loader.reload()

    action = "enabled" if new_state else "disabled"
    return AgentToggleResponse(
        name=agent_name,
        enabled=new_state,
        message=f"Agent '{agent_name}' has been {action}.",
    )
