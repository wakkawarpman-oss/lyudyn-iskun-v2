"""
Unit tests for Human-in-the-Loop (HITL) Tactical Review & Feedback.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.hitl import (
    get_source_reputation,
    save_source_reputation,
    build_hitl_keyboard,
    process_hitl_callback
)
from worker.grading import SourceReputation


def test_hitl_keyboard_builder():
    """Verify inline keyboard markup contains confirm, fake, and noise buttons."""
    markup = build_hitl_keyboard(42)
    buttons = [btn for row in markup.inline_keyboard for btn in row]
    callbacks = [btn.callback_data for btn in buttons]
    assert "hitl:confirm:42" in callbacks
    assert "hitl:fake:42" in callbacks
    assert "hitl:noise:42" in callbacks


def test_get_and_save_source_reputation():
    """Verify Redis persistence and deserialization of SourceReputation."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    # Default prior (2/2)
    rep = get_source_reputation("kievreal1", r_client=mock_redis)
    assert rep.alpha == 2.0
    assert rep.beta == 2.0
    assert rep.reputation() == 0.5

    # Update with confirm (+1 alpha)
    rep.update(confirmed=True)
    assert rep.alpha == 3.0
    assert rep.beta == 2.0
    assert rep.reputation() == 0.6

    save_source_reputation("kievreal1", rep, r_client=mock_redis)
    assert mock_redis.set.called


@pytest.mark.anyio
async def test_process_hitl_confirm_callback():
    """Verify analyst confirmation updates event status and increments alpha."""
    mock_callback = MagicMock()
    mock_callback.data = "hitl:confirm:101"
    mock_callback.from_user.username = "tactical_officer"
    mock_callback.message.edit_text = AsyncMock()
    mock_callback.answer = AsyncMock()

    mock_event = MagicMock()
    mock_event.id = 101
    mock_event.source_channel = "@operatyvnyi_monitor"
    mock_event.location_text = "Вишгород"
    mock_event.confidence_score = 50
    mock_event.verification_status = "UNVERIFIED_SINGLE_SOURCE"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_event

    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # fresh rep

    with patch("bot.handlers.hitl.SessionLocal", return_value=mock_db), \
         patch("bot.handlers.hitl._get_redis_client", return_value=mock_redis):
        await process_hitl_callback(mock_callback)

        assert mock_event.verification_status == "CONFIRMED_ANALYST"
        assert mock_event.confidence_score == 75
        assert mock_db.commit.called
        assert mock_redis.set.called  # Saved updated rep
        assert mock_callback.message.edit_text.called
        assert mock_callback.answer.called


@pytest.mark.anyio
async def test_process_hitl_fake_callback():
    """Verify analyst fake report updates event status and increments beta."""
    mock_callback = MagicMock()
    mock_callback.data = "hitl:fake:202"
    mock_callback.from_user.username = "tactical_officer"
    mock_callback.message.edit_text = AsyncMock()
    mock_callback.answer = AsyncMock()

    mock_event = MagicMock()
    mock_event.id = 202
    mock_event.source_channel = "@fake_channel"
    mock_event.location_text = "Київ"
    mock_event.confidence_score = 60
    mock_event.verification_status = "POSSIBLE_IPSO"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_event

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch("bot.handlers.hitl.SessionLocal", return_value=mock_db), \
         patch("bot.handlers.hitl._get_redis_client", return_value=mock_redis):
        await process_hitl_callback(mock_callback)

        assert mock_event.verification_status == "REJECTED_ANALYST"
        assert mock_event.confidence_score == 20
        assert mock_db.commit.called
        assert mock_redis.set.called
        assert mock_callback.message.edit_text.called
