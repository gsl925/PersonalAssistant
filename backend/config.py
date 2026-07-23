from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
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

    @model_validator(mode="after")
    def build_derived_paths(self) -> "Settings":
        # Only set if they were not explicitly provided via env vars.
        if self.SKILLS_DIR == Path():
            self.SKILLS_DIR = self.BASE_DIR / "skills"
        if self.UPLOADS_DIR == Path():
            self.UPLOADS_DIR = self.BASE_DIR / "data" / "uploads"
        return self

    # ------------------------------------------------------------------
    # Capability tiers
    # ------------------------------------------------------------------
    CAPABILITY_TIERS: CapabilityTiers = Field(
        default_factory=lambda: DEFAULT_CAPABILITY_TIERS
    )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

settings = Settings()
