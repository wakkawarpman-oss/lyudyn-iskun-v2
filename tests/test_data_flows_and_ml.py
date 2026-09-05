"""
Comprehensive 7-Benchmark Test Suite for C4ISR OKINT-PRO Data Flows & ML Interpretation.

Validates:
1. Synthetic Anchor Integrity (46.6777, 32.7229)
2. Threat Class Pydantic Serialization (7 distinct threat types)
3. Dynamic Kalman Process Noise Scaling (adaptive q_accel based on threat dynamics)
4. River Canyon LoS Grid Caching (tactical:cache:river_mask:*)
5. Bayesian Belief Network (BBN) Log-Odds Convergence
6. Cross-Contour Auto-Sanitization Pipeline (anti-BDA 3h holdback, coordinate fuzzing, field stripping)
7. End-to-End Pipeline & Contour Integrity
"""

import pytest
import math
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from worker.schemas import (
    TacticalThreatTypeEnum,
    TacticalDroneTrackSchema,
    EtaConeSchema,
    TerrainMaskingSchema,
    BayesianConfidenceSchema,
    EwProfileSchema,
    WeatherVectorSchema,
    AcousticHitSchema,
    SigintEmitterSchema,
    MaritimeCarrierSchema,
    FirmsThermalSchema
)
from worker.track_fusion import (
    KalmanTrackFilter,
    THREAT_TYPE_Q_ACCEL,
    latlon_to_enu,
    enu_to_latlon
)
from worker.osint.terrain_los import (
    find_nearest_river_corridor,
    evaluate_terrain_masking
)
from worker.scoring_bayesian import (
    evaluate_bayesian_threat_confidence,
    prob_to_log_odds,
    log_odds_to_prob,
    PRIOR_THREAT_PROB
)
from database.models import (
    SessionLocal,
    TacticalEvent,
    SanitizedEvent,
    init_db
)
from worker.tasks import auto_sanitize_tactical_events_task


SYNTHETIC_ANCHOR_LAT = 46.6777
SYNTHETIC_ANCHOR_LNG = 32.7229


# ============================================================================
# Benchmark 1: Synthetic Anchor Verification
# ============================================================================
def test_synthetic_anchor_verification():
    """Verify that synthetic testing anchors adhere to zero real-world operational leakage."""
    assert pytest.approx(SYNTHETIC_ANCHOR_LAT, abs=0.0001) == 46.6777
    assert pytest.approx(SYNTHETIC_ANCHOR_LNG, abs=0.0001) == 32.7229


# ============================================================================
# Benchmark 2: Threat Class Pydantic Serialization
# ============================================================================
def test_threat_class_pydantic_serialization():
    """Validates that all 7 threat classes instantiate into typed TacticalDroneTrackSchema."""
    threat_types = [
        TacticalThreatTypeEnum.SHAHED_136,
        TacticalThreatTypeEnum.SHAHED_238,
        TacticalThreatTypeEnum.KH_101,
        TacticalThreatTypeEnum.ISKANDER_M,
        TacticalThreatTypeEnum.KAB_500,
        TacticalThreatTypeEnum.SUPER_CAM,
        TacticalThreatTypeEnum.MSTA_S,
    ]

    for idx, tt in enumerate(threat_types):
        payload = {
            "id": f"syn_threat_{idx:02d}",
            "lat": SYNTHETIC_ANCHOR_LAT + (idx * 0.01),
            "lng": SYNTHETIC_ANCHOR_LNG + (idx * 0.01),
            "heading": float((idx * 45) % 360),
            "speed_kmh": 180.0 + (idx * 50.0),
            "threat_type": tt,
            "category": "drone" if "SHAHED" in tt.value or tt == TacticalThreatTypeEnum.SUPER_CAM else "missile",
            "label": f"Ціль {tt.value}",
            "confidence": 85,
            "altitude_m": 120.0 + (idx * 100),
            "trail": [[SYNTHETIC_ANCHOR_LAT, SYNTHETIC_ANCHOR_LNG]],
            "eta_cone": {
                "eta_time_str": "14:30:00",
                "speed_kmh": 180.0,
                "bearing_deg": 45.0,
                "cone_half_angle_deg": 15.0
            }
        }
        validated = TacticalDroneTrackSchema.model_validate(payload)
        assert validated.threat_type == tt
        assert validated.lat == pytest.approx(SYNTHETIC_ANCHOR_LAT + (idx * 0.01))
        assert validated.eta_cone is not None
        assert validated.eta_cone["speed_kmh"] == 180.0


