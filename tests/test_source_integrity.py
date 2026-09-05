import pytest
import os
from unittest.mock import MagicMock
from worker.geo_disambiguation import is_tactical_threat_candidate, is_civilian_non_threat_noise
from bot.handlers.utils import get_dashboard_url

def test_retrospective_digest_rejection():
    # Retrospective summaries must NOT be treated as tactical threat candidates
    weekly_digest = "[Київ: найважливіше за тиждень] У понеділок було зафіксовано приліт БпЛА у приватному секторі."
    assert is_civilian_non_threat_noise(weekly_digest) is True
    assert is_tactical_threat_candidate(weekly_digest) is False

    daily_digest = "Підсумки доби: сили оборони знищили 40 крилатих ракет та 20 шахедів."
    assert is_civilian_non_threat_noise(daily_digest) is True
    assert is_tactical_threat_candidate(daily_digest) is False

def test_authentic_military_alerts_accepted():
    # Legitimate tactical alerts must be accepted
    real_alert = "🛵 Реактивні БпЛА на Бровари."
    assert is_civilian_non_threat_noise(real_alert) is False
    assert is_tactical_threat_candidate(real_alert) is True

    fast_target = "🚀 Швидкісна ціль на Дніпро"
    assert is_civilian_non_threat_noise(fast_target) is False
    assert is_tactical_threat_candidate(fast_target) is True

def test_dashboard_url_fallback(monkeypatch):
    # If DASHBOARD_URL is empty, fallback must not be 127.0.0.1
    monkeypatch.delenv("DASHBOARD_URL", raising=False)
    monkeypatch.setattr("bot.handlers.utils.redis_client.get", MagicMock(return_value=None))
    url = get_dashboard_url()
    assert url != "http://127.0.0.1"
    assert "136.113.156.17" in url
