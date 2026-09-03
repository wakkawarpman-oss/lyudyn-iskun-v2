import pytest
from worker.llm_engine import clean_and_validate_json_response, rule_based_fallback_parser
from worker.llm_engine import clean_and_validate_json_response as clean_json_response

def test_clean_json_response():
    # Test perfect JSON
    raw_1 = '{"is_kyiv_region": true}'
    assert clean_json_response(raw_1) == {"is_kyiv_region": True}

    # Test Markdown wrapped JSON
    raw_2 = '```json\n{"is_kyiv_region": false, "event_type": "explosion"}\n```'
    assert clean_json_response(raw_2) == {"is_kyiv_region": False, "event_type": "explosion"}

    # Test generic backticks
    raw_3 = '```\n{"location": "Оболонь"}\n```'
    assert clean_json_response(raw_3) == {"location": "Оболонь"}

def test_rule_based_fallback():
    # Test empty
    assert rule_based_fallback_parser("") == {"is_kyiv_region": False}

    # Test kyiv explosion
    res = rule_based_fallback_parser("Вибух на лівому березі, Дарниця!")
    assert res["is_kyiv_region"] == True
    assert res["event_type"] == "explosion"
    assert "Дарниця" in res["location"]

    # Test kyiv radar track
    res = rule_based_fallback_parser("Ракета летить на Київ з півночі")
    assert res["is_kyiv_region"] == True
    assert res["event_type"] == "radar_track"
    assert res["is_radar_track"] == True
