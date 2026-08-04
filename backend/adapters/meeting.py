from __future__ import annotations

from pathlib import Path

from backend.adapters.base import BaseAdapter, ProcessedContent
from backend.adapters.transcript_correction import correct_transcript
from backend.adapters.whisper_utils import transcribe_audio


class MeetingAdapter(BaseAdapter):
    """Adapter for meeting recordings and video files — transcribes the audio
    track via faster-whisper (works on video containers too, e.g. mp4)."""

    source_type = "meeting"

    async def process(self, audio_path: Path) -> ProcessedContent:
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        saved = self._save_file(audio_path)
        transcript = await transcribe_audio(audio_path)
        corrected = await correct_transcript(self.model_router, transcript)

        return ProcessedContent(
            source_type=self.source_type,
            title=f"Meeting: {audio_path.stem}",
            original_content=transcript,
            corrected_content=corrected,
            file_path=str(saved),
            metadata={"original_filename": audio_path.name},
        )
