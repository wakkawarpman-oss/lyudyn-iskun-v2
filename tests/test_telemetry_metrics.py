"""
Unit tests for Tactical Telemetry & Precision Metrics Engine.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from worker.telemetry_metrics import (
    haversine_distance_m,
    calculate_cep_delta,
    calculate_eta_drift_sec,
    get_system_accuracy_telemetry
)


def test_haversine_distance_and_cep():
    """Verify geodesic distance calculation between known Kyiv landmarks."""
    # Khreshchatyk (50.4501, 30.5234) to Maidan (50.4506, 30.5230) ~ 60 meters
    dist = haversine_distance_m(50.4501, 30.5234, 50.4506, 30.5230)
    assert 40.0 < dist < 80.0

    # Khreshchatyk to Brovary (50.5111, 30.7900) ~ 20 km
    dist_brovary = calculate_cep_delta(50.4501, 30.5234, 50.5111, 30.7900)
    assert 18000.0 < dist_brovary < 22000.0


def test_calculate_eta_drift():
    """Verify temporal prediction error in seconds."""
    t_pred = datetime(2026, 9, 4, 19, 30, 0)
    t_actual = datetime(2026, 9, 4, 19, 28, 30)  # Arrived 90s earlier than predicted
    drift = calculate_eta_drift_sec(t_pred, t_actual)
    assert drift == 90.0

    t_late = datetime(2026, 9, 4, 19, 32, 15)  # Arrived 135s later
    drift_late = calculate_eta_drift_sec(t_pred, t_late)
    assert drift_late == -135.0


def test_system_accuracy_telemetry_aggregation():
    """Verify aggregate telemetry generator with mock DB."""
    mock_db = MagicMock()
    # Mock counts for total_events, multi_source_count, hitl_confirmed, hitl_rejected, official_verified
    mock_db.query.return_value.filter.return_value.scalar.side_effect = [
        100,  # total_events
        65,   # multi_source_count
        18,   # hitl_confirmed
        2,    # hitl_rejected
        24    # official_verified
    ]
    # Mock precision breakdown query
    mock_db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
        ("exact", 30, 150.0),
        ("settlement", 50, 2000.0),
        ("district", 20, 3500.0)
    ]

    metrics = get_system_accuracy_telemetry(mock_db, hours=72)
    assert metrics["total_events"] == 100
    assert metrics["multi_source_consensus_count"] == 65
    assert metrics["consensus_rate_pct"] == 65.0
    assert metrics["official_verified_count"] == 24
    assert metrics["hitl"]["total_reviewed"] == 20
    assert metrics["hitl"]["confirmed_analyst"] == 18
    assert metrics["hitl"]["analyst_accuracy_pct"] == 90.0
    assert "exact" in metrics["precision_breakdown"]
    assert metrics["mean_cep_radius_m"] > 0
