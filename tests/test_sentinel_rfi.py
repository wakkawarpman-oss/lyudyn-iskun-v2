from worker.sensors.sentinel_rfi import get_live_ew_interference, find_nearby_ew_activity


def test_get_live_ew_interference():
    data = get_live_ew_interference()
    assert data["status"] == "online"
    assert data["sensor"] == "Sentinel-1 C-SAR (5.405 GHz)"
    assert data["count"] >= 6
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == data["count"]

    feat = data["features"][0]
    assert "geometry" in feat
    assert "properties" in feat
    assert feat["geometry"]["type"] == "Point"
    assert "freq_ghz" in feat["properties"]
    assert feat["properties"]["freq_ghz"] == 5.405
    assert "beam_line" in feat["properties"]


def test_find_nearby_ew_activity():
    # Kyiv North position (51.1245, 30.2814)
    matches = find_nearby_ew_activity(51.1200, 30.2800, max_dist_km=15)
    assert len(matches) >= 1
    assert matches[0]["id"] == "RFI-S1-KYIV-NORD"
    assert matches[0]["emitter_type"] == "EW_JAMMER"
    assert matches[0]["distance_km"] < 5.0


def test_find_nearby_none_in_western_ukraine():
    # Lviv center - no front-line RFI emitter within 25km
    matches = find_nearby_ew_activity(49.8397, 24.0297, max_dist_km=25)
    assert len(matches) == 0
