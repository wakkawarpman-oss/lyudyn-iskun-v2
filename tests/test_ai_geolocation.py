import pytest
from unittest.mock import patch, MagicMock
from worker.osint.ai_geolocation import AIGeolocation


def test_ai_geolocation_file_not_found():
    geo = AIGeolocation()
    assert geo.analyze_image("/path/to/nonexistent/file.jpg") is None


def test_ai_geolocation_gemini_fallback(tmp_path):
    dummy_img = tmp_path / "test.jpg"
    dummy_img.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00")

    geo = AIGeolocation()

    # GeoSpy returns None, Gemini succeeds
    with patch.object(geo, "_analyze_geospy", return_value=None):
        with patch.object(geo, "_analyze_gemini", return_value={
            "predicted_location": "Київ, Поділ",
            "confidence": "high",
            "coordinates": [50.4682, 30.5154],
            "clues": "Андріївська церква"
        }):
            res = geo.analyze_image(str(dummy_img))
            assert res is not None
            assert res["provider"] == "Gemini Vision"
            assert "Поділ" in res["predicted_location"]
            assert res["coordinates"] == [50.4682, 30.5154]


def test_ai_geolocation_openai_fallback(tmp_path):
    dummy_img = tmp_path / "test2.jpg"
    dummy_img.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00")

    geo = AIGeolocation()

    # Both GeoSpy and Gemini fail, OpenAI succeeds
    with patch.object(geo, "_analyze_geospy", return_value=None):
        with patch.object(geo, "_analyze_gemini", return_value=None):
            with patch.object(geo, "_analyze_openai", return_value={
                "predicted_location": "Бровари, Київська обл",
                "confidence": "medium",
                "coordinates": [50.5111, 30.7900]
            }):
                res = geo.analyze_image(str(dummy_img))
                assert res is not None
                assert res["provider"] == "OpenAI Vision"
                assert "Бровари" in res["predicted_location"]
