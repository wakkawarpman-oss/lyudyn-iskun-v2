import pytest
from worker.geo_extractors.poi_matcher import (
    find_nearby_critical_infrastructure,
    calculate_haversine_distance_m,
    match_poi
)


def test_haversine_distance_calculation():
    # Kyiv Maidan to Khreshchatyk Metro (~350m)
    dist = calculate_haversine_distance_m(50.4501, 30.5234, 50.4475, 30.5255)
    assert 250 < dist < 450


def test_find_nearby_tv_tower():
    # Exactly at Kyiv TV Tower coordinates
    matches = find_nearby_critical_infrastructure(50.4716, 30.4533, max_radius_m=1000)
    assert len(matches) >= 2
    assert matches[0].name == "Київська телевежа"
    assert matches[0].distance_m < 5.0
    assert matches[0].category == "telecom"


def test_find_nearby_substation_pivnichna():
    # Coordinates 100m from PS 330 kV Pivnichna
    matches = find_nearby_critical_infrastructure(50.5700, 30.5060, max_radius_m=1000)
    assert len(matches) >= 1
    assert "Північна" in matches[0].name
    assert matches[0].category == "substation"
    assert matches[0].distance_m < 200.0


def test_find_nearby_none_in_empty_field():
    # Coordinates in remote woods (Chornobyl zone) with no critical infrastructure within 500m
    matches = find_nearby_critical_infrastructure(51.3500, 30.0500, max_radius_m=500)
    assert len(matches) == 0


def test_poi_matcher_identifies_new_substation_alias():
    text = "Ворог вдарив ракетою по ПС 330 Північна на Київщині"
    poi = match_poi(text)
    assert poi is not None
    assert "Північна" in poi.name
    assert poi.category == "substation"
