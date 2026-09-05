"""
Test suite for updated P1 Core (Multi-INT Data Fusion Engine):
1. worker/track_fusion_v2.py (KalmanTrackFilterV2, AeroLimits, q_eff(v), ETA Cone)
2. worker/scoring_bayesian.py (SENSOR_CONFIG, calculate_decayed_lr, MNAR fusion)
3. worker/osint/terrain_los.py (TerrainMaskingEngine 0.001 deg grid)
4. Celery Worker Pipeline P1 Integration
"""
import math
import pytest
from unittest.mock import MagicMock, patch

from worker.track_fusion_v2 import KalmanTrackFilterV2, AeroLimits, AERO_DB
from worker.scoring_bayesian import (
    SENSOR_CONFIG,
    calculate_decayed_lr,
    fuse_multi_domain_evidence
)
from worker.osint.terrain_los import TerrainMaskingEngine


# ─────────────────────────────────────────────────────────────────────────────
# 1. Kinematics & ETA (KalmanTrackFilterV2)
# ─────────────────────────────────────────────────────────────────────────────

def test_aero_limits_database():
    assert "SHAHED_136" in AERO_DB
    assert "GERAN_2" in AERO_DB
    assert "ORLAN_10" in AERO_DB

    shahed = AERO_DB["SHAHED_136"]
    assert shahed.v_stall_ms == 33.0
    assert shahed.v_dive_ms == 75.0
    assert shahed.q_base == 5.0
    assert shahed.q_max == 35.0
    assert shahed.beta == 0.8
    assert shahed.v_ref == 50.0

    geran = AERO_DB["GERAN_2"]
    assert geran.q_max == 40.0
    assert geran.beta == 0.9


def test_calculate_q_eff_quadratic_model():
    kf = KalmanTrackFilterV2(threat_type="SHAHED_136")

    # At v = 50 m/s (v_ref): q = 5.0 * (1.0 + 0.8 * (50/50)^2) = 5.0 * 1.8 = 9.0
    q_50 = kf.calculate_q_eff(50.0)
    assert q_50 == pytest.approx(9.0, abs=0.01)

    # Clamping at stall: v = 10 m/s -> clamped to 33.0 m/s
    q_stall = kf.calculate_q_eff(10.0)
    q_33 = 5.0 * (1.0 + 0.8 * (33.0 / 50.0)**2)
    assert q_stall == pytest.approx(q_33, abs=0.01)

    # Clamping at dive: v = 120 m/s -> clamped to 75.0 m/s
    q_dive = kf.calculate_q_eff(120.0)
    q_75 = min(35.0, 5.0 * (1.0 + 0.8 * (75.0 / 50.0)**2))
    assert q_dive == pytest.approx(q_75, abs=0.01)


def test_estimate_eta_cone_polygon():
    kf = KalmanTrackFilterV2(threat_type="GERAN_2")
    state_x, state_y = 50000.0, 60000.0
    heading = 90.0  # East
    v_ms = 50.0
    horizon_sec = 600  # 10 minutes

    res = kf.estimate_eta_cone(state_x, state_y, heading, v_ms, horizon_sec)

    assert "dist_min_m" in res
    assert "dist_max_m" in res
    assert "theta_cone_deg" in res
    assert "eta_polygon" in res

    # dist_min = 33.0 * 600 = 19,800 m
    # dist_max = 75.0 * 600 = 45,000 m
    assert res["dist_min_m"] == 19800.0
    assert res["dist_max_m"] == 45000.0
    assert 3.0 <= res["theta_cone_deg"] <= 45.0
    assert len(res["eta_polygon"]) >= 8


# ─────────────────────────────────────────────────────────────────────────────
# 2. BBN Temporal Decay & MNAR
# ─────────────────────────────────────────────────────────────────────────────

def test_sensor_config_parameters():
    assert "RADAR" in SENSOR_CONFIG
    assert "ACOUSTIC" in SENSOR_CONFIG
    assert "SIGINT" in SENSOR_CONFIG
    assert "OSINT" in SENSOR_CONFIG

    lr_hit, lr_miss, tau = SENSOR_CONFIG["RADAR"]
    assert lr_hit == 15.0
    assert lr_miss == 0.2
    assert tau == 90.0


