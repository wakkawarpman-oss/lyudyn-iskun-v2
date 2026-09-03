"""Deterministic threat-vector extraction — pure functions, no mocking
needed. See worker/geo_extractors/vector_extractor.py's module docstring
for why this isn't a Kalman filter (data association isn't solved)."""
from worker.geo_extractors.vector_extractor import (
    calculate_bearing,
    detect_weapon,
    extract_threat_vector,
    find_nearest_kyiv_district,
    project_point,
)


def test_calculate_bearing_known_directions():
    # Due north and due east from the same starting point.
    assert calculate_bearing(50.0, 30.0, 51.0, 30.0) == 0.0
    east_bearing = calculate_bearing(50.0, 30.0, 50.0, 31.0)
    assert 85 < east_bearing < 95  # not exactly 90 off the equator, but close


def test_detect_weapon_speed():
    assert detect_weapon("Шахеди курсом на Київ")[0].startswith("БпЛА")
    label, speed = detect_weapon("Ракета Х-101 повз Обухів")
    assert label == "Крилата ракета" and speed == 800.0
    label, speed = detect_weapon("Іскандер-М пуск")
    assert "Балістика" in label and speed == 3000.0
    # Unrecognized weapon still gets a (conservative) default, not a crash.
    label, speed = detect_weapon("щось невідоме курсом на Київ")
    assert speed == 170.0


def test_extract_threat_vector_real_example_from_proposal():
    result = extract_threat_vector("Шахеди повз Обухів у напрямку Києва (Голосіївський район)")
    assert result is not None
    assert result.origin_name == "Обухів"
    assert "Київ" in result.destination_name
    assert 0 <= result.bearing_deg <= 360
    assert result.distance_km > 0
    assert result.eta_minutes > 0
    assert result.weapon_label.startswith("БпЛА")


def test_extract_threat_vector_returns_none_without_named_origin():
    """"з півдня області" is a direction, not a place — resolve_canonical_toponym
    can't find coordinates for it, so this must decline rather than guess."""
    result = extract_threat_vector("Шахеди з півдня області курсом на Обухів/Васильків")
    assert result is None


def test_extract_threat_vector_returns_none_for_unrelated_text():
    assert extract_threat_vector("Гарна погода сьогодні в Києві") is None
    assert extract_threat_vector("") is None
    assert extract_threat_vector(None) is None


def test_extract_threat_vector_accepts_generic_kyiv_destination():
    """"курсом на Київ" (the whole city, not a specific district) is
    is_fallback_geo=True in resolve_canonical_toponym (too vague to pin an
    INCIDENT to), but is still a perfectly meaningful vector destination —
    the extractor must not require district-level precision to produce a
    result."""
    result = extract_threat_vector("з Бровари курсом на Київ")
    assert result is not None
    assert result.destination_name == "Київ"


def test_project_point_and_find_nearest_district():
    # Project from Brovary towards Kyiv center and confirm we land near a
    # real Kyiv district somewhere along that path.
    from worker.canonical_geo import CANONICAL_TOPONYMS

    brovary = CANONICAL_TOPONYMS["бровар"]
    kyiv = CANONICAL_TOPONYMS["київ"]
    bearing = calculate_bearing(brovary["lat"], brovary["lon"], kyiv["lat"], kyiv["lon"])

    found_district = False
    for extra_km in range(0, 25, 2):
        proj_lat, proj_lon = project_point(brovary["lat"], brovary["lon"], bearing, extra_km)
        if find_nearest_kyiv_district(proj_lat, proj_lon, max_km=6.0):
            found_district = True
            break
    assert found_district, "projecting from Brovary towards Kyiv should pass near a real district"
