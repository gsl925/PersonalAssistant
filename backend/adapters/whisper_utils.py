"""Shared faster-whisper transcription helper.

Used by both :class:`~backend.adapters.meeting.MeetingAdapter` (audio/voice
uploads) and :class:`~backend.adapters.webclip.WebclipAdapter` (caption-less
YouTube videos) so the model-loading/transcription logic lives in one place.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger
from opencc import OpenCC

WHISPER_MODEL_SIZE = "medium"  # was "base" — trading CPU inference time for accuracy

# Whisper's Chinese training data skews Simplified, so it transcribes
# Mandarin speech into Simplified characters regardless of accent/region —
# s2twp additionally swaps Mainland/Taiwan terminology (軟件→軟體, 程序→程式),
# not just character shapes. Built once and reused; running it on non-Chinese
# text is a harmless no-op.
_S2TWP = OpenCC("s2twp")


_TIMESTAMP_BUCKET_SECONDS = 30.0


def format_timestamp(seconds: float) -> str:
    """Render a seconds offset as ``MM:SS`` (hours folded into the minutes
    field — fine for the single-video durations this is used for)."""
    total_seconds = max(0, int(seconds))
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


async def transcribe_audio(media_path: Path, with_timestamps: bool = False) -> str:
    """Transcribe the audio track of *media_path* (audio or video container).

    faster-whisper decodes via PyAV, which reads the audio stream directly out
    of common video containers (e.g. mp4) — no separate ffmpeg extraction step
    is needed.

    ``with_timestamps=False`` (default, used by the meeting adapter) keeps the
    original plain-paragraph output unchanged. ``with_timestamps=True`` (used
    by the webclip adapter's YouTube path) instead groups consecutive segments
    into ~30s buckets and prefixes each with a ``[MM:SS]`` marker, so a later
    summarization step can cite *real* points in the video rather than
    inventing times.
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
            if not with_timestamps:
                text = " ".join(seg.text.strip() for seg in segments)
                return _S2TWP.convert(text)

            lines: list[str] = []
            bucket_start: float | None = None
            bucket_parts: list[str] = []
            for seg in segments:
                if bucket_start is None:
                    bucket_start = seg.start
                bucket_parts.append(seg.text.strip())
                if seg.end - bucket_start >= _TIMESTAMP_BUCKET_SECONDS:
                    lines.append(f"[{format_timestamp(bucket_start)}] {' '.join(bucket_parts)}")
                    bucket_start, bucket_parts = None, []
            if bucket_parts and bucket_start is not None:
                lines.append(f"[{format_timestamp(bucket_start)}] {' '.join(bucket_parts)}")
            return _S2TWP.convert("\n".join(lines))
        except Exception as exc:
            logger.error("Whisper transcription failed: {}", exc)
            return f"[Transcription failed: {exc}]"

    return await loop.run_in_executor(None, _run)
