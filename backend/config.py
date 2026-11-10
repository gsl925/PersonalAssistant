from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from ruamel.yaml import YAML

# Round-trip loader/dumper — unlike PyYAML's safe_load/safe_dump, this
# preserves hand-written comments (e.g. "auto_wake: false  # verified
# working 2026-07-30...") across a load-then-dump cycle, so adding/removing
# a tracked project no longer silently wipes out every comment in the file.
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=2, offset=0)


# ---------------------------------------------------------------------------
# Capability tier helpers
# ---------------------------------------------------------------------------

class ModelEntry(dict):
    """A single {provider, model} entry in a capability tier fallback chain."""


CapabilityTiers = dict[str, list[dict[str, str]]]

DEFAULT_CAPABILITY_TIERS: CapabilityTiers = {
    "fast_text": [
        {"provider": "local", "model": "qwen3:8b"},
    ],
    "complex_reasoning": [
        {"provider": "local", "model": "deepseek-r1:14b"},
    ],
    "vision": [
        {"provider": "local", "model": "qwen3-vl:8b"},
        {"provider": "local", "model": "llava:7b"},
    ],
    # Literal text transcription (screenshot-agent's OCR step). Separate from
    # "vision" above. Order flipped 2026-11-10 after moving to llama.cpp: on
    # Ollama (2026-07-28, a dense real screenshot) qwen3-vl/deepseek-ocr
    # invented fictional content while minicpm-v stayed grounded; on llama.cpp
    # with this exact OCR prompt and a dense project-tracker screenshot,
    # qwen3-vl read 15/18 probe strings verbatim while minicpm-v got 12/18 and
    # paraphrased the rest (and looped on a different prompt). The two engines
    # disagree, so re-test with a few real screenshots if OCR quality matters
    # — note the default OCR engine is tesseract (SCREENSHOT_OCR_ENGINE), so
    # this tier only runs when that is set to "vlm".
    "ocr": [
        {"provider": "local", "model": "qwen3-vl:8b"},
        {"provider": "local", "model": "minicpm-v:8b"},
    ],
    "embedding": [
        {"provider": "local", "model": "bge-m3"},
    ],
    # Knowledge-base RAG answer generation (/api/chat/ask_kb, Telegram /kb) —
    # this is the default path (cloud is opt-in per call). Local-only, so
    # "local" results are never secretly cloud-assisted.
    # gemma4:26b is primary: live-tested 2026-10-05 against
    # qwen3:8b on the same question/context — 26b caught specific figures and
    # ranges (e.g. "1%~5%") that 8b dropped, closer to Claude's detail level,
    # at a real cost (~137s vs ~21s). qwen3:8b stays as the fast fallback.
    # qwen3.8:27b was tried too and timed out past 180s on this hardware —
    # not viable, so not included here.
    "rag_local": [
        {"provider": "local", "model": "gemma4:26b"},
        {"provider": "local", "model": "qwen3:8b"},
    ],
    # "What is the author actually arguing" extraction (backend/insight.py) —
    # deliberately its own tier rather than reusing "complex_reasoning", since
    # webclip-agent's summary task and this task have different quality
    # profiles per-model; keeping them separate lets a local-vs-cloud
    # comparison for this specific task pick its own winner without affecting
    # webclip-agent's tier. Decided 2026-08-05 after a real side-by-side on
    # two TechNews articles (verified against the actual source text, not
    # just vibes): gpt-oss:120b-cloud consistently surfaced the article's
    # real point (e.g. caught a "discoverability" angle deepseek-r1:14b's
    # output missed entirely). It was dropped from the chain when the app went
    # local-only (a "-cloud" model is only reachable through a local Ollama
    # daemon). Local replacement chosen 2026-11-10 from a 5-article A/B of the
    # real insight prompt: gemma4:26b wrote all 5 in Traditional Chinese and
    # stated the author's stance rather than restating the content, while
    # deepseek-r1:14b slipped into Simplified Chinese on 2 of 5 (~2x faster,
    # so it stays as the fallback).
    "insight_extraction": [
        {"provider": "local", "model": "gemma4:26b"},
        {"provider": "local", "model": "deepseek-r1:14b"},
    ],
    # Video digest (backend/video_digest.py): deliberately single-entry, no
    # fallback chain — unlike every tier above, this pair is called together
    # (local draft vs. cloud draft, then Claude Code judges the two), so one
    # tier silently falling back to the other model would defeat the whole
    # point of comparing them. A model failing here is handled by
    # video_digest.py itself (degrade to the other draft), not by the router.
    "video_digest_local": [
        {"provider": "local", "model": "deepseek-r1:14b"},
    ],
    # Tier name is historical: gpt-oss:120b-cloud used to fill this slot. Now
    # local-only, so a second, different local model supplies the other draft.
    "video_digest_cloud": [
        {"provider": "local", "model": "qwen3:8b"},
    ],
}

