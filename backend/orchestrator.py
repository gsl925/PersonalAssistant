from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.factory import AdapterFactory
from backend.config import settings
from backend.knowledge import crud
from backend.model_router import AllProvidersFailedError, ModelRouter
from backend.skill_schemas import normalize_agent_output
from backend.skills_loader import SkillDefinition, SkillsLoader

# ---------------------------------------------------------------------------
# Confidence thresholds (SDD §4.1)
# ---------------------------------------------------------------------------

_AUTO_THRESHOLD = 0.8
_CONFIRM_THRESHOLD = 0.4

# Minimum semantic similarity to create a relation link
_RELATION_THRESHOLD = 0.7

# Minimum number of shared keyword tags to create a "shared_tag" relation link
_SHARED_TAG_MIN_COUNT = 2

# Max retries for transient LLM / DB failures
_MAX_RETRIES = 2
_RETRY_DELAY = 1.5  # seconds between retries

# ---------------------------------------------------------------------------
# Todo reminder defaults
# ---------------------------------------------------------------------------

_TAIPEI = ZoneInfo("Asia/Taipei")
_TODO_REMINDER_HOUR = 9  # 09:00 Asia/Taipei, matching the daily-digest morning cadence
# If a todo's start→due span exceeds this many days, add one extra reminder
# at the midpoint so a long-running task doesn't go completely unmentioned
# between the start and the day-before-deadline reminders.
_TODO_MIDPOINT_GAP_DAYS = 7

# ---------------------------------------------------------------------------
# Fast-lane: input types that bypass LLM routing entirely
# ---------------------------------------------------------------------------

_FAST_LANE: dict[str, tuple[str, float]] = {
    "image":      ("screenshot-agent", 1.0),
    "photo":      ("screenshot-agent", 1.0),
    "screenshot": ("screenshot-agent", 1.0),
    "audio":      ("meeting-agent",    1.0),
    "voice":      ("meeting-agent",    1.0),
    "video":      ("meeting-agent",    1.0),
    "url":        ("webclip-agent",    0.95),
    "file":       ("document-agent",   0.90),
    "doc":        ("document-agent",   0.90),
    "document":   ("document-agent",   0.90),
}

# ---------------------------------------------------------------------------
# Reverse mapping: canonical DB source_type → a representative _route()/
# AdapterFactory input_type, used by retry_document() to reconstruct the
# original input_type from a persisted (failed) Document row.
# ---------------------------------------------------------------------------

_SOURCE_TYPE_TO_INPUT_TYPE: dict[str, str] = {
    "screenshot": "screenshot",
    "doc": "doc",
    "note": "text",
    "webclip": "url",
    # audio/voice/video all route to meeting-agent at the same confidence, so
    # any one of them is a faithful stand-in for re-routing a "meeting" doc.
    "meeting": "audio",
}


# ---------------------------------------------------------------------------
# Internal state holder for pending confirmations
# ---------------------------------------------------------------------------

