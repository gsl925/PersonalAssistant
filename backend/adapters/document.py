from __future__ import annotations

from pathlib import Path

from loguru import logger

from backend.adapters.base import BaseAdapter, ProcessedContent

_CHUNK_SIZE = 3000
_CHUNK_OVERLAP = 200


class DocumentAdapter(BaseAdapter):
    """Adapter for PDF and Word document files."""

    source_type = "doc"

    async def process(self, file_path: Path) -> ProcessedContent:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            text = self._extract_pdf(file_path)
        elif suffix in (".docx", ".doc"):
            text = self._extract_docx(file_path)
        else:
            raise ValueError(f"Unsupported document type: {suffix}")

        saved = self._save_file(file_path)
        title = file_path.stem

        return ProcessedContent(
            source_type=self.source_type,
            title=title,
            original_content=text,
            file_path=str(saved),
            metadata={"original_filename": file_path.name, "extension": suffix},
        )

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    def _extract_pdf(self, path: Path) -> str:
        try:
            import pypdf

            reader = pypdf.PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages).strip()
        except ImportError:
            logger.warning("pypdf not installed; trying pypdf2")
            import PyPDF2  # type: ignore[import]

            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages).strip()

    def _extract_docx(self, path: Path) -> str:
        import docx

        doc = docx.Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    @staticmethod
    def chunk_text(text: str) -> list[str]:
        """Split long text into overlapping chunks suitable for LLM processing."""
        if len(text) <= _CHUNK_SIZE:
            return [text]
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + _CHUNK_SIZE
            chunks.append(text[start:end])
            start += _CHUNK_SIZE - _CHUNK_OVERLAP
        return chunks