# Provider names that predate the engine-neutral "local" provider. Still
# accepted (in .env-supplied tiers, saved overrides, API payloads) and
# rewritten to "local" so old configs keep working.
LEGACY_LOCAL_PROVIDERS = frozenset({"ollama_local"})
LOCAL_PROVIDER = "local"


def normalize_capability_tiers(tiers: CapabilityTiers) -> CapabilityTiers:
    """Return a copy of ``tiers`` with legacy local provider names rewritten
    to the engine-neutral "local"."""
    return {
        tier: [
            {**entry, "provider": LOCAL_PROVIDER}
            if entry.get("provider") in LEGACY_LOCAL_PROVIDERS
            else dict(entry)
            for entry in chain
        ]
        for tier, chain in tiers.items()
    }


def _is_valid_tiers(data: Any) -> bool:
    return isinstance(data, dict) and all(
        isinstance(chain, list)
        and all(
            isinstance(e, dict) and isinstance(e.get("provider"), str) and isinstance(e.get("model"), str)
            for e in chain
        )
        for chain in data.values()
    )


# ---------------------------------------------------------------------------
# Main settings class
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "personal_assistant"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    # If provided directly, used as-is; otherwise constructed from components.
    DATABASE_URL: str = ""

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        return self

    # ------------------------------------------------------------------
    # Qdrant
    # ------------------------------------------------------------------
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    # Separate destination for todo reminders so they don't mix in with the
    # daily digest. Falls back to TELEGRAM_CHAT_ID when unset.
    TELEGRAM_TODO_CHAT_ID: str = ""

    # ------------------------------------------------------------------
    # Email (SMTP)
    # ------------------------------------------------------------------
    EMAIL_SMTP_HOST: str = "smtp.gmail.com"
    EMAIL_SMTP_PORT: int = 587
    EMAIL_USER: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_RECIPIENT: str = ""

    # ------------------------------------------------------------------
    # Local LLM server
    # ------------------------------------------------------------------
    # Two supported engines: llama.cpp behind llama-swap (default) and Ollama.
    # Ollama is never the silent fallback — it is used only when
    # LOCAL_LLM_ENGINE=ollama says so. LOCAL_LLM_BASE_URL, when set, overrides
    # the engine's default address (keep LOCAL_LLM_ENGINE matching what it
    # points at: dev_agent speaks a different wire format per engine).
    LOCAL_LLM_ENGINE: Literal["llama", "ollama"] = "llama"
    LOCAL_LLM_BASE_URL: str = ""
    LLAMA_SWAP_BASE_URL: str = "http://localhost:8090"
    OLLAMA_LOCAL_BASE_URL: str = "http://localhost:11434"
    OLLAMA_CLOUD_BASE_URL: str = ""
    OLLAMA_CLOUD_API_KEY: str = ""

    @property
    def local_base_url(self) -> str:
        if self.LOCAL_LLM_BASE_URL:
            return self.LOCAL_LLM_BASE_URL
        if self.LOCAL_LLM_ENGINE == "ollama":
            return self.OLLAMA_LOCAL_BASE_URL
        return self.LLAMA_SWAP_BASE_URL

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Path to the project root (parent of the backend package directory).
    BASE_DIR: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent
    )

    # ------------------------------------------------------------------
    # Derived paths (computed after BASE_DIR is known)
    # ------------------------------------------------------------------
    SKILLS_DIR: Path = Path()   # populated by validator below
    UPLOADS_DIR: Path = Path()  # populated by validator below
    PROJECTS_YAML_PATH: Path = Path()  # populated by validator below
    # Capability tiers saved from the settings page; see load_saved_capability_tiers().
    CAPABILITY_TIERS_PATH: Path = Path()  # populated by validator below

    @model_validator(mode="after")
    def build_derived_paths(self) -> "Settings":
        # Only set if they were not explicitly provided via env vars.
        if self.SKILLS_DIR == Path():
            self.SKILLS_DIR = self.BASE_DIR / "skills"
        if self.UPLOADS_DIR == Path():
            self.UPLOADS_DIR = self.BASE_DIR / "data" / "uploads"
        if self.PROJECTS_YAML_PATH == Path():
            self.PROJECTS_YAML_PATH = self.BASE_DIR / "projects.yaml"
        if self.CAPABILITY_TIERS_PATH == Path():
            self.CAPABILITY_TIERS_PATH = self.BASE_DIR / "data" / "capability_tiers.json"
        return self

    # ------------------------------------------------------------------
    # Capability tiers
    # ------------------------------------------------------------------
    CAPABILITY_TIERS: CapabilityTiers = Field(
        default_factory=lambda: DEFAULT_CAPABILITY_TIERS
    )

    # ------------------------------------------------------------------
    # Screenshot OCR engine
    # ------------------------------------------------------------------
    # "tesseract" (deterministic, local, no LLM call) or "vlm" (generative,
    # uses the "ocr" capability tier above). Kept switchable rather than a
    # hard replacement — VLM-OCR models are improving quickly and the user
    # wants to keep re-testing them; see project memory 2026-07-28.
    SCREENSHOT_OCR_ENGINE: str = "tesseract"
    # Path to the tesseract binary. Only needed on Windows where it's not on
    # PATH by default; leave empty to use whatever `tesseract` resolves to.
    TESSERACT_CMD: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESSERACT_LANG: str = "chi_tra+chi_sim+eng"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

