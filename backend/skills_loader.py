from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter
from loguru import logger


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SkillDefinition:
    name: str
    description: str
    model: str          # capability tier (e.g. "vision", "fast_text", "complex_reasoning")
    tools: list[str]
    enabled: bool
    output_schema: str
    version: str
    system_prompt: str  # the markdown body (everything after the YAML frontmatter)
    skill_dir: Path     # path to the folder that contains the SKILL.md


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_SKILL_FILENAME = "SKILL.md"

_REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "model",
    "enabled",
    "output_schema",
    "version",
)


class SkillsLoader:
    """Scan a skills directory, parse SKILL.md files, and provide routing data."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = Path(skills_dir)
        self._cache: dict[str, SkillDefinition] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> dict[str, SkillDefinition]:
        """Scan the skills directory and parse every SKILL.md found.

        Returns a dict keyed by skill *name* (from the frontmatter, not the
        folder name).  The result is also stored in the internal cache so that
        subsequent calls to :meth:`get_skill` do not re-read from disk.
        """
        if not self._skills_dir.exists():
            logger.warning(
                "Skills directory does not exist: {}", self._skills_dir
            )
            self._cache = {}
            return {}

        loaded: dict[str, SkillDefinition] = {}

        for skill_md_path in sorted(self._skills_dir.rglob(_SKILL_FILENAME)):
            try:
                skill = self._parse_skill_md(skill_md_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping {} — unexpected error while parsing: {}",
                    skill_md_path,
                    exc,
                )
                continue

            if skill is None:
                continue

            if skill.name in loaded:
                logger.warning(
                    "Duplicate skill name '{}' found at {}. "
                    "The earlier definition (from {}) will be overwritten.",
                    skill.name,
                    skill_md_path,
                    loaded[skill.name].skill_dir / _SKILL_FILENAME,
                )

            loaded[skill.name] = skill
            logger.debug("Loaded skill '{}' from {}", skill.name, skill_md_path)

        self._cache = loaded
        logger.info(
            "Loaded {total} skill(s) ({enabled} enabled) from {dir}",
            total=len(loaded),
            enabled=sum(1 for s in loaded.values() if s.enabled),
            dir=self._skills_dir,
        )
        return dict(self._cache)

    def get_enabled_skills(self) -> list[SkillDefinition]:
        """Return only the enabled :class:`SkillDefinition` objects.

        Uses the in-memory cache; call :meth:`load_all` first (or
        :meth:`reload`) to populate it.
        """
        return [s for s in self._cache.values() if s.enabled]

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """Look up a skill by name from the cache.

        Returns ``None`` when the skill is not found.
        """
        return self._cache.get(name)

    def reload(self) -> dict[str, SkillDefinition]:
        """Flush the cache and re-scan the skills directory from disk."""
        logger.info("Reloading skills from {}", self._skills_dir)
        self._cache = {}
        return self.load_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_skill_md(self, path: Path) -> Optional[SkillDefinition]:
        """Parse a single SKILL.md file.

        Returns a :class:`SkillDefinition` on success or ``None`` when the
        file is malformed or missing required fields.
        """
        try:
            post = frontmatter.load(str(path))
        except FileNotFoundError:
            logger.warning("SKILL.md not found (may have been deleted): {}", path)
            return None
        except Exception as exc:  # noqa: BLE001  — covers YAML parse errors
            logger.warning("Failed to parse YAML frontmatter in {}: {}", path, exc)
            return None

        meta: dict = post.metadata  # type: ignore[assignment]
        body: str = post.content.strip()

        # ---- Validate required fields ------------------------------------
        missing = [f for f in _REQUIRED_FIELDS if f not in meta]
        if missing:
            logger.warning(
                "Skipping {} — missing required frontmatter field(s): {}",
                path,
                missing,
            )
            return None

        # ---- Extract fields with safe defaults ---------------------------
        name: str = str(meta["name"]).strip()
        if not name:
            logger.warning("Skipping {} — 'name' field is empty.", path)
            return None

        description: str = str(meta.get("description", "")).strip()
        model: str = str(meta["model"]).strip()
        tools: list[str] = _coerce_string_list(meta.get("tools", []), path, "tools")
        enabled: bool = bool(meta["enabled"])
        output_schema: str = str(meta.get("output_schema", "")).strip()
        version: str = str(meta["version"]).strip()

        return SkillDefinition(
            name=name,
            description=description,
            model=model,
            tools=tools,
            enabled=enabled,
            output_schema=output_schema,
            version=version,
            system_prompt=body,
            skill_dir=path.parent,
        )


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------

def _coerce_string_list(value: object, path: Path, field_name: str) -> list[str]:
    """Convert *value* to a list of strings, logging a warning on type mismatch."""
    if value is None:
        return []
    if isinstance(value, list):
        coerced = []
        for item in value:
            if not isinstance(item, str):
                logger.warning(
                    "{}: field '{}' contains a non-string item {!r}; converting to str.",
                    path,
                    field_name,
                    item,
                )
            coerced.append(str(item))
        return coerced
    # Scalar (e.g. a single tool name given as a bare string)
    logger.warning(
        "{}: field '{}' expected a list but got {!r}; wrapping in a list.",
        path,
        field_name,
        value,
    )
    return [str(value)]
