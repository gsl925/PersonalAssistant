from __future__ import annotations

from backend.adapters.base import BaseAdapter, ProcessedContent

_TITLE_MAX_LEN = 60


class NoteAdapter(BaseAdapter):
    """Adapter for quick text notes — minimal processing, direct archive."""

    source_type = "note"

    async def process(self, text: str) -> ProcessedContent:
        text = text.strip()
        title = text[:_TITLE_MAX_LEN].rstrip() + ("…" if len(text) > _TITLE_MAX_LEN else "")
        return ProcessedContent(
            source_type=self.source_type,
            title=title,
            original_content=text,
        )
