"""Shared faster-whisper transcription helper.

Used by both :class:`~backend.adapters.meeting.MeetingAdapter` (audio/voice
uploads) and :class:`~backend.adapters.webclip.WebclipAdapter` (caption-less
YouTube videos) so the model-loading/transcription logic lives in one place.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

WHISPER_MODEL_SIZE = "base"  # use "small" or "medium" for better accuracy


async def transcribe_audio(media_path: Path) -> str:
    """Transcribe the audio track of *media_path* (audio or video container).

    faster-whisper decodes via PyAV, which reads the audio stream directly out
    of common video containers (e.g. mp4) — no separate ffmpeg extraction step
    is needed.
    """
    loop = asyncio.get_running_loop()

    def _run() -> str:
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
            segments, info = model.transcribe(str(media_path), beam_size=5)
            logger.info(
                "Transcribing {} — detected language '{}' (prob {:.2f})",
                media_path.name,
                info.language,
                info.language_probability,
            )
            return " ".join(seg.text.strip() for seg in segments)
        except Exception as exc:
            logger.error("Whisper transcription failed: {}", exc)
            return f"[Transcription failed: {exc}]"

    return await loop.run_in_executor(None, _run)
