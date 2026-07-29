from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Capability tier helpers
# ---------------------------------------------------------------------------

class ModelEntry(dict):
    """A single {provider, model} entry in a capability tier fallback chain."""


CapabilityTiers = dict[str, list[dict[str, str]]]

DEFAULT_CAPABILITY_TIERS: CapabilityTiers = {
    "fast_text": [
        {"provider": "ollama_local", "model": "qwen3:8b"},
        {"provider": "ollama_local", "model": "gpt-oss:120b-cloud"},
    ],
    "complex_reasoning": [
        {"provider": "ollama_local", "model": "deepseek-r1:14b"},
        {"provider": "ollama_local", "model": "gpt-oss:120b-cloud"},
    ],
    "vision": [
        {"provider": "ollama_local", "model": "qwen3-vl:8b"},
        {"provider": "ollama_local", "model": "llava:7b"},
    ],
    # Literal text transcription (screenshot-agent's OCR step). Separate from
    # "vision" above — general VLMs (qwen3-vl, llava) confabulate a plausible
    # but fictional narrative on dense/small-text screenshots instead of
    # admitting they can't read it; minicpm-v is specifically OCR-tuned and
    # stayed grounded in the real content on the same test image (live-tested
    # 2026-07-28 against a real dense screenshot — qwen3-vl/deepseek-ocr both
    # invented entirely fictional content, minicpm-v got most of it right).
    "ocr": [
        {"provider": "ollama_local", "model": "minicpm-v:8b"},
        {"provider": "ollama_local", "model": "qwen3-vl:8b"},
    ],
    "embedding": [
        {"provider": "ollama_local", "model": "bge-m3"},
    ],
}


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
    # Ollama
    # ------------------------------------------------------------------
    OLLAMA_LOCAL_BASE_URL: str = "http://localhost:11434"
    OLLAMA_CLOUD_BASE_URL: str = ""
    OLLAMA_CLOUD_API_KEY: str = ""

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

    @model_validator(mode="after")
    def build_derived_paths(self) -> "Settings":
        # Only set if they were not explicitly provided via env vars.
        if self.SKILLS_DIR == Path():
            self.SKILLS_DIR = self.BASE_DIR / "skills"
        if self.UPLOADS_DIR == Path():
            self.UPLOADS_DIR = self.BASE_DIR / "data" / "uploads"
        if self.PROJECTS_YAML_PATH == Path():
            self.PROJECTS_YAML_PATH = self.BASE_DIR / "projects.yaml"
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


# ---------------------------------------------------------------------------
# Tracked projects (daily cross-project check-in — see
# DESIGN_每日跨專案進度確認機制.md)
# ---------------------------------------------------------------------------

class TrackedProject(BaseModel):
    name: str
    label: str
    repo_path: str
    enabled: bool = True


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
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        projects = [TrackedProject(**entry) for entry in data.get("projects", [])]
    except Exception as exc:
        logger.error("Failed to parse {}: {}", path, exc)
        return []
    return [p for p in projects if p.enabled]
