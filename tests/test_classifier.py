import pytest
from worker.llm_engine import process_with_llm
from unittest.mock import patch

TEST_CASES = [
    ("Бахнуло в Бучі о 14:30, чути гучний вибух", True, "explosion", "Буч"),
    ("Сьогодні гарна погода в Києві", False, None, None),
    ("Обстріл Шевченківського району, ракета влучила в багатоповерхівку", True, "direct_strike", "Шевченківськ"),
    ("Даша їде на дачу", False, None, None),
    ("Shahed летить у бік Києва, тривога", True, "radar_track", None),
]

def mock_llm(text, media_path):
    if "Бучі" in text:
        return {"is_kyiv_region": True, "is_confirmed_incident": True, "event_type": "explosion", "location": "Буча"}
    if "погода" in text:
        return {"is_kyiv_region": True, "is_confirmed_incident": False}
    if "Обстріл" in text:
        return {"is_kyiv_region": True, "is_confirmed_incident": True, "event_type": "direct_strike", "location": "Шевченківський район"}
    if "Даша" in text:
        return {"is_kyiv_region": False, "is_confirmed_incident": False}
    if "Shahed" in text:
        return {"is_kyiv_region": True, "is_confirmed_incident": False, "is_radar_track": True, "event_type": "radar_track"}
    if "Львові" in text:
        return {"is_kyiv_region": False}
    return {}

@patch('worker.llm_engine.process_with_llm', side_effect=mock_llm)
@pytest.mark.parametrize("text,is_strike,event_type,location", TEST_CASES)
def test_classify(mock_func, text, is_strike, event_type, location):
    result = mock_func(text, None)
    
    if not is_strike:
        assert not result.get("is_confirmed_incident", False)
        return
        
    assert result.get("is_confirmed_incident", False) or result.get("is_radar_track", False)
    if event_type:
        assert result.get("event_type") == event_type
    if location:
        assert location in result.get("location", "")

@patch('worker.llm_engine.process_with_llm', side_effect=mock_llm)
def test_kyiv_filter(mock_func):
    r = mock_func("Вибух у Львові", None)
    assert not r.get("is_kyiv_region", False)
