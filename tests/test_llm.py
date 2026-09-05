from worker.llm_engine import rule_based_fallback_parser
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


def test_ollama_fallback_routing():
    """Verify that when Groq returns 429/error, routing automatically falls back to local Ollama."""
    from unittest.mock import patch, MagicMock
    from worker.llm_engine import _route_text_llm

    mock_groq_resp = MagicMock()
    mock_groq_resp.status_code = 429

    mock_ollama_res = {
        "is_kyiv_region": True,
        "is_confirmed_incident": True,
        "is_radar_track": False,
        "event_type": "explosion",
        "location": "Бровари",
        "osm_query": "Бровари",
        "casualties": False,
        "damage_level": "none",
        "short_summary": "Вибух у Броварах"
    }

    with patch("worker.llm_engine._call_groq_text", return_value=mock_groq_resp), \
         patch("worker.llm_engine._call_ollama_text", return_value=mock_ollama_res) as mock_ollama:
        result = _route_text_llm("Вибух у Броварах", "sys prompt")
        assert mock_ollama.called
        assert result["location"] == "Бровари"
        assert result["event_type"] == "explosion"


def test_call_ollama_text_parsing():
    """Verify that _call_ollama_text parses Ollama json output correctly."""
    from unittest.mock import patch, MagicMock
    from worker.llm_engine import _call_ollama_text

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": '{"is_kyiv_region": true, "location": "Поділ", "event_type": "fire"}'
    }

    with patch("requests.post", return_value=mock_resp):
        res = _call_ollama_text("Пожежа на Подолі", "sys prompt")
        assert res["is_kyiv_region"] is True
        assert res["location"] == "Поділ"
        assert res["event_type"] == "fire"
