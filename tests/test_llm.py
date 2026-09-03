import pytest
from worker.llm_engine import clean_and_validate_json_response, rule_based_fallback_parser
from worker.llm_engine import clean_and_validate_json_response as clean_json_response

def test_clean_json_response():
    # clean_and_validate_json_response runs input through a Pydantic schema, so
    # the result always carries every schema field (with defaults) — not just
    # the keys present in the raw JSON. Assert on the fields under test instead
    # of full-dict equality.

    # Test perfect JSON
    raw_1 = '{"is_kyiv_region": true}'
    assert clean_json_response(raw_1)["is_kyiv_region"] == True

    # Test Markdown wrapped JSON
    raw_2 = '```json\n{"is_kyiv_region": false, "event_type": "explosion"}\n```'
    result_2 = clean_json_response(raw_2)
    assert result_2["is_kyiv_region"] == False
    assert result_2["event_type"] == "explosion"

    # Test generic backticks
    raw_3 = '```\n{"location": "Оболонь"}\n```'
    assert clean_json_response(raw_3)["location"] == "Оболонь"

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
