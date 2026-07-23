"""Maps each skill's own ``output_schema`` (documented in its SKILL.md) onto the
generic fields the orchestrator's pipeline needs (title/summary/category/tags).

Each skill defines its own JSON output shape in SKILL.md — deliberately, since a
meeting's ``attendees``/``decisions`` and a document's ``chunk_summaries`` don't
fit a one-size-fits-all schema. This module is the single place that knows how
to translate each shape into the columns the DB/embedding/tagging pipeline uses,
so the LLM prompt never has to be told a schema that conflicts with the one its
own SKILL.md already documents.
"""
from __future__ import annotations

from typing import Any

# For each output_schema name: which of its own keys map onto the generic
# title / summary / category / tags fields. ``None`` means that schema has no
# equivalent field, so it stays null (falls back to source_type-level info).
_SCHEMA_FIELD_MAP: dict[str, dict[str, str | None]] = {
    "document_output": {
        "title": "title",
        "summary": "overall_summary",
        "category": "document_type",
        "tags": "keyword_suggestions",
    },
    "note_output": {
        "title": None,
        "summary": "original_text",
        "category": "note_type",
        "tags": "keyword_suggestions",
    },
    "dev_output": {
        "title": None,
        "summary": "summary",
        "category": "content_type",
        "tags": "keyword_suggestions",
    },
    "meeting_output": {
        "title": "meeting_title",
        "summary": "summary",
        "category": None,
        "tags": "keyword_suggestions",
    },
    "screenshot_output": {
        "title": None,
        "summary": "summary",
        "category": "category",
        "tags": "keyword_suggestions",
    },
    "webclip_output": {
        "title": "page_title",
        "summary": "summary",
        "category": "content_type",
        "tags": "keyword_suggestions",
    },
}

# Fallback used for an unrecognised output_schema — assume the raw dict already
# uses generic key names.
_GENERIC_FIELD_MAP: dict[str, str | None] = {
    "title": "title",
    "summary": "summary",
    "category": "category",
    "tags": "suggested_tags",
}


def normalize_agent_output(output_schema: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Translate a skill's raw JSON output into the orchestrator's generic shape.

    Returns a dict with keys: title, summary, category, suggested_tags,
    suggested_project, project_confidence, type_specific_data (the full raw
    output, preserved for anything the generic columns don't capture).
    """
    field_map = _SCHEMA_FIELD_MAP.get(output_schema, _GENERIC_FIELD_MAP)

    def _get(field: str) -> Any:
        key = field_map.get(field)
        return raw.get(key) if key else None

    tags = _get("tags")
    if not isinstance(tags, list):
        tags = []

    return {
        "title": _get("title"),
        "summary": _get("summary"),
        "category": _get("category"),
        "suggested_tags": tags,
        # No skill schema currently defines these; project classification is
        # handled independently by Orchestrator._classify_project().
        "suggested_project": raw.get("suggested_project"),
        "project_confidence": raw.get("project_confidence") or 0.0,
        "type_specific_data": raw,
    }
