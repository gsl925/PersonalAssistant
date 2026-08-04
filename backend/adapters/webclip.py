from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript

from backend.adapters.base import BaseAdapter, ProcessedContent
from backend.adapters.transcript_correction import correct_transcript
from backend.adapters.whisper_utils import _S2TWP, transcribe_audio

_FETCH_TIMEOUT = 30.0
_INVESTMENT_PATTERNS = re.compile(
    r"\b(stock|etf|crypto|bitcoin|投資|股票|基金|期貨|選擇權|指數|ipo|dividend|portfolio)\b",
    re.IGNORECASE,
)
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_TRANSCRIPT_LANGUAGE_PREFERENCE = ["zh-Hant", "zh-Hans", "zh-TW", "zh-CN", "zh", "en"]


class WebclipAdapter(BaseAdapter):
    """Adapter for web URLs — fetches page content and detects content type."""

    source_type = "webclip"

    async def process(self, url: str) -> ProcessedContent:
        url = url.strip()
        video_id = self._extract_youtube_id(url)

        if video_id:
            transcript = await self._fetch_youtube_transcript(video_id)
            used_whisper = False
            if not transcript:
                logger.info(
                    "No captions for YouTube video {} — falling back to whisper transcription.",
                    video_id,
                )
                transcript = await self._transcribe_youtube_audio(video_id)
                used_whisper = True
                if not transcript:
                    logger.warning(
                        "Whisper transcription also failed for {} — falling back to page scrape.",
                        video_id,
                    )

            if transcript:
                _, title = await self._fetch_page(url)
                content_type = self._detect_content_type(url, transcript)
                # Official captions are text, not ASR output — nothing to
                # correct. Only whisper's fallback transcription goes
                # through the correction pass (see transcript_correction.py).
                corrected = await correct_transcript(self.model_router, transcript) if used_whisper else None
                return ProcessedContent(
                    source_type=self.source_type,
                    title=title or urlparse(url).netloc,
                    original_content=transcript,
                    corrected_content=corrected,
                    source_url=url,
                    metadata={
                        "content_type": content_type,
                        "page_title": title,
                        "is_video": True,
                    },
                )

        html, title = await self._fetch_page(url)
        main_text = self._extract_main_content(html)
        content_type = self._detect_content_type(url, main_text)

        return ProcessedContent(
            source_type=self.source_type,
            title=title or urlparse(url).netloc,
            original_content=main_text,
            source_url=url,
            metadata={"content_type": content_type, "page_title": title, "is_video": bool(video_id)},
        )

    def _extract_youtube_id(self, url: str) -> str | None:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host not in _YOUTUBE_HOSTS:
            return None

        if host == "youtu.be":
            return parsed.path.lstrip("/") or None

        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            return video_id

        for prefix in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix):].split("/")[0] or None

        return None

    async def _fetch_youtube_transcript(self, video_id: str) -> str | None:
        try:
            api = YouTubeTranscriptApi()
            fetched = await asyncio.to_thread(
                api.fetch, video_id, languages=_TRANSCRIPT_LANGUAGE_PREFERENCE
            )
        except CouldNotRetrieveTranscript as exc:
            logger.warning("Transcript fetch failed for {}: {}", video_id, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unexpected error fetching transcript for {}: {}", video_id, exc)
            return None

        text = " ".join(snippet.text for snippet in fetched).strip()
        # YouTube's own (auto-generated or uploaded) caption tracks skew
        # Simplified for Chinese the same way whisper does — see
        # whisper_utils._S2TWP. Applying it here too so this path isn't
        # silently exempt from the same conversion.
        return _S2TWP.convert(text) if text else None

    async def _transcribe_youtube_audio(self, video_id: str) -> str | None:
        """Fallback for videos with no captions: download the audio via
        yt-dlp and transcribe it locally with faster-whisper."""
        downloaded = await asyncio.to_thread(self._download_youtube_audio, video_id)
        if downloaded is None:
            return None
        audio_path, tmp_dir = downloaded
        try:
            transcript = await transcribe_audio(audio_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        if transcript.startswith("[Transcription failed"):
            return None
        return transcript.strip() or None

    def _download_youtube_audio(self, video_id: str) -> tuple[Path, Path] | None:
        """Blocking helper (run via asyncio.to_thread): downloads the best
        available audio-only stream, no ffmpeg post-processing required."""
        import yt_dlp

        tmp_dir = Path(tempfile.mkdtemp(prefix="ytaudio_"))
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(tmp_dir / f"{video_id}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "noprogress": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}", download=True
                )
                filepath = Path(ydl.prepare_filename(info))
            if filepath.exists():
                return filepath, tmp_dir
        except Exception as exc:
            logger.warning("yt-dlp audio download failed for {}: {}", video_id, exc)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    async def _fetch_page(self, url: str) -> tuple[str, str | None]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP {} fetching {}: {}", exc.response.status_code, url, exc)
            return f"[Failed to fetch: HTTP {exc.response.status_code}]", None
        except Exception as exc:
            logger.warning("Error fetching {}: {}", url, exc)
            return f"[Failed to fetch: {exc}]", None

        soup = BeautifulSoup(resp.text, "lxml")
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None
        return resp.text, title

    def _extract_main_content(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")

        # Remove boilerplate elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        # Prefer semantic content containers
        for selector in ("article", "main", '[role="main"]', ".content", "#content"):
            container = soup.select_one(selector)
            if container:
                return container.get_text(separator="\n", strip=True)

        body = soup.find("body")
        if body:
            return body.get_text(separator="\n", strip=True)
        return soup.get_text(separator="\n", strip=True)

    def _detect_content_type(self, url: str, text: str) -> str:
        combined = (url + " " + text[:500]).lower()
        if _INVESTMENT_PATTERNS.search(combined):
            return "investment"
        return "knowledge"
