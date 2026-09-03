from datetime import datetime, timezone
from database.models import DetectedEvent
from bot.ui_formatter import (
    format_confirmation_tier,
    format_event_type_human,
    format_human_event_card,
    clean_event_snippet,
)


def test_format_confirmation_tier_official():
    e = DetectedEvent(
        source_channel="kyivcityofficial",
        is_official=True,
        sources_count=1,
        verification_status="OFFICIAL"
    )
    badge, explanation = format_confirmation_tier(e)
    assert "🟢" in badge
    assert "Підтверджено" in badge
    assert "офіційного джерела" in explanation


def test_format_confirmation_tier_multi_source():
    e = DetectedEvent(
        source_channel="war_monitor",
        is_official=False,
        sources_count=3,
        source_weight=1.6,
        verification_status="VERIFIED"
    )
    badge, explanation = format_confirmation_tier(e)
    assert "🟢" in badge
    assert "Підтверджено" in badge
    assert "3 дж." in explanation


def test_format_confirmation_tier_single_source():
    e = DetectedEvent(
        source_channel="povitryanatrivogaaa",
        is_official=False,
        sources_count=1,
        source_weight=0.5,
        verification_status="UNVERIFIED_SINGLE_SOURCE"
    )
    badge, explanation = format_confirmation_tier(e)
    assert "🟡" in badge
    assert "Повідомляється" in badge
    assert "потребує уточнення" in explanation


def test_format_confirmation_tier_investigating():
    e = DetectedEvent(
        source_channel="some_channel",
        is_official=False,
        sources_count=1,
        verification_status="INVESTIGATING"
    )
    badge, explanation = format_confirmation_tier(e)
    assert "⚪" in badge
    assert "уточню" in explanation


def test_refined_threat_taxonomy():
    assert "Влучання / Наслідки атаки" in format_event_type_human("direct_strike")
    assert "БпЛА" in format_event_type_human("radar_track")
    assert "Вибух" in format_event_type_human("explosion")
    assert "Пожежа" in format_event_type_human("fire")
    assert "Робота сил ППО" in format_event_type_human("air_defense")


def test_human_card_no_internal_c2_leaks():
    e = DetectedEvent(
        id=123,
        detected_at=datetime(2026, 9, 3, 10, 6, 0, tzinfo=timezone.utc),
        event_type="direct_strike",
        location_text="Біла Церква",
        source_channel="kyivcityofficial",
        message_id=20253,
        message_text="Наслідки атаки противника у Білій Церкві",
        is_official=True,
        sources_count=1,
        verification_status="OFFICIAL"
    )
    card = format_human_event_card(1, e)

    # Must contain clear human information
    assert "1. Біла Церква" in card
    assert "10:06" in card or "13:06" in card
    assert "🟢 <b>Підтверджено</b>" in card
    assert "Першоджерело" in card

    # MUST NOT leak internal developer plumbing
    assert "PostGIS" not in card
    assert "GIST" not in card
    assert "C2 Схема" not in card
    assert "Consensus weight" not in card
    assert "Vision AI" not in card
    assert "EXIF GPS" not in card


def test_clean_snippet_sanitization():
    raw = "<b>Увага!</b> Повідомлення з посиланням https://t.me/example та [текстом](https://link.com)"
    clean = clean_event_snippet(raw)
    assert "https://" not in clean
    assert "<b>" not in clean
    assert "Увага!" in clean