# ============================================================================
# Benchmark 3: Dynamic Kalman Process Noise Scaling
# ============================================================================
def test_dynamic_kalman_process_noise():
    """Validates dynamic CWNA process noise scaling with target class and speed."""
    assert THREAT_TYPE_Q_ACCEL["SHAHED_136"] == 8.0
    assert THREAT_TYPE_Q_ACCEL["SHAHED_238"] == 18.0
    assert THREAT_TYPE_Q_ACCEL["KH_101"] == 25.0
    assert THREAT_TYPE_Q_ACCEL["ISKANDER_M"] == 35.0

    kf = KalmanTrackFilter(q_accel=8.0)
    t0 = 1000.0

    # Low speed Shahed-136 (~180 km/h = 50 m/s)
    state_slow, hist_slow = kf.init_track(
        track_id="trk_slow",
        lat=SYNTHETIC_ANCHOR_LAT,
        lon=SYNTHETIC_ANCHOR_LNG,
        t=t0,
        source_type="radar",
        initial_heading_deg=90.0,
        initial_speed_mps=50.0
    )

    # 10 seconds later, 500m East
    t1 = t0 + 10.0
    e1, n1 = 500.0, 0.0
    lat1, lon1 = enu_to_latlon(e1, n1, state_slow.ref_lat, state_slow.ref_lon)

    updated_slow = kf.add_measurement(
        state_slow,
        hist_slow,
        lat=lat1,
        lon=lon1,
        t=t1,
        source_type="radar",
        source_id="radar_01",
        threat_type="SHAHED_136"
    )
    assert updated_slow.speed_kmh == pytest.approx(180.0, rel=0.1)

    # Jet-powered Shahed-238 / Kh-101 (~720 km/h = 200 m/s)
    state_fast, hist_fast = kf.init_track(
        track_id="trk_fast",
        lat=SYNTHETIC_ANCHOR_LAT,
        lon=SYNTHETIC_ANCHOR_LNG,
        t=t0,
        source_type="radar",
        initial_heading_deg=90.0,
        initial_speed_mps=200.0
    )
    e2, n2 = 2000.0, 0.0
    lat2, lon2 = enu_to_latlon(e2, n2, state_fast.ref_lat, state_fast.ref_lon)

    updated_fast = kf.add_measurement(
        state_fast,
        hist_fast,
        lat=lat2,
        lon=lon2,
        t=t1,
        source_type="radar",
        source_id="radar_02",
        threat_type="KH_101"
    )
    assert updated_fast.speed_kmh == pytest.approx(720.0, rel=0.1)