class _PendingConfirmation:
    """Holds routing info for a document awaiting user confirmation via Telegram."""

    __slots__ = ("doc_id", "skill_name", "processed")

    def __init__(self, doc_id: uuid.UUID, skill_name: str | None, processed: Any) -> None:
        self.doc_id = doc_id
        self.skill_name = skill_name
        self.processed = processed


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """Central routing and execution brain for the Personal AI Assistant.

    Responsibilities
    ----------------
    1. Save raw input to PostgreSQL immediately (fail-safe).
    2. Route to the correct agent via fast-lane heuristics or LLM classification.
    3. Execute the agent (with retry logic).
    4. Post-process: auto-tagging, LLM project classification, embedding, relations.
    5. Return a status dict suitable for Telegram / REST callers.
    """

    def __init__(
        self,
        model_router: ModelRouter,
        skills_loader: SkillsLoader,
        qdrant_client: Any,
        session_maker: Any,
    ) -> None:
        self.model_router = model_router
        self.skills_loader = skills_loader
        self.qdrant = qdrant_client
        self._session_maker = session_maker
        # doc_id (str) → _PendingConfirmation awaiting user confirmation
        self.pending_confirmations: dict[str, _PendingConfirmation] = {}
        # doc_id (str) → suggested project name awaiting user confirmation
        self.pending_project_confirmations: dict[str, str] = {}
        # confirmation_id (str) → extracted todo fields awaiting user confirmation
        self.pending_todo_confirmations: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def process_input(
        self,
        input_type: str,
        input_data: Any,
        user_context: dict | None = None,
    ) -> dict:
        """Main entry point.

        Parameters
        ----------
        input_type:
            One of: image, photo, screenshot, audio, voice, url, file, doc,
            document, text, note.
        input_data:
            The raw payload — a file Path, a URL string, or plain text.
        user_context:
            Optional caller metadata (telegram user_id, chat_id, etc.).

        Returns
        -------
        dict with keys:
            status          "completed" | "pending_confirmation" | "failed"
            doc_id          str (UUID)
            message         Human-readable summary (may be Traditional Chinese)
            agent_name      present when status is "pending_confirmation"
            confidence      present when status is "pending_confirmation"
            available_agents  present when no confident match was found
        """
        # 1. Persist a stub record immediately so every input is traceable.
        source_type = self._normalize_source_type(input_type)
        doc_id: uuid.UUID | None = None

        try:
            async with self._session_maker() as db:
                doc = await crud.create_document(
                    db,
                    source_type=source_type,
                    processing_status="pending",
                )
                await db.commit()
                doc_id = doc.id
            logger.info("Saved raw input stub — doc_id={} source_type={}", doc_id, source_type)
        except Exception as exc:
            logger.error("Failed to create document stub: {}", exc)
            return {"status": "failed", "doc_id": None, "message": f"Database error: {exc}"}

        # 2. Run the adapter to normalise the raw input. Flip to "processing"
        # first so a poller can tell "actively transcribing/extracting" apart
        # from "still queued" — adapter.process() can take minutes for audio
        #/video (whisper transcription), during which nothing else updates.
        try:
            async with self._session_maker() as db:
                await crud.update_document_status(db, doc_id, "processing")
                await db.commit()

            adapter = AdapterFactory.get_adapter(
                input_type, self.model_router, settings.UPLOADS_DIR
            )
            processed = await adapter.process(input_data)
        except Exception as exc:
            logger.exception("Adapter failed for doc {}: {}", doc_id, exc)
            # Persist the raw input reference even on failure — otherwise
            # retry_document() has nothing to reconstruct from later.
            await self._mark_failed(doc_id, str(exc), **self._raw_input_fields(input_type, input_data))
            return {"status": "failed", "doc_id": str(doc_id), "message": str(exc)}

        # File uploads are saved to disk under a collision-free UUID filename
        # before reaching the adapter, so the adapter can only derive a title
        # from that UUID stem. Recover the human-readable original filename
        # here as a fallback title (the agent's own inferred title, once
        # available, takes priority — see _execute_and_save).
        original_filename = (user_context or {}).get("original_filename")
        if original_filename:
            processed.title = Path(original_filename).stem

        return await self._route_and_finalize(doc_id, input_type, processed)

    async def retry_document(self, doc_id: str) -> dict:
        """Manually re-run processing for a document stuck in ``"failed"`` status.

        Reconstructs the adapter input from whatever was persisted on the
        Document row (``file_path``, ``source_url``, or ``original_content``)
        and re-runs routing + execution against the *same* doc_id — no new
        document row is created, so history/relations aren't duplicated.
        """
        try:
            doc_uuid = uuid.UUID(doc_id)
        except ValueError:
            return {"status": "failed", "doc_id": doc_id, "message": "Invalid doc_id"}

        async with self._session_maker() as db:
            doc = await crud.get_document(db, doc_uuid)

        if doc is None:
            return {"status": "failed", "doc_id": doc_id, "message": "Document not found"}
        if doc.processing_status != "failed":
            return {
                "status": "failed",
                "doc_id": doc_id,
                "message": f"Document is not in 'failed' state (current: {doc.processing_status})",
            }

        if doc.file_path:
            input_data: Any = doc.file_path
        elif doc.source_url:
            input_data = doc.source_url
        else:
            input_data = doc.original_content or ""

        input_type = _SOURCE_TYPE_TO_INPUT_TYPE.get(doc.source_type, doc.source_type)

        try:
            async with self._session_maker() as db:
                await crud.update_document_status(db, doc_uuid, "processing")
                await db.commit()

            adapter = AdapterFactory.get_adapter(
                doc.source_type, self.model_router, settings.UPLOADS_DIR
            )
            processed = await adapter.process(input_data)
        except Exception as exc:
            logger.exception("Retry: adapter failed for doc {}: {}", doc_uuid, exc)
            await self._mark_failed(doc_uuid, str(exc))
            return {"status": "failed", "doc_id": doc_id, "message": str(exc)}

        if doc.title:
            processed.title = doc.title

        return await self._route_and_finalize(doc_uuid, input_type, processed)

    async def _route_and_finalize(
        self,
        doc_id: uuid.UUID,
        input_type: str,
        processed: Any,
    ) -> dict:
        """Route *processed* content to an agent and act on the resulting confidence.

        Shared by :meth:`process_input` (fresh input) and :meth:`retry_document`
        (re-running a previously failed document) so the confidence-tiering
        logic lives in exactly one place.
        """
        try:
            agent_name, confidence = await self._route(input_type, processed.original_content)
            logger.info(
                "Routing decision — doc={} agent='{}' confidence={:.2f}",
                doc_id, agent_name, confidence,
            )
        except Exception as exc:
            logger.warning("Routing failed for doc {}, falling back to note-agent: {}", doc_id, exc)
            agent_name, confidence = "note-agent", 0.3

        if confidence >= _AUTO_THRESHOLD:
            # High confidence → execute immediately.
            try:
                agent_result = await self._execute_and_save(doc_id, agent_name, processed)
                result = {
                    "status": "completed",
                    "doc_id": str(doc_id),
                    "message": f"已儲存至知識庫 (agent: {agent_name})",
                    "agent_name": agent_name,
                    "title": agent_result.get("title") or processed.title,
                    "summary": agent_result.get("summary"),
                    "category": agent_result.get("category"),
                    "tags": agent_result.get("suggested_tags"),
                }
                pending_project = agent_result.get("_pending_project")
                if pending_project:
                    result["pending_project"] = pending_project
                return result
            except Exception as exc:
                logger.exception("Auto-execution failed for doc {}: {}", doc_id, exc)
                await self._mark_failed(doc_id, str(exc))
                return {"status": "failed", "doc_id": str(doc_id), "message": str(exc)}

        elif confidence >= _CONFIRM_THRESHOLD:
            # Medium confidence → ask user to confirm via Telegram inline buttons.
            self.pending_confirmations[str(doc_id)] = _PendingConfirmation(
                doc_id, agent_name, processed
            )
            return {
                "status": "pending_confirmation",
                "doc_id": str(doc_id),
                "agent_name": agent_name,
                "confidence": confidence,
                "message": (
                    f"請確認處理方式 (建議: {agent_name}, "
                    f"信心度: {confidence:.0%})"
                ),
            }

        else:
            # Low / no confidence → list all agents for manual selection.
            enabled_names = [s.name for s in self.skills_loader.get_enabled_skills()]
            self.pending_confirmations[str(doc_id)] = _PendingConfirmation(
                doc_id, None, processed
            )
            return {
                "status": "pending_confirmation",
                "doc_id": str(doc_id),
                "agent_name": None,
                "available_agents": enabled_names,
                "message": "無法自動判斷處理方式，請手動選擇 agent",
            }

    async def confirm_routing(self, doc_id: str, agent_name: str) -> dict:
        """Called when the user confirms an agent selection via Telegram.

        Parameters
        ----------
        doc_id:
            UUID string of the document awaiting confirmation.
        agent_name:
            The agent the user selected (must be an enabled skill).

        Returns
        -------
        Status dict compatible with :meth:`process_input`.
        """
        pending = self.pending_confirmations.pop(doc_id, None)
        if pending is None:
            logger.warning("confirm_routing called for unknown doc_id={}", doc_id)
            return {
                "status": "failed",
                "doc_id": doc_id,
                "message": f"No pending task for doc_id={doc_id}",
            }

        try:
            agent_result = await self._execute_and_save(pending.doc_id, agent_name, pending.processed)
            result = {
                "status": "completed",
                "doc_id": doc_id,
                "message": f"已用 {agent_name} 完成處理",
                "agent_name": agent_name,
                "title": agent_result.get("title") or pending.processed.title,
                "summary": agent_result.get("summary"),
                "category": agent_result.get("category"),
                "tags": agent_result.get("suggested_tags"),
            }
            pending_project = agent_result.get("_pending_project")
            if pending_project:
                result["pending_project"] = pending_project
            return result
        except Exception as exc:
            logger.exception("Confirmed execution failed for doc {}: {}", doc_id, exc)
            await self._mark_failed(pending.doc_id, str(exc))
            return {"status": "failed", "doc_id": doc_id, "message": str(exc)}

    async def confirm_project(self, doc_id: str, project_name: str | None) -> dict:
        """Called when the user responds to a project-confirmation prompt.

        Parameters
        ----------
        doc_id:
            UUID string of the document awaiting project confirmation.
        project_name:
            The project to link the document to (created if it doesn't exist
            yet), or ``None`` if the user declined ("不歸類").
        """
        pending_name = self.pending_project_confirmations.pop(doc_id, None)
        if pending_name is None:
            logger.warning("confirm_project called for unknown doc_id={}", doc_id)
            return {
                "status": "failed",
                "doc_id": doc_id,
                "message": f"No pending project confirmation for doc_id={doc_id}",
            }

        if project_name is None:
            return {"status": "completed", "doc_id": doc_id, "message": "已略過專案歸類"}

        try:
            async with self._session_maker() as db:
                project = await crud.get_or_create_project(db, project_name)
                await crud.link_document_project(db, uuid.UUID(doc_id), project.id)
                await db.commit()
            return {
                "status": "completed",
                "doc_id": doc_id,
                "message": f"已加入專案「{project_name}」",
            }
        except Exception as exc:
            logger.exception("confirm_project failed for doc {}: {}", doc_id, exc)
            return {"status": "failed", "doc_id": doc_id, "message": str(exc)}

    async def get_action_items(self, due_before: str | None = None) -> list[dict]:
        """Aggregate action items across all completed meeting documents.

        Shares its query/flatten logic with ``GET /api/knowledge/action-items``
        (both call ``crud.list_action_items``) so a Telegram todo-intent query
        and the REST endpoint never drift out of sync.
        """
        parsed_due_before = date.fromisoformat(due_before) if due_before else None
        async with self._session_maker() as db:
            return await crud.list_action_items(db, due_before=parsed_due_before)

    # ------------------------------------------------------------------
    # Quick-capture todos
    # ------------------------------------------------------------------

    # Cheap pre-filter for the ambient Telegram path — date-like tokens or
    # todo-ish keywords. Only messages that trip this pay for an LLM call;
    # explicit paths (desktop/dashboard/the /todo command) skip it entirely
    # since intent is already unambiguous there.
    _TODO_CREATE_HINT_PATTERN = re.compile(
        r"提醒我|記得|別忘了|截止|deadline|due|期限|申請|開放|\d{1,2}[/\-]\d{1,2}",
        re.IGNORECASE,
    )

    async def extract_todo_fields(self, text: str) -> dict:
        """Extract todo content + dates from free text via a fast_text LLM call.

        Deliberately does not ask the LLM to compute ``remind_at`` itself —
        date arithmetic is unreliable coming out of a small model, so that's
        derived deterministically in Python (:meth:`_compute_reminders`).
        """
        today = datetime.now(_TAIPEI).date().isoformat()
        prompt = (
            f"Today's date is {today} (Asia/Taipei). Extract the task and any "
            "date range from the following message.\n\n"
            f"Message:\n{text[:1000]}\n\n"
            "Respond with ONLY valid JSON (no markdown fences):\n"
            '{"content": "<short task description>", '
            '"start_date": "<YYYY-MM-DD or null>", '
            '"due_date": "<YYYY-MM-DD or null>"}\n'
            "Resolve relative dates (e.g. \"明天\", \"下週三\") against today's date. "
            "content 請使用繁體中文撰寫，不要使用簡體中文或英文（專有名詞可保留原文）。"
        )
        try:
            raw = await self.model_router.chat(
                "fast_text", [{"role": "user", "content": prompt}], temperature=0,
            )
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return {
                    "content": str(data.get("content") or text[:200]).strip(),
                    "start_date": self._parse_date(data.get("start_date")),
                    "due_date": self._parse_date(data.get("due_date")),
                }
        except (AllProvidersFailedError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Todo extraction failed: {}", exc)
        return {"content": text[:200].strip(), "start_date": None, "due_date": None}

    async def classify_todo_intent(self, text: str) -> dict:
        """One LLM call that both decides "is this a todo" and extracts fields.

        Used only by the ambient Telegram free-text path — explicit paths call
        :meth:`extract_todo_fields` directly since intent is already known.
        """
        today = datetime.now(_TAIPEI).date().isoformat()
        prompt = (
            f"Today's date is {today} (Asia/Taipei). Decide whether the message "
            "below describes a task or deadline the user wants to remember (a "
            "todo), as opposed to a general note, question, or casual chat.\n\n"
            f"Message:\n{text[:1000]}\n\n"
            "Respond with ONLY valid JSON (no markdown fences):\n"
            '{"is_todo": <true|false>, "confidence": <0.0-1.0>, '
            '"content": "<short task description>", '
            '"start_date": "<YYYY-MM-DD or null>", "due_date": "<YYYY-MM-DD or null>"}\n'
            "Resolve relative dates against today's date. If is_todo is false, "
            "content/start_date/due_date may be null. "
            "content 請使用繁體中文撰寫，不要使用簡體中文或英文（專有名詞可保留原文）。"
        )
        try:
            raw = await self.model_router.chat(
                "fast_text", [{"role": "user", "content": prompt}], temperature=0,
            )
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return {
                    "is_todo": bool(data.get("is_todo")),
                    "confidence": float(data.get("confidence") or 0.0),
                    "content": str(data.get("content") or text[:200]).strip(),
                    "start_date": self._parse_date(data.get("start_date")),
                    "due_date": self._parse_date(data.get("due_date")),
                }
        except (AllProvidersFailedError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Todo intent classification failed: {}", exc)
        return {
            "is_todo": False, "confidence": 0.0,
            "content": None, "start_date": None, "due_date": None,
        }

    async def create_todo_from_text(self, text: str, source: str) -> dict:
        """Explicit-intent todo creation — used by the desktop widget, the
        dashboard quick-add form, and Telegram's ``/todo`` command. Intent is
        already known here, so this skips straight to extraction with no
        is_todo classification step."""
        fields = await self.extract_todo_fields(text)
        return await self._persist_todo(
            content=fields["content"],
            source=source,
            raw_input=text,
            start_date=fields["start_date"],
            due_date=fields["due_date"],
        )

    async def maybe_create_todo_from_message(self, text: str, source: str = "telegram") -> dict:
        """Ambient todo detection for free Telegram text.

        Returns ``{"status": "not_todo"}`` immediately if the cheap regex
        pre-filter doesn't match or the LLM decides it isn't a todo — the
        caller's normal note/webclip routing is untouched in that case.
        """
        if not self._TODO_CREATE_HINT_PATTERN.search(text):
            return {"status": "not_todo"}

        classification = await self.classify_todo_intent(text)
        if not classification["is_todo"]:
            return {"status": "not_todo"}

        confidence = classification["confidence"]
        if confidence >= _AUTO_THRESHOLD:
            result = await self._persist_todo(
                content=classification["content"],
                source=source,
                raw_input=text,
                start_date=classification["start_date"],
                due_date=classification["due_date"],
            )
            result["status"] = "auto_created"
            return result

        if confidence >= _CONFIRM_THRESHOLD:
            confirmation_id = str(uuid.uuid4())
            self.pending_todo_confirmations[confirmation_id] = {
                "content": classification["content"],
                "source": source,
                "raw_input": text,
                "start_date": classification["start_date"],
                "due_date": classification["due_date"],
            }
            return {
                "status": "pending_confirmation",
                "confirmation_id": confirmation_id,
                "content": classification["content"],
                "due_date": (
                    classification["due_date"].isoformat()
                    if classification["due_date"] else None
                ),
            }

        return {"status": "not_todo"}

    async def confirm_todo(self, confirmation_id: str, accept: bool) -> dict:
        """Called when the user responds to a todo-creation confirmation via
        Telegram inline buttons (medium-confidence ambient detection)."""
        pending = self.pending_todo_confirmations.pop(confirmation_id, None)
        if pending is None:
            logger.warning("confirm_todo called for unknown confirmation_id={}", confirmation_id)
            return {
                "status": "failed",
                "message": f"No pending todo confirmation for {confirmation_id}",
            }
        if not accept:
            return {"status": "cancelled"}

        result = await self._persist_todo(
            content=pending["content"],
            source=pending["source"],
            raw_input=pending["raw_input"],
            start_date=pending["start_date"],
            due_date=pending["due_date"],
        )
        result["status"] = "auto_created"
        return result

    async def get_todos(
        self, status: str | None = "pending", due_before: str | None = None
    ) -> list[dict]:
        parsed_due_before = date.fromisoformat(due_before) if due_before else None
        async with self._session_maker() as db:
            todos = await crud.list_todos(db, status=status, due_before=parsed_due_before)
        return [
            {
                "id": str(t.id),
                "content": t.content,
                "status": t.status,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "source": t.source,
                "source_url": t.source_url,
                "created_at": t.created_at,
                "reminders": [
                    {"label": r.label, "remind_at": r.remind_at.astimezone(_TAIPEI).isoformat()}
                    for r in sorted(t.reminders, key=lambda r: r.remind_at)
                    if not r.sent
                ],
            }
            for t in todos
        ]

    async def update_todo_status(self, todo_id: str, status: str) -> dict:
        async with self._session_maker() as db:
            todo = await crud.update_todo_status(db, uuid.UUID(todo_id), status)
            if todo is None:
                return {"status": "failed", "message": "Todo not found"}
            await db.commit()
        return {"status": "completed", "todo_id": todo_id, "content": todo.content}

    async def snooze_todo(self, todo_id: str, days: int = 1) -> dict:
        """Add one more reminder *days* from now (09:00 Asia/Taipei), on top
        of whatever reminders already exist — doesn't touch or cancel them."""
        todo_uuid = uuid.UUID(todo_id)
        remind_date = datetime.now(_TAIPEI).date() + timedelta(days=days)
        remind_at = datetime.combine(remind_date, time(hour=_TODO_REMINDER_HOUR, tzinfo=_TAIPEI))

        async with self._session_maker() as db:
            todo = await crud.get_todo(db, todo_uuid)
            if todo is None:
                return {"status": "failed", "message": "Todo not found"}
            rows = await crud.create_todo_reminders(db, todo_uuid, [("snooze", remind_at)])
            await db.commit()

        for reminder in rows:
            self._schedule_reminder(str(reminder.id), reminder.remind_at)

        return {
            "status": "completed",
            "todo_id": todo_id,
            "content": todo.content,
            "remind_at": remind_at.isoformat(),
        }

    async def mark_todo_done_from_reminder(self, reminder_id: str) -> dict:
        """Used by the Telegram reminder message's "✅ 完成" button — resolves
        the reminder back to its parent todo, since the button only knows
        the reminder it was attached to."""
        async with self._session_maker() as db:
            reminder = await crud.get_todo_reminder(db, uuid.UUID(reminder_id))
        if reminder is None:
            return {"status": "failed", "message": "Reminder not found"}
        return await self.update_todo_status(str(reminder.todo_id), "done")

    async def snooze_todo_from_reminder(self, reminder_id: str, days: int = 1) -> dict:
        """Used by the Telegram reminder message's "😴 稍後提醒" button."""
        async with self._session_maker() as db:
            reminder = await crud.get_todo_reminder(db, uuid.UUID(reminder_id))
        if reminder is None:
            return {"status": "failed", "message": "Reminder not found"}
        return await self.snooze_todo(str(reminder.todo_id), days=days)

    async def _persist_todo(
        self,
        *,
        content: str,
        source: str,
        raw_input: str | None,
        start_date: date | None,
        due_date: date | None,
    ) -> dict:
        reminders = self._compute_reminders(start_date, due_date)
        source_url = self._extract_url(raw_input) if raw_input else None

        async with self._session_maker() as db:
            todo = await crud.create_todo(
                db,
                content=content,
                source=source,
                raw_input=raw_input,
                source_url=source_url,
                start_date=start_date,
                due_date=due_date,
            )
            await db.flush()
            todo_id = todo.id
            created_at = todo.created_at
            reminder_rows = await crud.create_todo_reminders(db, todo_id, reminders)
            await db.commit()

        for reminder in reminder_rows:
            self._schedule_reminder(str(reminder.id), reminder.remind_at)

        return {
            "id": str(todo_id),
            "todo_id": str(todo_id),
            "content": content,
            "status": "pending",
            "source": source,
            "source_url": source_url,
            "start_date": start_date.isoformat() if start_date else None,
            "due_date": due_date.isoformat() if due_date else None,
            "reminders": [
                {"label": r.label, "remind_at": r.remind_at.isoformat()} for r in reminder_rows
            ],
            "created_at": created_at,
        }

    @staticmethod
    def _schedule_reminder(reminder_id: str, remind_at: datetime) -> None:
        from backend.tasks.scheduler import get_scheduler, schedule_todo_reminder
        schedule_todo_reminder(get_scheduler(), reminder_id, remind_at)

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if not value or not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None

    @staticmethod
    def _compute_reminders(
        start_date: date | None, due_date: date | None
    ) -> list[tuple[str, datetime]]:
        """Build the reminder schedule for a todo — a rule-based set, not a
        recurring/periodic nag:
        - "start": on start_date, if given.
        - "due": the day before due_date, if given.
        - "midpoint": only when both dates are given AND the gap exceeds
          _TODO_MIDPOINT_GAP_DAYS, so a long-running task isn't silent the
          whole way through.
        All fire at 09:00 Asia/Taipei. Duplicate dates collapse to one entry.
        """
        candidates: list[tuple[str, date]] = []
        if start_date:
            candidates.append(("start", start_date))
        if due_date:
            candidates.append(("due", due_date - timedelta(days=1)))
        if start_date and due_date:
            gap_days = (due_date - start_date).days
            if gap_days > _TODO_MIDPOINT_GAP_DAYS:
                midpoint = start_date + timedelta(days=gap_days // 2)
                candidates.append(("midpoint", midpoint))

        seen_dates: set[date] = set()
        reminders: list[tuple[str, datetime]] = []
        for label, d in candidates:
            if d in seen_dates:
                continue
            seen_dates.add(d)
            reminders.append(
                (label, datetime.combine(d, time(hour=_TODO_REMINDER_HOUR, tzinfo=_TAIPEI)))
            )
        reminders.sort(key=lambda r: r[1])
        return reminders

    _URL_PATTERN = re.compile(r"https?://\S+")
    _URL_TRAILING_PUNCT = ".,;:!?)]}、。，；：！？」』"

    @classmethod
    def _extract_url(cls, text: str) -> str | None:
        match = cls._URL_PATTERN.search(text)
        if not match:
            return None
        return match.group(0).rstrip(cls._URL_TRAILING_PUNCT)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def _route(self, input_type: str, content: str) -> tuple[str, float]:
        """Return (agent_name, confidence) for the given input.

        Fast-lane rules (deterministic, no LLM call):
          image / photo / screenshot → screenshot-agent  (1.0)
          audio / voice              → meeting-agent     (1.0)
          url                        → webclip-agent     (0.95)
          file / doc / document      → document-agent    (0.90)
          text (short, < 200 chars)  → note-agent        (0.85)
          text (long)                → LLM classify

        Any other unrecognised type falls through to LLM routing.
        """
        key = input_type.lower()

        # Deterministic fast-lane
        if key in _FAST_LANE:
            return _FAST_LANE[key]

        # Text: short content → note, long → LLM
        if key in ("text", "note"):
            stripped = (content or "").strip()
            if len(stripped) < 200:
                return "note-agent", 0.85
            return await self._llm_route(stripped)

        # Unknown type: delegate to LLM
        return await self._llm_route(content or "")

    async def _llm_route(self, content: str) -> tuple[str, float]:
        """Use a fast_text LLM to classify content against enabled agent descriptions.

        Returns (agent_name, confidence).  Falls back to note-agent at 0.3 on
        any failure so the pipeline always has somewhere to route.
        """
        enabled = self.skills_loader.get_enabled_skills()
        if not enabled:
            logger.warning("No enabled skills found; falling back to note-agent")
            return "note-agent", 0.5

        descriptions = "\n".join(
            f"- {s.name}: {s.description}" for s in enabled
        )
        prompt = (
            "You are a content-routing assistant. Given the content snippet below, "
            "decide which agent is best suited to handle it.\n\n"
            f"Available agents:\n{descriptions}\n\n"
            f"Content (first 500 chars):\n{content[:500]}\n\n"
            "Respond with ONLY valid JSON (no markdown fences):\n"
            '{"agent_name": "<exact name from list above>", "confidence": <0.0-1.0>}'
        )

        try:
            raw = await self.model_router.chat(
                "fast_text",
                [{"role": "user", "content": prompt}],
                temperature=0,
            )
            # Extract the JSON object even if the model wrapped it in prose.
            match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                agent = str(data["agent_name"])
                conf = float(data["confidence"])
                # Validate agent name is actually in the enabled list
                enabled_names = {s.name for s in enabled}
                if agent not in enabled_names:
                    logger.warning(
                        "LLM returned unknown agent '{}'; falling back to note-agent", agent
                    )
                    return "note-agent", 0.3
                return agent, conf
        except (AllProvidersFailedError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("LLM routing failed: {}", exc)

        return "note-agent", 0.3

    # ------------------------------------------------------------------
    # Execution (with retry)
    # ------------------------------------------------------------------

    async def _execute_and_save(
        self,
        doc_id: uuid.UUID,
        agent_name: str,
        processed: Any,
    ) -> dict:
        """Run the agent and persist all results.  Retries up to _MAX_RETRIES times."""
        skill = self.skills_loader.get_skill(agent_name)
        if skill is None:
            raise ValueError(f"Agent '{agent_name}' not found or is disabled.")

        # Mark as processing
        async with self._session_maker() as db:
            await crud.update_document_status(
                db,
                doc_id,
                "processing",
                title=processed.title,
                original_content=processed.original_content,
                file_path=processed.file_path,
                source_url=processed.source_url,
                agent_used=agent_name,
            )
            await db.commit()

        # Run the agent with retry logic
        agent_result = await self._execute_agent_with_retry(skill, processed)

        # Persist structured results
        async with self._session_maker() as db:
            await crud.update_document_status(
                db,
                doc_id,
                "completed",
                title=agent_result.get("title") or processed.title,
                summary=agent_result.get("summary"),
                category=agent_result.get("category"),
                type_specific_data=agent_result.get("type_specific_data"),
            )
            # Tags
            tags = agent_result.get("suggested_tags") or []
            if tags:
                await crud.add_tags(db, doc_id, tags)

            # LLM-assisted project classification against the existing project list
            project_name, project_confidence = await self._classify_project(
                db, agent_result, processed
            )
            if project_name:
                if project_confidence >= _AUTO_THRESHOLD:
                    project = await crud.get_or_create_project(db, project_name)
                    await crud.link_document_project(
                        db, doc_id, project.id, confidence=project_confidence,
                    )
                elif project_confidence >= _CONFIRM_THRESHOLD:
                    # Medium confidence → ask the user via Telegram before linking.
                    self.pending_project_confirmations[str(doc_id)] = project_name
                    agent_result["_pending_project"] = {
                        "project_name": project_name,
                        "confidence": project_confidence,
                    }
                # else: too low-confidence to even suggest — leave unlinked.

            await db.commit()

        # Post-process asynchronously (embedding + Qdrant + relations)
        # Failures here are non-critical and must not block the response.
        await self._post_process(doc_id, processed, agent_result)

        return agent_result

    async def _execute_agent_with_retry(
        self,
        skill: SkillDefinition,
        processed: Any,
        max_retries: int = _MAX_RETRIES,
    ) -> dict:
        """Call _execute_agent with exponential back-off retry on transient failures."""
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await self._execute_agent(skill, processed)
            except AllProvidersFailedError as exc:
                last_exc = exc
                if attempt < max_retries:
                    delay = _RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "Agent '{}' attempt {}/{} failed (AllProvidersFailedError). "
                        "Retrying in {:.1f}s…",
                        skill.name, attempt + 1, max_retries + 1, delay,
                    )
                    await asyncio.sleep(delay)
            except Exception as exc:
                # Non-transient failure: surface immediately without retry
                logger.warning("Agent '{}' non-transient failure: {}", skill.name, exc)
                raise

        logger.error(
            "Agent '{}' exhausted {} retries. Using fallback output.",
            skill.name, max_retries,
        )
        return self._fallback_result(processed)

    async def _execute_agent(self, skill: SkillDefinition, processed: Any) -> dict:
        """Run the actual agent work: call the LLM and extract structured output.

        Each skill's own SKILL.md documents its own output_schema (e.g. a
        meeting has ``attendees``/``decisions``, a document has
        ``chunk_summaries``) — the LLM must follow *that* schema, not a generic
        one, or the two instructions conflict and the model ends up satisfying
        whichever it weighs more heavily. The raw output is then normalized via
        :func:`normalize_agent_output` onto the generic fields (summary,
        category, suggested_tags, ...) the rest of the pipeline relies on.
        """
        user_content = processed.original_content or ""
        if processed.source_url:
            user_content = f"URL: {processed.source_url}\n\n{user_content}"

        messages = [
            {
                "role": "system",
                "content": skill.system_prompt or "You are a helpful knowledge assistant.",
            },
            {
                "role": "user",
                "content": (
                    "Process the following content and return ONLY the JSON object "
                    "described in the Output Format above — no markdown fences, "
                    "no extra commentary, no keys beyond that schema.\n\n"
                    f"{user_content[:4000]}"
                ),
            },
        ]

        raw = await self.model_router.chat(skill.model, messages, temperature=0.2)
        # Extract the outermost JSON object, tolerating markdown code fences.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                return normalize_agent_output(skill.output_schema, parsed)
            except json.JSONDecodeError as exc:
                logger.warning("Agent '{}' returned invalid JSON: {}", skill.name, exc)

        return self._fallback_result(processed)

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    async def _post_process(
        self,
        doc_id: uuid.UUID,
        processed: Any,
        agent_result: dict,
    ) -> None:
        """Generate embedding, store in Qdrant, find similar docs, add relations.

        This is intentionally non-critical: any exception is logged and swallowed
        so it never blocks the response returned to the user.
        """
        try:
            # 1. Build the text to embed: summary + a slice of the original.
            text_for_embedding = " ".join(filter(None, [
                agent_result.get("summary", ""),
                (processed.original_content or "")[:500],
            ])).strip()

            if not text_for_embedding:
                logger.debug("No embeddable text for doc {}; skipping Qdrant.", doc_id)
                return

            # 2. Generate the embedding vector.
            vector = await self.model_router.get_embedding(text_for_embedding)
            doc_id_str = str(doc_id)

            # 3. Upsert into Qdrant.
            await self.qdrant.upsert_document(
                doc_id=doc_id_str,
                vector=vector,
                payload={
                    "title": processed.title,
                    "summary": agent_result.get("summary", ""),
                    "category": agent_result.get("category", ""),
                    "source_type": processed.source_type,
                },
            )
            logger.debug("Upserted doc {} into Qdrant.", doc_id)

            # 4. Find semantically similar documents (score > threshold).
            similar = await self.qdrant.search_similar(vector, limit=5)

            # 5. Persist relation edges in PostgreSQL — two independent signals:
            #    semantic similarity (Qdrant, above) and shared keyword tags
            #    (PostgreSQL join, below). Both may fire for the same pair.
            tags = agent_result.get("suggested_tags") or []
            async with self._session_maker() as db:
                for hit in similar:
                    if hit["id"] == doc_id_str:
                        continue  # skip self
                    if hit["score"] < _RELATION_THRESHOLD:
                        continue
                    try:
                        await crud.add_relation(
                            db,
                            doc_id,
                            uuid.UUID(hit["id"]),
                            "semantic",
                            hit["score"],
                        )
                    except Exception as rel_exc:
                        # A failed relation is never worth aborting the loop.
                        logger.debug(
                            "Skipping relation {} ↔ {}: {}",
                            doc_id, hit["id"], rel_exc,
                        )

                if tags:
                    shared = await crud.get_documents_sharing_tags(db, doc_id, tags)
                    for other_id, shared_count in shared:
                        if shared_count < _SHARED_TAG_MIN_COUNT:
                            continue
                        score = min(shared_count / len(tags), 1.0)
                        try:
                            await crud.add_relation(db, doc_id, other_id, "shared_tag", score)
                        except Exception as rel_exc:
                            logger.debug(
                                "Skipping shared_tag relation {} ↔ {}: {}",
                                doc_id, other_id, rel_exc,
                            )

                await db.commit()
            logger.debug(
                "Post-processing complete for doc {} ({} similar docs checked, {} tags).",
                doc_id, len(similar), len(tags),
            )

        except AllProvidersFailedError:
            logger.warning(
                "Embedding skipped for doc {} — all LLM providers failed.", doc_id
            )
        except Exception as exc:
            logger.warning("Post-processing failed for doc {}: {}", doc_id, exc)

    # ------------------------------------------------------------------
    # LLM-assisted project classification
    # ------------------------------------------------------------------

    async def _classify_project(
        self,
        db: AsyncSession,
        agent_result: dict,
        processed: Any,
    ) -> tuple[str | None, float]:
        """Choose the best-matching project using LLM + existing project list.

        Falls back to the agent's own suggestion when the LLM call fails or
        when no projects exist yet. Does **not** decide whether to auto-link,
        ask for confirmation, or skip — that confidence-tiering decision is
        made by the caller (:meth:`_execute_and_save`) using the same
        ``_AUTO_THRESHOLD``/``_CONFIRM_THRESHOLD`` bands as agent routing.

        Returns ``(project_name, confidence)`` — ``project_name`` is ``None``
        when no candidate was found at all.
        """
        # The agent may have already suggested a project.
        agent_suggestion = agent_result.get("suggested_project")
        agent_confidence = float(agent_result.get("project_confidence") or 0.0)

        # Fetch active projects to ground the classification.
        try:
            existing_projects = await crud.get_projects(db)
        except Exception as exc:
            logger.warning("Could not fetch project list: {}; using agent suggestion.", exc)
            return agent_suggestion, agent_confidence

        # If no projects exist yet, trust the agent directly (it will create one).
        if not existing_projects:
            return agent_suggestion, agent_confidence

        project_list = "\n".join(f"- {p.name}" for p in existing_projects)
        summary = agent_result.get("summary", "")
        content_snippet = (processed.original_content or "")[:300]

        prompt = (
            "You are a project classifier. Given the document summary and the list "
            "of existing projects, decide which project this document belongs to.\n\n"
            f"Document summary:\n{summary}\n\n"
            f"Content snippet:\n{content_snippet}\n\n"
            f"Existing projects:\n{project_list}\n\n"
            "Respond with ONLY valid JSON (no markdown fences):\n"
            '{"project_name": "<exact name from list, or a new name, or null>", '
            '"confidence": <0.0-1.0>}\n'
            "Return null for project_name if this document does not clearly belong to any project."
        )

        try:
            raw = await self.model_router.chat(
                "fast_text",
                [{"role": "user", "content": prompt}],
                temperature=0,
            )
            match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                project_name = data.get("project_name")
                llm_confidence = float(data.get("confidence") or 0.0)
                if project_name:
                    logger.debug(
                        "LLM classified doc into project '{}' (conf={:.2f})",
                        project_name, llm_confidence,
                    )
                    return project_name, llm_confidence
        except (AllProvidersFailedError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Project classification LLM call failed: {}", exc)

        # Fall back to the agent's own suggestion.
        return agent_suggestion, agent_confidence

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _mark_failed(self, doc_id: uuid.UUID, reason: str, **extra: Any) -> None:
        """Persist a 'failed' status for a document, swallowing any DB errors.

        *extra* may carry ``file_path``/``source_url``/``original_content`` so
        a later call to :meth:`retry_document` has something to reconstruct
        the original input from.
        """
        try:
            async with self._session_maker() as db:
                await crud.update_document_status(db, doc_id, "failed", **extra)
                await db.commit()
        except Exception as exc:
            logger.error(
                "Could not mark doc {} as failed (reason: {}): {}", doc_id, reason, exc
            )

    @staticmethod
    def _raw_input_fields(input_type: str, input_data: Any) -> dict:
        """Best-effort mapping of *input_data* onto the Document row's raw-input
        columns, keyed by what kind of value each input_type actually carries."""
        key = input_type.lower()
        if key == "url":
            return {"source_url": str(input_data)}
        if key in ("text", "note"):
            return {"original_content": str(input_data)}
        # image/photo/screenshot/audio/voice/video/file/doc/document all pass
        # a filesystem path as input_data.
        return {"file_path": str(input_data)}

    @staticmethod
    def _normalize_source_type(input_type: str) -> str:
        """Map user-facing input_type strings to canonical DB source_type values."""
        mapping: dict[str, str] = {
            "image":    "screenshot",
            "photo":    "screenshot",
            "audio":    "meeting",
            "voice":    "meeting",
            "video":    "meeting",
            "url":      "webclip",
            "file":     "doc",
            "document": "doc",
            "text":     "note",
        }
        return mapping.get(input_type.lower(), input_type.lower())

    @staticmethod
    def _fallback_result(processed: Any) -> dict:
        """Minimal structured output used when the LLM agent call fails entirely."""
        snippet = (processed.original_content or "")[:200]
        return {
            "summary": snippet,
            "category": "General",
            "suggested_tags": [],
            "suggested_project": None,
            "project_confidence": 0.0,
            "type_specific_data": {},
        }
