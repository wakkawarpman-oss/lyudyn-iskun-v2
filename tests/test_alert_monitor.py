from datetime import datetime
from unittest.mock import MagicMock, patch
from bot.alert_monitor import (
    format_all_clear_banner,
    format_active_alert_banner,
    register_vidbiy_subscriber,
    unregister_vidbiy_subscriber,
    get_vidbiy_subscribers,
    clear_vidbiy_subscribers,
    get_current_kyiv_alert_status
)


def test_format_all_clear_banner_content():
    t = datetime(2026, 9, 3, 3, 15, 20)
    banner = format_all_clear_banner(
        region="м. Київ",
        event_time=t,
        source="КМВА (@kyiv_alarm)"
    )
    assert "🟩" in banner
    assert "ВІДБІЙ ТРИВОГИ!" in banner
    assert "м. Київ" in banner
    assert "КМВА (@kyiv_alarm)" in banner
    assert "Загроза ворожих ударів минула" in banner


def test_format_active_alert_banner_content():
    t = datetime(2026, 9, 3, 3, 15, 20)
    banner = format_active_alert_banner(
        region="м. Київ та Київська область",
        event_time=t,
        threat_info="Загроза Shahed-136"
    )
    assert "🟥" in banner
    assert "ПОВІТРЯНА ТРИВОГА!" in banner
    assert "РЕЖИМ МОНІТОРИНГУ ВІДБОЮ АКТИВОВАНО" in banner


def test_subscriber_management_lifecycle():
    mock_redis = MagicMock()
    mock_set = set()

    def mock_sadd(key, val):
        mock_set.add(val)
        return 1

    def mock_srem(key, val):
        mock_set.discard(val)
        return 1

    def mock_smembers(key):
        return {s.encode("utf-8") for s in mock_set}

    def mock_delete(key):
        mock_set.clear()
        return 1

    mock_redis.sadd.side_effect = mock_sadd
    mock_redis.srem.side_effect = mock_srem
    mock_redis.smembers.side_effect = mock_smembers
    mock_redis.delete.side_effect = mock_delete

    with patch("bot.alert_monitor.redis_client", mock_redis):
        clear_vidbiy_subscribers()
        chat_id = 999888777
        assert register_vidbiy_subscriber(chat_id) is True
        subs = get_vidbiy_subscribers()
        assert str(chat_id) in subs

        assert unregister_vidbiy_subscriber(chat_id) is True
        subs_after = get_vidbiy_subscribers()
        assert str(chat_id) not in subs_after


def test_get_current_kyiv_alert_status_safe_fallback():
    status = get_current_kyiv_alert_status()
    assert isinstance(status, dict)
    assert "is_alert" in status
    assert "status_text" in status
    assert "source" in status
