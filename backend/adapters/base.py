from __future__ import annotations

import shutil
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from backend.config import settings


@dataclass
class ProcessedContent:
    """Unified output produced by every adapter before entering the processing pipeline."""

    source_type: str
    original_content: str
    title: str | None = None
    file_path: str | None = None
    source_url: str | None = None
    metadata: dict = field(default_factory=dict)
    # LLM-corrected version of original_content, set only when original_content
    # came from whisper — see backend/adapters/transcript_correction.py.
    corrected_content: str | None = None


class BaseAdapter(ABC):
    """Abstract base for all input-source adapters."""

    source_type: str = "unknown"

    def __init__(self, model_router, uploads_dir: Path | None = None) -> None:
        self.model_router = model_router
        self.uploads_dir = uploads_dir or settings.UPLOADS_DIR
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def process(self, input_data: Any) -> ProcessedContent:  # noqa: ANN401
        """Transform *input_data* into a :class:`ProcessedContent` object."""

    def _save_file(self, source_path: Path, suffix: str | None = None) -> Path:
        """Copy *source_path* into the uploads directory with a UUID filename."""
        suffix = suffix or source_path.suffix
        dest = self.uploads_dir / f"{uuid.uuid4()}{suffix}"
        shutil.copy2(source_path, dest)
        logger.debug("Saved upload: {} → {}", source_path, dest)
        return dest

    def _save_bytes(self, data: bytes, suffix: str) -> Path:
        """Write raw *data* bytes into the uploads directory."""
        dest = self.uploads_dir / f"{uuid.uuid4()}{suffix}"
        dest.write_bytes(data)
        logger.debug("Saved {} bytes to {}", len(data), dest)
        return dest
