from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.knowledge.db import Base

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # doc / screenshot / note / webclip / meeting
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LLM pass over a whisper transcript that fixes likely ASR homophone
    # errors — kept separate from original_content (never overwritten) so
    # the unmodified transcript stays available to check the correction
    # against. NULL for anything that wasn't whisper-transcribed.
    corrected_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Fields specific to the agent's own output_schema (e.g. document chunk
    # summaries, meeting attendees/decisions) that don't map onto the generic
    # summary/category columns above.
    type_specific_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # LLM-extracted "what is the author actually arguing" — distinct from
    # `summary` (which is content-restatement-oriented, from webclip-agent's
    # own prompt). Populated by backend/insight.py::extract_insight(), only
    # for documents saved through the insight-preview flow.
    ai_insight: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The user's own personal annotation/reaction to this document — never
    # written by an LLM, only ever set directly via the "add my insight" UI.
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending / processing / completed / failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )

    # Relationships
    tags: Mapped[list[DocumentTag]] = relationship(
        "DocumentTag", back_populates="document", cascade="all, delete-orphan"
    )
    project_links: Mapped[list[DocumentProject]] = relationship(
        "DocumentProject", back_populates="document", cascade="all, delete-orphan"
    )
    relations_as_a: Mapped[list[DocumentRelation]] = relationship(
        "DocumentRelation",
        foreign_keys="DocumentRelation.doc_id_a",
        back_populates="document_a",
        cascade="all, delete-orphan",
    )
    relations_as_b: Mapped[list[DocumentRelation]] = relationship(
        "DocumentRelation",
        foreign_keys="DocumentRelation.doc_id_b",
        back_populates="document_b",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_documents_created_at", "created_at"),
        Index("ix_documents_source_type_status", "source_type", "processing_status"),
    )


# ---------------------------------------------------------------------------
# DocumentTag  (many-to-many through table: document ↔ keyword)
# ---------------------------------------------------------------------------


class DocumentTag(Base):
    __tablename__ = "document_tags"

    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    keyword: Mapped[str] = mapped_column(String(100), primary_key=True)

    document: Mapped[Document] = relationship("Document", back_populates="tags")

    __table_args__ = (Index("ix_document_tags_keyword", "keyword"),)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # Relationships
    document_links: Mapped[list[DocumentProject]] = relationship(
        "DocumentProject", back_populates="project", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# DocumentProject  (association: document ↔ project)
# ---------------------------------------------------------------------------


class DocumentProject(Base):
    __tablename__ = "document_projects"

    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    document: Mapped[Document] = relationship(
        "Document", back_populates="project_links"
    )
    project: Mapped[Project] = relationship(
        "Project", back_populates="document_links"
    )

    __table_args__ = (
        Index("ix_document_projects_project_id", "project_id"),
    )


# ---------------------------------------------------------------------------
# DocumentRelation
# ---------------------------------------------------------------------------


class DocumentRelation(Base):
    __tablename__ = "document_relations"

    doc_id_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    doc_id_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relation_type: Mapped[str] = mapped_column(
        String(20), nullable=False, primary_key=True
    )  # semantic / shared_tag
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    document_a: Mapped[Document] = relationship(
        "Document",
        foreign_keys=[doc_id_a],
        back_populates="relations_as_a",
    )
    document_b: Mapped[Document] = relationship(
        "Document",
        foreign_keys=[doc_id_b],
        back_populates="relations_as_b",
    )

    __table_args__ = (
        Index("ix_document_relations_doc_id_b", "doc_id_b"),
        Index("ix_document_relations_relation_type", "relation_type"),
    )


# ---------------------------------------------------------------------------
# Todo  (quick-capture todo/reminder — separate from meeting action_items,
# which have no "done" flag and come from a different source)
# ---------------------------------------------------------------------------


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # telegram / desktop / dashboard / claude:{project_name}
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cheap regex-extracted URL from raw_input, if any — just a reference
    # link, not fetched/summarized (that's webclip's job, not this table's).
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending / done / cancelled
    # Periodic reminder rule — independent of start_date/due_date, which stay
    # None for a recurring todo. NULL frequency means "not recurring" (the
    # existing one-off TodoReminder-based behavior, untouched). "done" does
    # NOT stop future recurring reminders (by design); only "cancelled" does
    # — see send_recurring_todo_reminder's status guard.
    recurrence_frequency: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # daily / weekly / monthly / NULL
    recurrence_weekday: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 0=Mon..6=Sun, only for weekly
    recurrence_day_of_month: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 1-31, only for monthly
    recurrence_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )

    reminders: Mapped[list[TodoReminder]] = relationship(
        "TodoReminder", back_populates="todo", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# TodoReminder  (one-to-many: a Todo can have a start/midpoint/due reminder)
# ---------------------------------------------------------------------------


class TodoReminder(Base):
    __tablename__ = "todo_reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    todo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("todos.id", ondelete="CASCADE"), nullable=False
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)  # start / midpoint / due
    sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    todo: Mapped[Todo] = relationship("Todo", back_populates="reminders")

    __table_args__ = (
        Index("ix_todo_reminders_remind_at", "remind_at"),
        Index("ix_todo_reminders_todo_id", "todo_id"),
    )


# ---------------------------------------------------------------------------
# Tool  (a factory tool tracked in the separate `factory-tools` project —
# dev-agent drafts/writes/tests code for these; this row persists across the
# tool's lifetime, since it gets revisited repeatedly, not a one-shot record)
# ---------------------------------------------------------------------------


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Path relative to the factory-tools repo root, e.g. "tools/log_checker_a"
    repo_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Path to reference code the user pointed dev-agent at when first
    # building this tool, if any — NULL means it was built from scratch.
    reference_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )  # active / deprecated
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )

    change_logs: Mapped[list[ToolChangeLog]] = relationship(
        "ToolChangeLog", back_populates="tool", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# ToolChangeLog  (one row per dev-agent change to a Tool. No git involved by
# design — factory-tools is a plain local folder, never git-initialized;
# diff_text is the entire change record, not a pointer to a commit)
# ---------------------------------------------------------------------------


class ToolChangeLog(Base):
    __tablename__ = "tool_change_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False
    )
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    diff_text: Mapped[str] = mapped_column(Text, nullable=False)
    drafted_by: Mapped[str] = mapped_column(String(100), nullable=False)
    # Reference code path used for THIS specific change, if any — distinct
    # from Tool.reference_path (which only captures the tool's original
    # build), since a later change can point at a different reference.
    reference_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Links back to the Document (screenshot/meeting/note) whose content
    # this change request actually came from, if it arrived that way rather
    # than as a plain-text request — lets the change be traced back to the
    # real discussion/evidence, not just a written summary of it.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    self_test_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which model reviewed this change after dev-agent's self-test: the
    # normal path is "claude-code"; "cloud-fallback:{model}" records that
    # Claude Code's own quota was exhausted and review fell back to an
    # existing free cloud tier instead.
    review_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="drafted", index=True
    )  # drafted / self_tested / blocked / landed
    # Set when status="blocked" — why the review gate rejected this change.
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    tool: Mapped[Tool] = relationship("Tool", back_populates="change_logs")

    __table_args__ = (
        Index("ix_tool_change_logs_tool_id", "tool_id"),
        Index("ix_tool_change_logs_source_document_id", "source_document_id"),
    )


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
