"""
Unit tests for NATS JetStream Tactical Intelligence Publisher.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from listener.nats_publisher import publish_tg_report, get_jetstream, close_nats


@pytest.mark.anyio
async def test_nats_offline_fallback():
    """Verify that when NATS is offline/unreachable, publish_tg_report fails safely without raising."""
    with patch("listener.nats_publisher.nats.connect", side_effect=ConnectionError("NATS offline")):
        await close_nats()
        payload = {
            "channel": "@kievreal1",
            "message_id": 12345,
            "oblast": "kyiv_city",
            "text": "Вибухи на Лівому березі",
            "date": "2026-09-04T19:00:00Z"
        }
        res = await publish_tg_report(payload)
        assert res is False


@pytest.mark.anyio
async def test_nats_publish_success_and_headers():
    """Verify that publish_tg_report correctly formats subjects, payloads, and Nats-Msg-Id dedup headers."""
    mock_ack = MagicMock()
    mock_ack.seq = 42

    mock_js = MagicMock()
    mock_js.publish = AsyncMock(return_value=mock_ack)

    with patch("listener.nats_publisher.get_jetstream", AsyncMock(return_value=mock_js)):
        payload = {
            "channel": "@kievreal1",
            "message_id": 999,
            "oblast": "kyiv_city",
            "text": "Пуск ракети у бік столиці",
            "date": "2026-09-04T19:15:00Z"
        }
        res = await publish_tg_report(payload)
        assert res is True
        assert mock_js.publish.called

        # Verify subject & headers
        call_args = mock_js.publish.call_args
        subject = call_args[0][0]
        data_bytes = call_args[0][1]
        headers = call_args[1]["headers"]

        assert subject == "osint.tg.report.kyiv_city"
        assert "Пуск ракети".encode("utf-8") in data_bytes
        assert headers["Nats-Msg-Id"] == "kievreal1_999"
        assert headers["X-Source-Channel"] == "@kievreal1"
        assert headers["X-Detected-At"] == "2026-09-04T19:15:00Z"