def test_calculate_decayed_lr_hit_and_miss():
    # Hit at dt = 0
    lr_hit_0 = calculate_decayed_lr("RADAR", 0.0, is_hit=True)
    assert lr_hit_0 == pytest.approx(15.0, abs=0.01)

    # Miss at dt = 0
    lr_miss_0 = calculate_decayed_lr("RADAR", 0.0, is_hit=False)
    assert lr_miss_0 == pytest.approx(0.2, abs=0.01)

    # Decay towards neutral 1.0 as dt -> inf
    lr_hit_inf = calculate_decayed_lr("RADAR", 100000.0, is_hit=True)
    assert lr_hit_inf == pytest.approx(1.0, abs=0.01)


def test_fuse_multi_domain_evidence_mnar_in_canyon():
    # Shahed flying at 50m in Dnipro River Canyon
    # RADAR and SIGINT missed (None), ACOUSTIC heard 10s ago, OSINT heard 30s ago
    sensor_data = {
        "RADAR": None,
        "SIGINT": None,
        "ACOUSTIC": 10.0,
        "OSINT": 30.0,
    }

    # In river canyon + altitude 50m (<80m) -> MNAR active
    p_masked = fuse_multi_domain_evidence(sensor_data, altitude_m=50.0, in_river_canyon=True)

    # In open plain + altitude 150m (>=80m) -> Normal penalty applied for missing radar/sigint
    p_unmasked = fuse_multi_domain_evidence(sensor_data, altitude_m=150.0, in_river_canyon=False)

    # MNAR preserves high confidence because missing radar in canyon is expected!
    assert p_masked > 0.50
    assert p_masked > p_unmasked


# ─────────────────────────────────────────────────────────────────────────────
# 3. Terrain & Radio Horizon (TerrainMaskingEngine 0.001°)
# ─────────────────────────────────────────────────────────────────────────────

def test_terrain_masking_engine_grid_key():
    engine = TerrainMaskingEngine()
    key = engine._generate_grid_key(47.8327, 35.1371)
    assert key == "tactical:cache:river_mask:47.833_35.137"


def test_terrain_masking_engine_redis_caching():
    mock_redis = MagicMock()
    mock_redis.get.return_value = "1"

    engine = TerrainMaskingEngine()
    with patch.object(engine, "r", mock_redis):
        is_canyon = engine.is_in_river_canyon(48.460, 35.040)
        assert is_canyon is True
        mock_redis.get.assert_called_once_with("tactical:cache:river_mask:48.460_35.040")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pipeline P1 End-to-End Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def test_pipeline_p1_end_to_end_flow():
    # 1. Ingestion: lat, lon, v, h
    lat, lon = 48.460, 35.040
    v_ms = 55.0
    h_m = 45.0  # 45m low-altitude terrain hugging flight

    # 2. Task 3 (Terrain): check river canyon
    engine = TerrainMaskingEngine()
    # Mock fallback to confirm Dnipro corridor
    with patch.object(engine, "_calculate_los_from_dem", return_value=True):
        in_canyon = engine.is_in_river_canyon(lat, lon)
        assert in_canyon is True

    # 3. Task 2 (BBN): Multi-domain fusion with MNAR
    sensor_reports = {
        "RADAR": None,      # Dropped below radar horizon in canyon
        "SIGINT": None,     # Kometa-M CRPA antenna immune
        "ACOUSTIC": 5.0,    # Detected by Sky Fortress microphone 5s ago
        "OSINT": 60.0,      # Tactical channel mention 60s ago
    }
    threat_prob = fuse_multi_domain_evidence(sensor_reports, altitude_m=h_m, in_river_canyon=in_canyon)
    assert threat_prob > 0.50

    # 4. Task 1 (Kalman): ETA cone & dynamic q_eff
    kf = KalmanTrackFilterV2(threat_type="GERAN_2")
    q_eff = kf.calculate_q_eff(v_ms)
    assert q_eff > 5.0

    cone = kf.estimate_eta_cone(lat, lon, heading=90.0, v_ms=v_ms, time_horizon_sec=900)
    assert cone["dist_min_m"] == pytest.approx(33.0 * 900, rel=0.01)
    assert cone["dist_max_m"] == pytest.approx(75.0 * 900, rel=0.01)
    assert len(cone["eta_polygon"]) >= 8
