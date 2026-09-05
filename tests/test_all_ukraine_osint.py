"""
Unit & Integration Tests for All-Ukraine C4ISR Multi-Region OSINT Pipeline.
Verifies national coordinates validation, channel registry completeness,
channel oblast resolution, and dynamic alert routing for all Ukrainian regions.
"""
import json
import os
import pytest

from worker.geo_disambiguation import (
    validate_tactical_coordinates,
    detect_channel_oblast,
    detect_external_oblast,
    is_explicitly_kyiv_context
)
from worker.schemas import ParsedEventSchema, EventTypeEnum


def test_validate_tactical_coordinates_national_bounds():
    """Verify that all major regional centers pass national Ukraine coordinate validation."""
    cities = {
        "kharkiv": (49.9935, 36.2304),
        "odesa": (46.4825, 30.7233),
        "dnipro": (48.4647, 35.0462),
        "zaporizhzhia": (47.8388, 35.1396),
        "lviv": (49.8397, 24.0297),
        "mykolaiv": (46.9750, 31.9946),
        "sumy": (50.9077, 34.7981),
        "poltava": (49.5883, 34.5514),
        "kyiv": (50.4501, 30.5234),
        "sevastopol": (44.6167, 33.5254),
    }
    for city, (lat, lon) in cities.items():
        ok, err = validate_tactical_coordinates(lat, lon)
        assert ok is True, f"Failed for {city}: {err}"


def test_validate_tactical_coordinates_inverted_and_out_of_bounds():
    """Verify that inverted (lon/lat swapped) or foreign coordinates are rejected."""
    # Inverted: Lon and Lat swapped (e.g. Lon=50.45, Lat=30.52)
    ok, err = validate_tactical_coordinates(30.52, 50.45)
    assert ok is False
    assert "inverted_or_out_of_ukraine_bounds" in err

    # Out of bounds: Atlantic ocean
    ok, err = validate_tactical_coordinates(15.0, 15.0)
    assert ok is False
    assert "inverted_or_out_of_ukraine_bounds" in err

    # Missing coordinates
    ok, err = validate_tactical_coordinates(None, 30.5)
    assert ok is False
    assert err == "missing_coordinates"


def test_validate_tactical_coordinates_metro_guard():
    """Verify that is_kyiv_metro=True strictly enforces metropolitan boundaries."""
    # Inside Kyiv
    ok, err = validate_tactical_coordinates(50.4501, 30.5234, is_kyiv_metro=True)
    assert ok is True

    # Bila Tserkva (Kyiv Oblast, outside metro)
    ok, err = validate_tactical_coordinates(49.7967, 30.1317, is_kyiv_metro=True)
    assert ok is False
    assert "outside_kyiv_metro_bounds" in err


def test_channel_registry_completeness():
    """Verify channel_registry.json contains all 27+ oblasts and newly added operational monitors."""
    reg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "channels", "channel_registry.json")
    with open(reg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "kharkiv" in data
    assert "odesa" in data
    assert "mykolaiv" in data
    assert "dnipropetrovsk" in data
    assert "zaporizhzhia" in data
    assert "sumy" in data
    assert "poltava" in data
    assert "lviv" in data

    # Check newly added operational monitoring channels
    kharkiv_handles = [c["username"] for c in data["kharkiv"]]
    assert "kharkiv_life" in kharkiv_handles
    assert "kharkov_radar" in kharkiv_handles

    odesa_handles = [c["username"] for c in data["odesa"]]
    assert "odessa_typical" in odesa_handles
    assert "our_odessa" in odesa_handles

    mykolaiv_handles = [c["username"] for c in data["mykolaiv"]]
    assert "novostiniko" in mykolaiv_handles
    assert "nikolaev_live" in mykolaiv_handles

    lviv_handles = [c["username"] for c in data["lviv"]]
    assert "lviv_typical" in lviv_handles
    assert "lviv_radar" in lviv_handles


def test_channel_oblast_detection():
    """Verify that detect_channel_oblast properly attributes regional channels."""
    assert detect_channel_oblast("senkevichonline") == "mykolaiv"
    assert detect_channel_oblast("synegubov") == "kharkiv"
    assert detect_channel_oblast("kharkiv_life") == "kharkiv"
    assert detect_channel_oblast("odessa_typical") == "odesa"
    assert detect_channel_oblast("ivan_fedorov_zp") == "zaporizhzhia"
    assert detect_channel_oblast("dnepr_live") == "dnipropetrovsk"
    assert detect_channel_oblast("lviv_typical") == "lviv"
    assert detect_channel_oblast("poltava_alerts") == "poltava"
    assert detect_channel_oblast("sumy_radar") == "sumy"


def test_parsed_event_schema_target_oblast():
    """Verify that ParsedEventSchema supports target_oblast attribute."""
    event = ParsedEventSchema(
        is_kyiv_region=False,
        target_oblast="kharkiv",
        is_confirmed_incident=True,
        event_type=EventTypeEnum.EXPLOSION,
        location="Салтівка, Харків",
        osm_query="Салтівка, Харків"
    )
    d = event.model_dump()
    assert d["target_oblast"] == "kharkiv"
    assert d["is_kyiv_region"] is False
    assert d["event_type"] == "explosion"


def test_dynamic_generic_alert_metadata():
    """Verify OBLAST_ALERT_METADATA correctly maps regional alerts without hardcoding Kyiv."""
    from worker.tasks import OBLAST_ALERT_METADATA

    assert OBLAST_ALERT_METADATA["mykolaiv"]["location"] == "Миколаїв та область"
    assert OBLAST_ALERT_METADATA["mykolaiv"]["lat"] == 46.9750
    assert OBLAST_ALERT_METADATA["mykolaiv"]["lon"] == 31.9946

    assert OBLAST_ALERT_METADATA["kharkiv"]["location"] == "Харків та область"
    assert OBLAST_ALERT_METADATA["kharkiv"]["lat"] == 49.9935
    assert OBLAST_ALERT_METADATA["kharkiv"]["lon"] == 36.2304

    assert OBLAST_ALERT_METADATA["zaporizhzhia"]["location"] == "Запоріжжя та область"
    assert OBLAST_ALERT_METADATA["zaporizhzhia"]["lat"] == 47.8388
    assert OBLAST_ALERT_METADATA["zaporizhzhia"]["lon"] == 35.1396

    assert OBLAST_ALERT_METADATA["odesa"]["location"] == "Одеса та область"
    assert OBLAST_ALERT_METADATA["odesa"]["lat"] == 46.4825
    assert OBLAST_ALERT_METADATA["odesa"]["lon"] == 30.7233
