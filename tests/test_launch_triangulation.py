import pytest
from worker.osint.launch_triangulation import (
    haversine_km,
    calculate_bearing,
    angular_difference,
    estimate_launch_origin,
    project_forward_substation_threats,
    KNOWN_ENEMY_FACILITIES
)
from worker.osint.apt_matcher import APT_SIGNATURE_DB, analyze_threat_actors


def test_haversine_accuracy():
    # Kyiv (50.4501, 30.5234) to Boryspil (50.35, 30.95) ~34 km
    d = haversine_km(50.4501, 30.5234, 50.35, 30.95)
    assert 30.0 <= d <= 36.0
    # Zero distance
    assert haversine_km(50.0, 30.0, 50.0, 30.0) == 0.0


def test_calculate_bearing_cardinal():
    # North
    assert calculate_bearing(50.0, 30.0, 51.0, 30.0) == pytest.approx(0.0, abs=1.0)
    # South
    assert calculate_bearing(51.0, 30.0, 50.0, 30.0) == pytest.approx(180.0, abs=1.0)
    # East
    assert calculate_bearing(50.0, 30.0, 50.0, 31.0) == pytest.approx(90.0, abs=2.0)
    # West
    assert calculate_bearing(50.0, 31.0, 50.0, 30.0) == pytest.approx(270.0, abs=2.0)


def test_angular_difference():
    assert angular_difference(10.0, 20.0) == 10.0
    assert angular_difference(355.0, 5.0) == 10.0
    assert angular_difference(0.0, 180.0) == 180.0
    assert angular_difference(90.0, 270.0) == 180.0


def test_estimate_launch_origin_navlya():
    # Drone near Chernihiv (lat 51.5, lon 31.3) flying SW (heading ~220 deg)
    # Reverse bearing is ~40 deg, matching Navlya / Tsymbulovo
    origin = estimate_launch_origin(
        current_lat=51.5,
        current_lon=31.3,
        heading_deg=220.0,
        speed_kmh=185.0
    )
    assert origin is not None
    assert origin["site_id"] in ("navlya", "tsymbulovo")
    assert origin["distance_km"] > 100.0
    assert origin["flight_time_minutes"] > 30
    assert origin["confidence_score"] >= 50


def test_estimate_launch_origin_chauda():
    # Drone over Black Sea approaching Odesa from South-East (heading ~300 deg)
    # Reverse bearing is ~120 deg, matching Chauda or Primorsko-Akhtarsk
    origin = estimate_launch_origin(
        current_lat=46.0,
        current_lon=31.5,
        heading_deg=300.0,
        speed_kmh=185.0
    )
    assert origin is not None
    assert origin["site_id"] in ("chauda", "primorsko_akhtarsk", "yeysk")


def test_estimate_launch_origin_none_when_invalid():
    assert estimate_launch_origin(None, 31.0, 180.0) is None
    assert estimate_launch_origin(50.0, None, 180.0) is None
    assert estimate_launch_origin(50.0, 31.0, None) is None


def test_project_forward_substation_threats():
    # Drone flying South directly towards a substation
    substations = [
        {"name": "ПС 330 кВ Північна", "lat": 50.3, "lon": 30.5, "voltage": "330 kV"},
        {"name": "ПС 110 кВ Західна (стороння)", "lat": 50.5, "lon": 30.0, "voltage": "110 kV"}
    ]
    threats = project_forward_substation_threats(
        current_lat=50.5,
        current_lon=30.5,
        heading_deg=180.0,
        speed_kmh=180.0,
        substations=substations,
        max_cone_deg=25.0,
        max_distance_km=30.0
    )
    assert len(threats) >= 1
    assert threats[0]["name"] == "ПС 330 кВ Північна"
    assert threats[0]["eta_minutes"] > 0
    assert threats[0]["urgency"] == "IMMEDIATE"


def test_known_enemy_facilities_structure():
    assert len(KNOWN_ENEMY_FACILITIES) >= 10
    facility_ids = [f["id"] for f in KNOWN_ENEMY_FACILITIES]
    assert "navlya" in facility_ids
    assert "tsymbulovo" in facility_ids
    assert "alabuga" in facility_ids
    assert "kolomna" in facility_ids
    assert "kashan" in facility_ids
    assert "senezh" in facility_ids

    for f in KNOWN_ENEMY_FACILITIES:
        assert "lat" in f and "lon" in f
        assert "name" in f and "type" in f
        assert "threat_level" in f and "dossier" in f


def test_shahed_apt_profiles_detection():
    # Test Alabuga / Albatross detection
    text_alabuga = "Зафіксовано постачання БпЛА Герань-2 із заводу Алабуга (ТОВ Альбатрос, Флоров)."
    res_alabuga = analyze_threat_actors(text_alabuga)
    assert res_alabuga["matched"] is True
    assert any(g["group"] == "Alabuga-Albatross" for g in res_alabuga["matched_groups"])

    # Test 924th Kolomna detection
    text_kolomna = "Координація пусків ведеться через 924 ДЦ БпЛА (в/ч 20924 у Коломні)."
    res_kolomna = analyze_threat_actors(text_kolomna)
    assert res_kolomna["matched"] is True
    assert any(g["group"] == "Unit-20924-Kolomna" for g in res_kolomna["matched_groups"])

    # Test Senezh EW bypass detection
    text_senezh = "У перехопленні згадано центр Сенеж та в/ч 92154 для оновлення прошивок обходу РЕБ."
    res_senezh = analyze_threat_actors(text_senezh)
    assert res_senezh["matched"] is True
    assert any(g["group"] == "Unit-92154-Senezh" for g in res_senezh["matched_groups"])