settings = Settings()


def load_saved_capability_tiers() -> CapabilityTiers | None:
    """Tiers saved from the settings page, or None when there is no usable
    saved file (missing, unreadable, or malformed — logged, never raised, so a
    bad file can't stop the app from starting on the built-in defaults)."""
    path = settings.CAPABILITY_TIERS_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Ignoring unreadable {}: {}", path, exc)
        return None
    if not _is_valid_tiers(data):
        logger.error("Ignoring {}: expected {{tier: [{{provider, model}}, ...]}}", path)
        return None
    return normalize_capability_tiers(data)


def save_capability_tiers(tiers: CapabilityTiers) -> None:
    """Persist ``tiers`` so they survive a restart. Written to a temp file and
    renamed so a crash mid-write can't leave a truncated file behind."""
    path = settings.CAPABILITY_TIERS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(tiers, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


settings.CAPABILITY_TIERS = load_saved_capability_tiers() or normalize_capability_tiers(
    settings.CAPABILITY_TIERS
)


# ---------------------------------------------------------------------------
# Tracked projects (daily cross-project check-in — see
# DESIGN_每日跨專案進度確認機制.md)
# ---------------------------------------------------------------------------

class TrackedProject(BaseModel):
    name: str
    label: str
    repo_path: str
    enabled: bool = True
    # Opt-in per project: when a "📮 你的指示" item sits unprocessed too long,
    # project_sync.py fires an unattended, fully-autonomous `claude -p` call
    # scoped to this repo (can edit files / run Bash, no confirmation gate —
    # see claude_wake.py). Off by default since that's a meaningfully bigger
    # trust boundary than the read-only mailman relay.
    auto_wake: bool = False


def _yaml_dump(data: Any, path: Path) -> None:
    import io

    buf = io.StringIO()
    _yaml.dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


def load_tracked_projects() -> list[TrackedProject]:
    """Read projects.yaml fresh on every call (cheap — a handful of entries)
    so the list can be edited without restarting the backend. Returns only
    enabled projects; missing file or malformed entries log a warning and
    yield an empty list rather than raising, since the daily check-in job
    calling this must never crash the whole app over a config typo."""
    path = settings.PROJECTS_YAML_PATH
    if not path.exists():
        logger.warning("projects.yaml not found at {}; no projects tracked.", path)
        return []
    try:
        data = _yaml.load(path.read_text(encoding="utf-8")) or {}
        projects = [TrackedProject(**entry) for entry in data.get("projects", [])]
    except Exception as exc:
        logger.error("Failed to parse {}: {}", path, exc)
        return []
    return [p for p in projects if p.enabled]


def add_tracked_project(name: str, label: str, repo_path: str, auto_wake: bool = False) -> bool:
    """Append a new project entry to projects.yaml. Returns False if `name`
    already belongs to an existing entry (checked against every entry, not
    just enabled ones, so re-adding a disabled project's slug still
    collides). Used to onboard a brand-new tracked project — see
    project_sync.add_project().
    """
    path = settings.PROJECTS_YAML_PATH
    try:
        data = _yaml.load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as exc:
        logger.error("Failed to parse {}: {}", path, exc)
        data = {}
    data = data or {}
    entries = data.setdefault("projects", [])
    if any(e.get("name") == name for e in entries):
        return False
    entries.append(
        {"name": name, "label": label, "repo_path": repo_path, "enabled": True, "auto_wake": auto_wake}
    )
    _yaml_dump(data, path)
    return True


def remove_tracked_project(name: str) -> bool:
    """Remove a project entry from projects.yaml by its `name` slug.

    Returns False if the file or the named entry doesn't exist. Used by the
    Dashboard's "delete project" action to declutter tracked experiments —
    edits the config file directly since projects.yaml is the single source
    of truth load_tracked_projects() reads fresh on every call.
    """
    path = settings.PROJECTS_YAML_PATH
    if not path.exists():
        return False
    try:
        data = _yaml.load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.error("Failed to parse {}: {}", path, exc)
        return False
    entries = data.get("projects", [])
    matching_indices = [i for i, e in enumerate(entries) if e.get("name") == name]
    if not matching_indices:
        return False
    # Delete matching entries by index, in reverse, directly on the existing
    # CommentedSeq (rather than reassigning data["projects"] to a fresh
    # plain list) — ruamel keeps standalone/sequence-level comments aligned
    # with the remaining items' indices when you delete through its own
    # __delitem__, but a wholesale replacement loses that bookkeeping.
    for i in reversed(matching_indices):
        del entries[i]
    _yaml_dump(data, path)
    return True
