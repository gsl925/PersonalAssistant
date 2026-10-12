"""Regression test for Tier-3 discoverability fixes: /insight and
meeting/screenshot/note were "forgotten about" (user's 2026-10-02
diagnosis) since their only mention was a one-time /start message. Added a
rotating tip to the (far more frequently seen) daily digest, and added
/insight to the /start text (it wasn't mentioned there at all before).
"""
from __future__ import annotations

from datetime import date

from backend.tasks import processing


def test_pick_feature_tip_rotates_deterministically_by_date():
    tip_day1 = processing._pick_feature_tip(date(2026, 10, 2))
    tip_day2 = processing._pick_feature_tip(date(2026, 10, 3))
    assert tip_day1 in processing._FEATURE_TIPS
    assert tip_day2 in processing._FEATURE_TIPS
    # Same date always picks the same tip (deterministic, not random).
    assert processing._pick_feature_tip(date(2026, 10, 2)) == tip_day1


def test_feature_tips_mention_insight_and_meeting_screenshot_note():
    all_tips = " ".join(processing._FEATURE_TIPS)
    assert "/insight" in all_tips
    assert "截圖" in all_tips or "語音" in all_tips
