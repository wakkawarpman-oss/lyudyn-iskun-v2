from worker.geo_extractors.consensus import GeoEvidence, resolve_geo_consensus, haversine_distance_meters


def test_haversine_distance_accuracy():
    # Kyiv Maidan to Kyiv Pechersk Lavra (~2.8 km)
    d = haversine_distance_meters(50.4505, 30.5230, 50.4350, 30.5575)
    assert 2500 < d < 3200


def test_consensus_nearby_sources():
    e1 = GeoEvidence(source="poi", lat=50.4536, lon=30.3711, confidence=0.95, radius_meters=50.0, label="Склади")
    e2 = GeoEvidence(source="regex_address", lat=50.4538, lon=30.3715, confidence=0.85, radius_meters=100.0, label="Вулиця")

    res = resolve_geo_consensus([e1, e2])
    assert res is not None
    assert res.source == "consensus"
    assert res.is_conflict is False
    assert res.confidence >= 0.95
    assert res.radius_meters <= 50.0
    # Centroid close to e1
    assert abs(res.lat - 50.4536) < 0.001


def test_consensus_conflicting_sources():
    # Obolon vs Darnitsa (>10km apart)
    e_exif = GeoEvidence(source="exif", lat=50.5107, lon=30.5033, confidence=0.99, radius_meters=10.0, label="EXIF Оболонь")
    e_text = GeoEvidence(source="text_toponym", lat=50.4132, lon=30.6558, confidence=0.60, radius_meters=2000.0, label="Текст Дарниця")

    res = resolve_geo_consensus([e_exif, e_text])
    assert res is not None
    assert res.is_conflict is True
    # Should pick EXIF due to much higher confidence
    assert res.source == "exif"
    assert abs(res.lat - 50.5107) < 0.001
    assert res.radius_meters > 2000.0