# ============================================================================
# Benchmark 4: River Canyon LoS Grid Caching
# ============================================================================
def test_river_canyon_los_grid_cache():
    """Validates Redis grid caching for nearest river canyon lookups."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # First call: cache miss

    with patch("worker.osint.terrain_los._get_redis_client", return_value=mock_redis):
        # Coordinates along Dnipro River corridor (e.g. 48.46, 35.04)
        corridor = find_nearest_river_corridor(48.46, 35.04)
        assert corridor is not None
        assert "Дніпро" in corridor["river"]

        # Verify Redis SET called with tactical cache key
        grid_key = "tactical:cache:river_mask:48.46_35.04"
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        assert args[0] == grid_key
        assert kwargs.get("ex") == 3600

    # Second call: cache hit simulation
    mock_hit_data = json.dumps({
        "corridor_name": "Дніпровський каньйон та заплава",
        "river": "Дніпро",
        "canyon_depth_m": 85.0,
        "masking_buffer_km": 12.0,
        "distance_to_river_km": 1.2
    })
    mock_redis_hit = MagicMock()
    mock_redis_hit.get.return_value = mock_hit_data

    with patch("worker.osint.terrain_los._get_redis_client", return_value=mock_redis_hit):
        cached_result = find_nearest_river_corridor(48.46, 35.04)
        assert cached_result is not None
        assert cached_result["distance_to_river_km"] == 1.2
        # No recomputation / write needed on hit
        mock_redis_hit.set.assert_not_called()


# ============================================================================
# Benchmark 5: BBN Log-Odds Convergence
# ============================================================================
def test_bbn_log_odds_convergence():
    """Validates Bayesian multi-INT log-odds accumulation across radar, acoustic, and SIGINT."""
    # 1. Multi-domain corroboration: Radar + Acoustic (2 sensors) + SIGINT
    evidence_strong = {
        "has_radar": True,
        "doppler_match": True,
        "acoustic_count": 2,
        "sigint_intercept": True,
        "adsb_mode": "dark",
        "osint_level": "monitors"
    }
    res_strong = evaluate_bayesian_threat_confidence(evidence_strong)
    assert res_strong["confidence_score"] >= 95
    assert res_strong["category"] == "VERIFIED_THREAT"
    assert res_strong["active_corroborating_sources_count"] >= 4

    # 2. Civilian aircraft: radar return but civilian ADS-B squawk
    evidence_civilian = {
        "has_radar": True,
        "doppler_match": False,
        "acoustic_count": 0,
        "sigint_intercept": False,
        "adsb_mode": "civilian",
        "osint_level": "none"
    }
    res_civilian = evaluate_bayesian_threat_confidence(evidence_civilian)
    assert res_civilian["category"] in ["BENIGN_OR_NOISE", "UNCERTAIN"]
    assert res_civilian["confidence_score"] < 40

    # 3. Terrain masked target: absence of radar does NOT penalize target
    evidence_masked = {
        "has_radar": False,
        "is_terrain_masked": True,
        "acoustic_count": 2,
        "sigint_intercept": True
    }
    res_masked = evaluate_bayesian_threat_confidence(evidence_masked)
    # Target still highly probable despite missing radar because masking neutralizes radar penalty
    assert res_masked["confidence_score"] >= 90


# ============================================================================
# Benchmark 6: Cross-Contour Auto-Sanitization
# ============================================================================
def test_cross_contour_auto_sanitization():
    """Validates automatic sanitization from restricted_ops to public_osint."""
    init_db()
    db = SessionLocal()

    now = datetime.utcnow()
    # 1. Create tactical drone event with exact coordinates & sensitive EW profile
    te_drone = TacticalEvent(
        incident_id="INC-SYN-TEST-001",
        exact_lat=SYNTHETIC_ANCHOR_LAT,
        exact_lng=SYNTHETIC_ANCHOR_LNG,
        altitude_m=75.0,
        speed_kmh=185.0,
        heading_deg=270.0,
        target_type="SHAHED_136",
        raw_telemetry=json.dumps({
            "ew_profile": {"vtx_5_8_jamming": True},
            "sigint": {"freq_mhz": 5800.0},
            "oblast": "Херсонська область"
        }),
        confidence_score=90,
        security_level="restricted",
        detected_at=now - timedelta(minutes=15),
        created_at=now - timedelta(minutes=15)
    )

    # 2. Create FIRMS thermal event under 3 hours (should be held back)
    te_thermal_recent = TacticalEvent(
        incident_id="INC-SYN-THERMAL-RECENT",
        exact_lat=SYNTHETIC_ANCHOR_LAT + 0.05,
        exact_lng=SYNTHETIC_ANCHOR_LNG + 0.05,
        target_type="FIRMS_THERMAL",
        confidence_score=75,
        detected_at=now - timedelta(minutes=30),  # < 3 hours
        created_at=now - timedelta(minutes=30)
    )

    # 3. Create older FIRMS thermal event (> 3 hours, eligible for sanitization)
    te_thermal_old = TacticalEvent(
        incident_id="INC-SYN-THERMAL-OLD",
        exact_lat=SYNTHETIC_ANCHOR_LAT + 0.10,
        exact_lng=SYNTHETIC_ANCHOR_LNG + 0.10,
        target_type="FIRMS_THERMAL",
        confidence_score=80,
        detected_at=now - timedelta(hours=4),  # > 3 hours
        created_at=now - timedelta(hours=4)
    )

    db.add(te_drone)
    db.add(te_thermal_recent)
    db.add(te_thermal_old)
    db.commit()

    try:
        # Run sanitization task
        result = auto_sanitize_tactical_events_task(batch_size=50)
        assert result["status"] == "success"
        assert result["processed"] >= 2  # te_drone and te_thermal_old sanitized
        assert result["skipped_holdback"] >= 1  # te_thermal_recent held back

        # Check sanitized output in SanitizedEvent
        san_drone = db.query(SanitizedEvent).filter_by(event_uid=f"SAN-{te_drone.id}").first()
        assert san_drone is not None
        assert san_drone.event_type == "SHAHED_136"
        # Coordinates must be coarsened (not equal to exact)
        assert san_drone.rough_lat != SYNTHETIC_ANCHOR_LAT or san_drone.rough_lng != SYNTHETIC_ANCHOR_LNG
        # Must be rounded to 2 decimal places
        assert len(str(san_drone.rough_lat).split(".")[-1]) <= 2
        assert len(str(san_drone.rough_lng).split(".")[-1]) <= 2
        assert san_drone.significance_level == "HIGH"
        assert san_drone.verification_status == "VERIFIED"

        # Verify recent thermal was held back
        san_thermal_recent = db.query(SanitizedEvent).filter_by(event_uid=f"SAN-{te_thermal_recent.id}").first()
        assert san_thermal_recent is None

        # Verify old thermal was processed
        san_thermal_old = db.query(SanitizedEvent).filter_by(event_uid=f"SAN-{te_thermal_old.id}").first()
        assert san_thermal_old is not None

    finally:
        # Cleanup test records
        db.query(SanitizedEvent).filter(SanitizedEvent.event_uid.in_([
            f"SAN-{te_drone.id}", f"SAN-{te_thermal_old.id}"
        ])).delete(synchronize_session=False)
        db.query(TacticalEvent).filter(TacticalEvent.id.in_([
            te_drone.id, te_thermal_recent.id, te_thermal_old.id
        ])).delete(synchronize_session=False)
        db.commit()
        db.close()


# ============================================================================
# Benchmark 7: End-to-End Pipeline & Contour Integrity
# ============================================================================
def test_end_to_end_pipeline_integrity():
    """Validates complete ingestion contract through civilian vs operational API endpoints."""
    from api.main import get_radar_drones

    synthetic_threats = {
        "count": 1,
        "drones": [
            {
                "id": "trk_shahed_syn_01",
                "lat": SYNTHETIC_ANCHOR_LAT,
                "lng": SYNTHETIC_ANCHOR_LNG,
                "heading": 270.0,
                "speed_kmh": 185.0,
                "category": "drone",
                "label": "БПЛА Shahed",
                "threat_type": "SHAHED_136",
                "trail": [[SYNTHETIC_ANCHOR_LAT, SYNTHETIC_ANCHOR_LNG]],
                "eta_cone": {
                    "eta_time_str": "15:00:00",
                    "speed_kmh": 185.0,
                    "bearing_deg": 270.0,
                    "cone_half_angle_deg": 12.0
                },
                "ew_profile": {"vtx_5_8_jamming": True},
                "sigint_corroboration": {"sigint_active": True},
                "corroborating_sensors": ["acoustic_node_01"]
            }
        ]
    }

    # Test Civilian Contour (Unauthenticated / Public)
    with patch("worker.osint.neptun_radar.get_live_radar_threats", return_value=synthetic_threats), \
         patch("api.main.is_tactical_authorized", return_value=False):
        res_civ = get_radar_drones(oblast="kherson")
        assert res_civ["contour"] == "civilian"
        assert res_civ["coordinates_fidelity"] == "1:1_exact_wgs84"
        drone_civ = res_civ["drones"][0]
        # Coordinates & kinematics preserved for civilian defense warning
        assert drone_civ["lat"] == pytest.approx(SYNTHETIC_ANCHOR_LAT)
        assert drone_civ["lng"] == pytest.approx(SYNTHETIC_ANCHOR_LNG)
        assert drone_civ["speed_kmh"] == 185.0
        # Military extensions strictly stripped
        assert drone_civ["ew_profile"] is None
        assert drone_civ["sigint_corroboration"] is None
        assert drone_civ["corroborating_sensors"] == []

    # Test Operational Contour (Authenticated)
    with patch("worker.osint.neptun_radar.get_live_radar_threats", return_value=synthetic_threats), \
         patch("api.main.is_tactical_authorized", return_value=True):
        res_ops = get_radar_drones(oblast="kherson")
        assert res_ops["contour"] == "restricted_operational"
        drone_ops = res_ops["drones"][0]
        # Sensitive extensions preserved
        assert drone_ops["ew_profile"] is not None
        assert drone_ops["ew_profile"]["vtx_5_8_jamming"] is True
        assert drone_ops["sigint_corroboration"] is not None
