from worker.geo_extractors.address_extractor import AddressExtractor
from worker.verification.live_target_verifier import LiveTargetVerifier


def test_address_extractor_full_address():
    text = "Увага! Приліт на вул. Соборна, 57 у Рівному, пожежа!"
    results = AddressExtractor.extract(text)
    assert len(results) > 0
    addr = results[0]
    assert addr.location_type == "address"
    assert "Соборна" in addr.street
    assert addr.building == "57"
    assert addr.city == "Рівне"
    assert addr.latitude is not None
    assert addr.longitude is not None
    assert addr.confidence >= 0.85


def test_address_extractor_decimal_coords():
    text = "Виявлено ворожий БпЛА: 50.4501, 30.5234 біля мосту"
    results = AddressExtractor.extract(text)
    assert len(results) > 0
    coord = results[0]
    assert coord.location_type == "coordinate"
    assert round(coord.latitude, 4) == 50.4501
    assert round(coord.longitude, 4) == 30.5234
    assert coord.confidence >= 0.95


def test_address_extractor_dms_coords():
    text = "БпЛА помічено: 46°29 05 N 30°44 20 E курсом на південь"
    results = AddressExtractor.extract(text)
    assert len(results) > 0
    coord = results[0]
    assert coord.location_type == "coordinate"
    assert 46.4 <= coord.latitude <= 46.5
    assert 30.7 <= coord.longitude <= 30.8
    assert coord.confidence >= 0.95


def test_address_extractor_city_declensions():
    for text, expected_city in [
        ("Вибухи у Харкові", "Харків"),
        ("Тривога в Києві", "Київ"),
        ("Повідомляють про звуки у Львові", "Львів"),
        ("У Запоріжжі чутно гучні звуки", "Запоріжжя"),
    ]:
        results = AddressExtractor.extract(text)
        assert len(results) > 0
        assert results[0].city == expected_city


def test_live_verifier_rivne_shelter_match():
    query = "Удар біля вул. Соборна, 57 у Рівному"
    report = LiveTargetVerifier.verify(query)
    assert report.location is not None
    assert report.location["city"] == "Рівне"
    assert report.confidence_score >= 40
    assert report.nearest_shelter is not None
    assert "ПРУ" in report.nearest_shelter["name"]
    assert len(report.tactical_recommendations) > 0


def test_live_verifier_kyiv_infra_match():
    query = "Фіксація БпЛА над координатами 50.4501, 30.5234"
    report = LiveTargetVerifier.verify(query)
    assert report.location is not None
    assert report.location["location_type"] == "coordinate"
    assert len(report.nearby_infrastructure) > 0
    assert report.confidence_score >= 50


def test_openwebui_manifest_has_verify_tool():
    from api.routes.openwebui_tools import get_tools_manifest
    manifest = get_tools_manifest()
    tool_names = [t["name"] for t in manifest["tools"]]
    assert "c4isr_verify_address" in tool_names
    assert "c4isr_radar_threats" in tool_names
    assert "c4isr_infrastructure_proximity" in tool_names
