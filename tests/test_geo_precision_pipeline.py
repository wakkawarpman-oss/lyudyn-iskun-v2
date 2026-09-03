from unittest.mock import patch
from worker.tasks import pipeline_geocode


def test_pipeline_geocode_tier_poi():
    data = {
        "skip": False,
        "payload": {
            "text": "Российские террористы снова бьют по бизнесу в Украине: уничтожены склады OKWINE",
            "channel": "test_channel"
        },
        "llm_data": {"location": "Святошинський район, Київ"},
        "geom_wkt": None,
        "osint_location": None
    }
    res = pipeline_geocode(data)
    assert res["precision_tier"] == "building"
    assert res["precision_radius_m"] == 50
    assert res["is_fallback_geo"] is False
    assert "POINT(30.3711 50.4536)" in res["geom_wkt"]
    assert "склади OKWINE" in res["llm_data"]["location"]


def test_pipeline_geocode_tier_address():
    data = {
        "skip": False,
        "payload": {
            "text": "На Харківському шосе 121 ледь не вщент згорів автомобіль",
            "channel": "test_channel"
        },
        "llm_data": {"location": "Київ"},
        "geom_wkt": None,
        "osint_location": None
    }
    with patch("worker.tasks.cached_geocode", return_value="POINT(30.65 50.42)") as mock_geo:
        res = pipeline_geocode(data)
        assert res["precision_tier"] == "address"
        assert res["precision_radius_m"] == 100
        assert res["is_fallback_geo"] is False
        assert res["geom_wkt"] == "POINT(30.65 50.42)"
        assert "Харківське шосе, 121, Київ" in res["llm_data"]["location"]


def test_pipeline_geocode_tier_settlement_fallback():
    data = {
        "skip": False,
        "payload": {
            "text": "💥Бучанський р-н - вибухи",
            "channel": "test_channel"
        },
        "llm_data": {"location": "Буча"},
        "geom_wkt": None,
        "osint_location": None
    }
    res = pipeline_geocode(data)
    assert res["precision_tier"] == "settlement"
    assert res["precision_radius_m"] == 2000
    assert res["is_fallback_geo"] is False
    assert "POINT(30.210693 50.550313)" in res["geom_wkt"]
