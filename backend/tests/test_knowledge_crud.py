"""Regression test for the daily-digest day-boundary bug.

get_documents_created_today() used to compute "today" as UTC midnight, but
the digest cron fires at 08:00 Asia/Taipei == 00:00 UTC, so at the exact
moment the digest ran, the UTC-midnight boundary equalled "now" itself —
collapsing the window to zero width and silently excluding every document
added since the previous run.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.knowledge import crud
from backend.knowledge.db import async_session_maker
from backend.knowledge.models import Document


class _FrozenDateTime(datetime):
    """datetime subclass whose .now() always returns a fixed instant."""

    _frozen: datetime

    @classmethod
    def now(cls, tz=None):  # noqa: D102
        return cls._frozen.astimezone(tz) if tz else cls._frozen


@pytest.mark.asyncio
async def test_get_documents_created_today_uses_taipei_midnight_not_utc():
    # Freeze "now" to the exact moment the digest cron fires: 08:00 Taipei,
    # which is 00:00 UTC on the same calendar day.
    frozen_now = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc)
    frozen_cls = type("_Frozen", (_FrozenDateTime,), {"_frozen": frozen_now})

    # Created 1 hour before the digest runs (07:00 Taipei / 23:00 UTC the
    # previous day) — squarely "today" in Taipei terms. The old UTC-midnight
    # boundary equalled `frozen_now` exactly, so this document (created
    # before that instant) was always wrongly excluded.
    included_at = datetime(2026, 10, 1, 23, 0, 0, tzinfo=timezone.utc)
    # Created the previous Taipei day (10:00 Taipei / 02:00 UTC) — must stay
    # excluded under the fix too.
    excluded_at = datetime(2026, 10, 1, 2, 0, 0, tzinfo=timezone.utc)

    included_id = uuid.uuid4()
    excluded_id = uuid.uuid4()

    async with async_session_maker() as session:
        try:
            session.add_all(
                [
                    Document(
                        id=included_id,
                        source_type="webclip",
                        processing_status="completed",
                        created_at=included_at,
                    ),
                    Document(
                        id=excluded_id,
                        source_type="webclip",
                        processing_status="completed",
                        created_at=excluded_at,
                    ),
                ]
            )
            await session.flush()

            with patch("backend.knowledge.crud.datetime", frozen_cls):
                docs = await crud.get_documents_created_today(session)

            found_ids = {d.id for d in docs}
            assert included_id in found_ids, (
                "document created 07:00 Taipei today should be in the digest window"
            )
            assert excluded_id not in found_ids, (
                "document created the previous Taipei day must stay excluded"
            )
        finally:
            await session.rollback()
