"""
Unit & Integration Tests for Practical Innovations:
1. Physics-Informed EKF Kinematic Box-Constraints (a_lat <= 2.5g, speed clamps).
2. Weather-Compensated Acoustic TDoA (c(T) calculation, propagation delay).
3. Explainable AI (XAI) Attribution Breakdown (log-odds delta, human-readable explanations).
4. Anti-Hallucination & Anti-PSYOP Deterministic Guardrails (burst detection, coordinate bounds).
"""
import pytest
import math
import numpy as np

from worker.track_fusion_v2 import KalmanTrackFilterV2, AeroLimits
from worker.track_fusion import KalmanTrackFilter, get_aero_profile
from worker.osint.acoustic_gateway import (
    calculate_speed_of_sound,
    calculate_tdoa_propagation_time_sec,
    corroborate_drone_with_acoustics,
    record_acoustic_hit
)
from worker.scoring_bayesian import explain_threat_assessment
from worker.verification.psyop_detector import (
    PsyopBurstDetector,
    validate_osint_event_truthfulness,
    UKRAINE_GEO_BOUNDS
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Physics-Informed Kinematic Clamping Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_kalman_v2_kinematic_clamping_turn_rate():
    kf_v2 = KalmanTrackFilterV2(threat_type="SHAHED_136")
    
    # Drone flying North at 50 m/s: vx = 0, vy = 50 (heading = 90 deg)
    vx_curr = 0.0
    vy_curr = 50.0
    
    # Sudden noisy measurement attempting a 90-degree instant East turn: target vx = 50, vy = 0 (heading = 0 deg)
    dt = 1.0  # 1 second interval
    new_vx, new_vy, info = kf_v2.clamp_kinematics(
        current_vx=vx_curr,
        current_vy=vy_curr,
        dt_sec=dt,
        target_vx=50.0,
        target_vy=0.0
    )
    
    # With a_max = 2.5g = 24.525 m/s^2 and v = 50 m/s:
    # omega_max = 24.525 / 50 = 0.4905 rad/s = ~28.1 deg/s
    assert info["clamped_turn"] is True
    assert info["max_d_heading_deg"] < 35.0
    # Turn should be bounded, not the full 90 degrees
    heading_diff = abs(info["heading_deg"] - 90.0)
    assert heading_diff <= info["max_d_heading_deg"] + 0.1
    # Speed remains within limits
    assert 33.0 <= info["v_ms"] <= 75.0


def test_kalman_filter_update_applies_kinematic_limits():
    kf = KalmanTrackFilter(dt=1.0, threat_type="GERAN_2")
    # Initialize track moving East: state [0, 0, 50, 0]
    kf.kf.x[0, 0] = 0.0
    kf.kf.x[1, 0] = 0.0
    kf.kf.x[2, 0] = 50.0
    kf.kf.x[3, 0] = 0.0
    
    # Severe jump: measurement far to the North (y = 500, x = 50)
    z_noisy = np.array([[50.0], [500.0]])
    kf.update(z_noisy)
    
    state = kf.state
    # Speed must be physically bounded to Geran-2 limits
    assert state["v_ms"] <= kf.aero.v_dive_ms
    assert state["v_ms"] >= kf.aero.v_stall_ms
    # Flag must record aero clamping occurred
    assert state["aero_clamped"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. Weather-Compensated Acoustic TDoA Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_speed_of_sound_weather_compensation():
    # Cold winter: -15 deg C
    c_winter = calculate_speed_of_sound(temp_celsius=-15.0)
    # Hot summer: +35 deg C
    c_summer = calculate_speed_of_sound(temp_celsius=35.0)
    # Standard: +15 deg C
    c_standard = calculate_speed_of_sound(temp_celsius=15.0)
    
    assert 320.0 < c_winter < 325.0
    assert 350.0 < c_summer < 355.0
    assert 338.0 < c_standard < 342.0
    
    # 10 km propagation delay check
    delay_winter = calculate_tdoa_propagation_time_sec(10.0, temp_celsius=-15.0)
    delay_summer = calculate_tdoa_propagation_time_sec(10.0, temp_celsius=35.0)
    
    # In winter sound takes longer to travel 10 km
    assert delay_winter > delay_summer
    # Difference over 10 km is ~2.5 seconds (significant for TDoA)
    assert abs(delay_winter - delay_summer) > 2.0


def test_corroborate_acoustics_with_temperature():
    record_acoustic_hit(lat=48.5, lng=35.0, sensor_id="mic_01", source="Sky Fortress", confidence=90)
    res = corroborate_drone_with_acoustics(drone_lat=48.51, drone_lng=35.01, max_radius_km=10.0, temp_celsius=-5.0)
    
    assert res["corroborated"] is True
    assert res["sensor_count"] >= 1
    sensor = res["sensors"][0]
    assert "tdoa_delay_sec" in sensor
    assert "speed_of_sound_ms" in sensor
    assert sensor["speed_of_sound_ms"] < 335.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Explainable AI (XAI) Attribution Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_xai_threat_attribution_breakdown():
    # Sensor data: Acoustic hit 10s ago, Radar hit 15s ago, Sigint missing, OSINT missing
    sensor_data = {
        "ACOUSTIC": 5.0,
        "RADAR": 5.0,
        "OSINT": 10.0,
        "SIGINT": None
    }
    
    explanation = explain_threat_assessment(sensor_data=sensor_data, altitude_m=120.0, in_river_canyon=False)
    
    assert explanation["threat_probability"] > 0.80
    assert explanation["threat_level"] in ["HIGH", "CRITICAL"]
    assert "factors" in explanation
    assert len(explanation["factors"]) == 4
    
    # Check that sum of attribution percentages is approximately 100%
    total_pct = sum(f["impact_percent"] for f in explanation["factors"])
    assert 99.0 <= total_pct <= 101.0
    
    # Acoustic and Radar should have positive log-odds delta
    acoustic_factor = next(f for f in explanation["factors"] if f["factor_name"] == "ACOUSTIC")
    assert acoustic_factor["log_odds_delta"] > 0.0
    assert "Підтверджено" in acoustic_factor["description"]


def test_xai_terrain_masking_attribution():
    # Flying low in canyon (MNAR): Radar missing should NOT be penalized
    sensor_data = {
        "ACOUSTIC": 5.0,
        "RADAR": None,
        "SIGINT": None
    }
    explanation = explain_threat_assessment(sensor_data=sensor_data, altitude_m=50.0, in_river_canyon=True)
    
    radar_factor = next(f for f in explanation["factors"] if f["factor_name"] == "RADAR")
    # In canyon with MNAR, delta log-odds should be 0.0 (no penalty)
    assert radar_factor["log_odds_delta"] == 0.0
    assert "Маскування рельєфом" in radar_factor["description"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Anti-Hallucination & Anti-PSYOP Guardrails Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_psyop_burst_detection():
    detector = PsyopBurstDetector(window_sec=60.0, max_burst=4)
    channel = "@fake_air_alert_bot"
    
    # 3 messages in quick succession: under threshold
    for _ in range(3):
        is_burst, count, score = detector.record_channel_message(channel)
    assert is_burst is False
    assert count == 3
    
    # 4th message: triggers burst limit
    is_burst, count, score = detector.record_channel_message(channel)
    assert is_burst is True
    assert count == 4
    assert score >= 0.60


def test_validate_osint_event_coordinates_out_of_bounds():
    # Coordinates in Pacific Ocean (hallucination / invalid)
    res = validate_osint_event_truthfulness(
        lat=0.0,
        lon=-150.0,
        text_content="Пуски Шахедів над морем",
        channel_id="@source_1"
    )
    assert res["is_valid"] is False
    assert "COORDINATES_OUT_OF_UKRAINE_BOUNDS" in res["validation_flags"]


def test_validate_osint_event_with_grounded_unit_and_panic():
    det = PsyopBurstDetector()
    # Message mentioning real unit from registry (в/ч 20924 924-й ДЦ БпЛА)
    res = validate_osint_event_truthfulness(
        lat=48.5,
        lon=35.0,
        text_content="Екіпаж в/ч 20924 здійснює наведення БпЛА",
        channel_id="@legit_channel",
        detector=det
    )
    assert res["grounded_unit"] == "в/ч 20924"
    assert "GROUNDED_UNIT_в/ч 20924" in res["validation_flags"]
    assert res["is_valid"] is True
