from __future__ import annotations

from pathlib import Path

from backend.adapters.base import BaseAdapter
from backend.adapters.document import DocumentAdapter
from backend.adapters.meeting import MeetingAdapter
from backend.adapters.note import NoteAdapter
from backend.adapters.screenshot import ScreenshotAdapter
from backend.adapters.webclip import WebclipAdapter

# ---------------------------------------------------------------------------
# Primary registry: canonical source_type → adapter class
# ---------------------------------------------------------------------------

_ADAPTER_MAP: dict[str, type[BaseAdapter]] = {
    "screenshot": ScreenshotAdapter,
    "doc":        DocumentAdapter,
    "note":       NoteAdapter,
    "webclip":    WebclipAdapter,
    "meeting":    MeetingAdapter,
}

# ---------------------------------------------------------------------------
# Alias map: user-facing input_type strings → canonical source_type key
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {
    "image":    "screenshot",
    "photo":    "screenshot",
    "file":     "doc",
    "document": "doc",
    "text":     "note",
    "url":      "webclip",
    "audio":    "meeting",
    "voice":    "meeting",
    # MeetingAdapter transcribes via faster-whisper/PyAV, which decodes the
    # audio track directly out of video containers — no separate video
    # adapter needed.
    "video":    "meeting",
}


class AdapterFactory:
    """Instantiates the correct :class:`~backend.adapters.base.BaseAdapter` subclass
    for a given source-type or input-type string.

    Usage
    -----
    ::

        adapter = AdapterFactory.get_adapter("image", model_router, uploads_dir)
        processed = await adapter.process(image_path)

    Supported canonical types (also accepts all aliases):
        screenshot, doc, note, webclip, meeting
    """

    @staticmethod
    def get_adapter(
        source_type: str,
        model_router,
        uploads_dir: Path | None = None,
    ) -> BaseAdapter:
        """Return an initialised adapter for *source_type*.

        Parameters
        ----------
        source_type:
            Canonical source type (e.g. ``"screenshot"``) **or** any alias
            (e.g. ``"image"``, ``"photo"``).  Case-insensitive.
        model_router:
            A :class:`~backend.model_router.ModelRouter` instance passed
            through to adapters that need LLM calls (e.g. ScreenshotAdapter).
        uploads_dir:
            Directory where adapters should persist copies of uploaded files.
            Defaults to :attr:`~backend.config.Settings.UPLOADS_DIR` when
            omitted.

        Raises
        ------
        ValueError
            When *source_type* is not in either the canonical registry or the
            alias map.
        """
        normalized = _ALIAS_MAP.get(source_type.lower(), source_type.lower())
        cls = _ADAPTER_MAP.get(normalized)
        if cls is None:
            raise ValueError(
                f"No adapter registered for source_type={source_type!r}. "
                f"Known types: {sorted(_ADAPTER_MAP)} | "
                f"Aliases: {sorted(_ALIAS_MAP)}"
            )
        return cls(model_router=model_router, uploads_dir=uploads_dir)

    @staticmethod
    def supported_types() -> list[str]:
        """Return the list of canonical source type keys (sorted)."""
        return sorted(_ADAPTER_MAP.keys())

    @staticmethod
    def supported_aliases() -> list[str]:
        """Return all accepted alias strings (sorted)."""
        return sorted(_ALIAS_MAP.keys())

    @staticmethod
    def registered_types() -> dict[str, str]:
        """Return a combined map of all accepted strings → canonical type.

        Useful for input validation in API endpoints.
        """
        combined: dict[str, str] = {k: k for k in _ADAPTER_MAP}
        combined.update(_ALIAS_MAP)
        return combined
