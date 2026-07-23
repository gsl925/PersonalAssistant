from __future__ import annotations

import base64
from pathlib import Path

from loguru import logger

from backend.adapters.base import BaseAdapter, ProcessedContent


class ScreenshotAdapter(BaseAdapter):
    """Adapter for image files / screenshots using a vision-capable LLM."""

    source_type = "screenshot"

    _SYSTEM_PROMPT = (
        "You are an expert at reading images and screenshots. "
        "Extract ALL text visible in the image verbatim. "
        "Then provide a brief description of what the image shows. "
        "Format: first the extracted text, then a separator '---', then the description."
    )

    async def process(self, image_path: Path) -> ProcessedContent:
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        image_b64 = self._encode_image(image_path)
        saved = self._save_file(image_path)

        try:
            response = await self.model_router.chat_with_image(
                tier="vision",
                messages=[
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": "Please analyse this screenshot/image.",
                    },
                ],
                image_base64=image_b64,
            )
        except Exception as exc:
            logger.warning("VLM analysis failed, using fallback description: {}", exc)
            response = f"[Image file: {image_path.name}]"

        return ProcessedContent(
            source_type=self.source_type,
            title=f"Screenshot: {image_path.stem}",
            original_content=response,
            file_path=str(saved),
            metadata={"original_filename": image_path.name},
        )

    def _encode_image(self, path: Path) -> str:
        """Return the image as a base64-encoded string (JPEG or PNG)."""
        from PIL import Image
        import io

        with Image.open(path) as img:
            # Convert palette/RGBA images to RGB for JPEG encoding
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode()
