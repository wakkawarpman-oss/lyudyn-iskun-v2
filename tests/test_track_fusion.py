import pytest
import math
from worker.track_fusion import (
    latlon_to_enu, enu_to_latlon, KalmanTrackFilter, TrackState, MeasurementRecord
)


def test_enu_coordinate_roundtrip():
    ref_lat, ref_lon = 50.4501, 30.5234
    target_lat, target_lon = 50.4800, 30.5800

    e, n = latlon_to_enu(target_lat, target_lon, ref_lat, ref_lon)
    lat_back, lon_back = enu_to_latlon(e, n, ref_lat, ref_lon)

    assert pytest.approx(target_lat, abs=1e-5) == lat_back
    assert pytest.approx(target_lon, abs=1e-5) == lon_back


def test_kalman_filter_tracking_and_sequential_update():
    kf = KalmanTrackFilter(q_accel=8.0)
    t0 = 1000.0
    state, history = kf.init_track(
        track_id="drone_01",
        lat=50.4500,
        lon=30.5200,
        t=t0,
        source_type="radar",
        initial_heading_deg=90.0,
        initial_speed_mps=50.0  # Heading East at 50 m/s (~180 km/h)
    )

    assert state.speed_mps == pytest.approx(50.0, rel=0.01)
    assert state.heading_deg == pytest.approx(90.0, rel=0.1)

    # 10 seconds later, moved East ~500m
    t1 = t0 + 10.0
    e1 = 500.0
    n1 = 0.0
    lat1, lon1 = enu_to_latlon(e1, n1, state.ref_lat, state.ref_lon)

    updated_state = kf.add_measurement(
        state, history, lat=lat1, lon=lon1, t=t1, source_type="radar", source_id="radar_main"
    )

    assert updated_state.n_updates == 2
    assert updated_state.t == t1
    assert updated_state.speed_kmh == pytest.approx(180.0, rel=0.1)
    assert updated_state.heading_deg == pytest.approx(90.0, abs=5.0)


def test_oosm_out_of_sequence_retrodiction():
    kf = KalmanTrackFilter(q_accel=8.0)
    t0 = 1000.0
    state, history = kf.init_track(
        track_id="missile_01", lat=50.40, lon=30.40, t=t0, source_type="radar"
    )

    # Sequential update at t=1020
    t2 = t0 + 20.0
    lat2, lon2 = enu_to_latlon(1000.0, 0.0, state.ref_lat, state.ref_lon)
    state = kf.add_measurement(state, history, lat=lat2, lon=lon2, t=t2, source_type="radar", source_id="r1")
    assert state.t == t2

    # Delayed out-of-sequence measurement arrives at t=1010 (500m East)
    t_delayed = t0 + 10.0
    lat_delayed, lon_delayed = enu_to_latlon(500.0, 0.0, state.ref_lat, state.ref_lon)
    state_after_oosm = kf.add_measurement(
        state, history, lat=lat_delayed, lon=lon_delayed, t=t_delayed, source_type="telegram", source_id="tg_post"
    )

    # After retrodiction, history has 3 measurements and state accurately captures intermediate motion
    assert len(history) == 3
    assert state_after_oosm.n_updates == 3
    assert state_after_oosm.speed_mps == pytest.approx(50.0, rel=0.15)


def test_eta_cone_corridor_and_uncertainty():
    kf = KalmanTrackFilter()
    t0 = 1000.0
    state, history = kf.init_track(
        track_id="drone_cone",
        lat=50.4500,
        lon=30.5200,
        t=t0,
        source_type="radar",
        initial_heading_deg=0.0,  # Moving due North
        initial_speed_mps=50.0    # 50 m/s
    )

    # Target 1: Directly North 5000m
    lat_north, lon_north = enu_to_latlon(0.0, 5000.0, state.ref_lat, state.ref_lon)
    cone_res = kf.eta_cone(state, lat_north, lon_north)

    assert cone_res is not None
    assert cone_res["is_in_corridor"] is True
    assert cone_res["dist_km"] == pytest.approx(5.0, rel=0.05)
    # 5000m at 50 m/s = ~100s
    assert cone_res["eta_sec"] == pytest.approx(100.0, rel=0.05)
    assert cone_res["eta_min_sec"] <= cone_res["eta_sec"] <= cone_res["eta_max_sec"]
    assert len(cone_res["cone_polygon"]) == 4

    # Target 2: Due West (90° away from heading) -> should NOT be in corridor
    lat_west, lon_west = enu_to_latlon(-5000.0, 0.0, state.ref_lat, state.ref_lon)
    cone_res_west = kf.eta_cone(state, lat_west, lon_west)
    assert cone_res_west is not None
    assert cone_res_west["is_in_corridor"] is False


def test_neptun_radar_integrates_kalman_eta_cone(monkeypatch):
    from worker.osint.neptun_radar import get_live_radar_threats
    import json
    from unittest.mock import MagicMock

    mock_neptun_payload = {
        "markers": [
            {
                "id": "drone_test_01",
                "lat": 50.10,
                "lng": 30.20,
                "threat_type": "Shahed",
                "course_bearing": 25.0,
                "speed_kmh": 185.0,
                "positions": [
                    {"lat": 50.00, "lng": 30.10},
                    {"lat": 50.05, "lng": 30.15},
                    {"lat": 50.10, "lng": 30.20}
                ]
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_neptun_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: mock_resp)

    res = get_live_radar_threats(force_refresh=True)
    assert res["count"] == 1
    drone = res["drones"][0]
    assert drone["id"] == "drone_test_01"
    assert "eta_cone" in drone
    assert drone["eta_cone"] is not None
    assert "cone_polygon" in drone["eta_cone"]
    assert "speed_kmh" in drone
