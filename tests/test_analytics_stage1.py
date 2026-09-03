from unittest.mock import MagicMock, patch
from worker.scoring import calculate_confidence_score
from worker.tasks import get_time_window_stats, cleanup_old_events


def test_weighted_consensus_beats_simple_count():
    """
    A.5 Contract: 1 Official source (1.0 weight) must score higher
    than 2 low-trust aggregators (0.45 * 2 = 0.9 combined weight).
    """
    official_score = calculate_confidence_score(["dsns_kyiv_region"], is_official=True)
    aggregators_score = calculate_confidence_score(["povitryanatrivogaaa", "kyiv_alarm"])
    
    assert official_score == 90
    assert aggregators_score == 40
    assert official_score > aggregators_score


def test_monitor_plus_aggregator_boosts():
    """
    A.5 Contract:
    - 2 Monitors (0.75 + 0.80 = 1.55 >= 1.5) -> 85
    - 1 Monitor (0.75) + 1 Aggregator (0.45) = 1.2 -> 70
    - 1 Aggregator alone (0.45) -> 40
    """
    double_monitors = calculate_confidence_score(["monitor_ukr", "war_monitor"])
    mixed_score = calculate_confidence_score(["monitor_ukr", "kyiv_alarm"])
    single_aggregator = calculate_confidence_score(["kyiv_alarm"])

    assert double_monitors == 85
    assert mixed_score == 70
    assert single_aggregator == 40
    assert double_monitors > mixed_score > single_aggregator


def test_time_window_spike_detection_logic():
    """
    A.2 Contract:
    - 5m_count >= 3 AND 5m_count >= (60m_count / 12.0) * 2.0 -> Spike = True
    - Empty or low baseline -> Spike = False
    """
    # 1. Mock DB returning baseline: 0 in 5m, 12 in 60m -> No spike
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.scalar.side_effect = [
        0,  # 5m
        2,  # 15m
        12  # 60m
    ]
    stats = get_time_window_stats(mock_db)
    assert stats["events_5m"] == 0
    assert stats["events_60m"] == 12
    assert stats["spike"] is False

    # 2. Mock DB returning spike: 4 in 5m, 14 in 60m (baseline rate 14/12 = 1.16, 4 >= 2.33) -> Spike = True
    mock_db_spike = MagicMock()
    mock_db_spike.query.return_value.filter.return_value.scalar.side_effect = [
        4,  # 5m
        8,  # 15m
        14  # 60m
    ]
    stats_spike = get_time_window_stats(mock_db_spike)
    assert stats_spike["events_5m"] == 4
    assert stats_spike["events_60m"] == 14
    assert stats_spike["spike"] is True

    # 3. Empty DB -> Spike = False
    mock_db_empty = MagicMock()
    mock_db_empty.query.return_value.filter.return_value.scalar.side_effect = [
        0,
        0,
        0
    ]
    stats_empty = get_time_window_stats(mock_db_empty)
    assert stats_empty["spike"] is False


def test_tiered_cleanup_execution():
    """
    Retention Contract:
    - Tier 1: Delete noise records older than 24h.
    - Tier 2: Archive physical strike records older than 90d.
    - Redis caches flushed.
    """
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.delete.return_value = 5
    mock_session.query.return_value.filter.return_value.update.return_value = 2

    with patch("worker.tasks.SessionLocal", return_value=mock_session), \
         patch("worker.tasks.redis.Redis.from_url") as mock_redis:
        
        result = cleanup_old_events(retention_hours=24)
        
        assert result["status"] == "success"
        assert result["tier1_deleted_24h_garbage"] == 5
        assert result["tier2_archived_90d_strikes"] == 2
        assert result["total_operations"] == 7
        
        # Verify commit called twice (once for Tier 1, once for Tier 2)
        assert mock_session.commit.call_count == 2
        # Verify Redis flush called for stale caches
        mock_redis.return_value.delete.assert_any_call("api:events")
        mock_redis.return_value.delete.assert_any_call("api:stats")
