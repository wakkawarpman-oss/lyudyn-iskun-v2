"""
Unit and Integration Tests for ATAK Cursor-on-Target (CoT) XML & DataPackage export.
"""
import io
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api.cot import (
    COT_TYPE_MAPPING,
    build_cot_event_element,
    generate_cot_datapackage_zip,
    generate_cot_xml,
    get_cot_feed,
    get_cot_zip_datapackage,
    verify_tactical_token,
)


class MockEvent:
    def __init__(
        self,
        id=1,
        incident_id="INC-202609030830-BROVARY",
        event_type="radar_track",
        location_text="Бровари & Бориспіль <Сектор>",
        resonance_score=90,
        significance_score=85,
        confidence_score=92,
        sources_count=3,
        is_fallback_geo=False,
        detected_at=None,
        lat=50.511117,
        lon=30.790048,
    ):
        import datetime

        self.id = id
        self.incident_id = incident_id
        self.event_type = event_type
        self.location_text = location_text
        self.resonance_score = resonance_score
        self.significance_score = significance_score
        self.confidence_score = confidence_score
        self.sources_count = sources_count
        self.is_fallback_geo = is_fallback_geo
        self.detected_at = detected_at or datetime.datetime(2026, 9, 3, 8, 30, 0)
        self.lat = lat
        self.lon = lon


def test_cot_xml_validity_and_character_escaping():
    """Ensure ElementTree generates well-formed XML even with special characters."""
    ev = MockEvent(
        location_text="Київ & Область <\"Спец-Зона\"> 'Троєщина'",
        event_type="radar_track",
    )
    elem = build_cot_event_element(ev)
    xml_str = ET.tostring(elem, encoding="utf-8").decode("utf-8")

    # Parse back with ElementTree to guarantee 100% valid XML syntax
    parsed = ET.fromstring(xml_str)
    assert parsed.tag == "event"
    assert parsed.attrib["uid"] == "INC-202609030830-BROVARY"
    assert parsed.attrib["type"] == COT_TYPE_MAPPING["radar_track"]["cot_type"]
    assert parsed.attrib["how"] == "m-g"
    assert parsed.attrib["time"] == "2026-09-03T08:30:00Z"
    assert parsed.attrib["stale"] == "2026-09-03T10:30:00Z"

    # Check point coordinates
    pt = parsed.find("point")
    assert pt is not None
    assert pt.attrib["lat"] == "50.511117"
    assert pt.attrib["lon"] == "30.790048"

    # Check contact callsign and remarks
    contact = parsed.find("detail/contact")
    assert contact is not None
    assert "БпЛА: Київ & Область <\"Спец-Зона\"> 'Троєщина'" in contact.attrib["callsign"]

    remarks = parsed.find("detail/remarks")
    assert remarks is not None
    assert "Загроза: 85/100" in remarks.text


def test_cot_type_mappings():
    """Verify standard MIL-STD-2525 and BDA spot mappings."""
    types_to_check = {
        "radar_track": "a-h-A-M-F-Q",
        "missile": "a-h-A-M-M",
        "air_defense": "a-f-G-U-C-A",
        "direct_strike": "b-m-p-s-p-loc",
        "explosion": "b-m-p-s-p-loc",
        "fire": "b-m-p-s-p-loc",
        "destruction": "b-m-p-s-p-loc",
    }
    for ev_type, expected_cot in types_to_check.items():
        ev = MockEvent(event_type=ev_type)
        elem = build_cot_event_element(ev)
        assert elem.attrib["type"] == expected_cot


def test_cot_xml_deduplication():
    """Verify 1 <event> per unique incident_id."""
    ev1 = MockEvent(id=1, incident_id="INC-BROVARY-01")
    ev2 = MockEvent(id=2, incident_id="INC-BROVARY-01")  # duplicate incident
    ev3 = MockEvent(id=3, incident_id="INC-BORYSPIL-02")

    xml_out = generate_cot_xml([ev1, ev2, ev3])
    root = ET.fromstring(xml_out)
    events = root.findall("event")
    assert len(events) == 2
    uids = [e.attrib["uid"] for e in events]
    assert uids == ["INC-BROVARY-01", "INC-BORYSPIL-02"]


def test_cot_datapackage_zip_structure():
    """Verify DataPackage ZIP contains valid MANIFEST/manifest.xml and events.cot."""
    ev = MockEvent(incident_id="INC-TEST-ZIP")
    zip_bytes = generate_cot_datapackage_zip([ev])

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        file_list = zf.namelist()
        assert "MANIFEST/manifest.xml" in file_list
        assert "events.cot" in file_list

        # Validate MANIFEST XML
        manifest_data = zf.read("MANIFEST/manifest.xml")
        manifest_tree = ET.fromstring(manifest_data)
        assert manifest_tree.tag == "MissionPackageManifest"
        assert manifest_tree.attrib["version"] == "2"

        # Validate events.cot XML
        cot_data = zf.read("events.cot")
        cot_tree = ET.fromstring(cot_data)
        assert cot_tree.tag == "events"
        assert len(cot_tree.findall("event")) == 1


def test_verify_tactical_token_security():
    """Test fail-closed security and token comparison."""
    mock_request = MagicMock()
    mock_request.headers.get.return_value = None

    # 1. Fail-closed: TACTICAL_API_TOKEN is unset in environment -> 503
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(HTTPException) as exc_info:
            verify_tactical_token(mock_request, token=None)
        assert exc_info.value.status_code == 503

    # 2. Unauthorized: Missing or invalid token -> 401
    with patch.dict("os.environ", {"TACTICAL_API_TOKEN": "secret-tac-token-123"}):
        with pytest.raises(HTTPException) as exc_info:
            verify_tactical_token(mock_request, token=None)
        assert exc_info.value.status_code == 401

        with pytest.raises(HTTPException) as exc_info:
            verify_tactical_token(mock_request, token="invalid-token")
        assert exc_info.value.status_code == 401

    # 3. Authorized via query param -> True
    with patch.dict("os.environ", {"TACTICAL_API_TOKEN": "secret-tac-token-123"}):
        assert verify_tactical_token(mock_request, token="secret-tac-token-123") is True

    # 4. Authorized via header -> True
    mock_request_hdr = MagicMock()
    mock_request_hdr.headers.get.return_value = "secret-tac-token-123"
    with patch.dict("os.environ", {"TACTICAL_API_TOKEN": "secret-tac-token-123"}):
        assert verify_tactical_token(mock_request_hdr, token=None) is True


def test_get_cot_feed_and_zip_endpoints():
    """Verify endpoint handlers return proper XML and ZIP content."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        MockEvent(incident_id="INC-ENDPOINT-TEST")
    ]

    # Test XML feed
    resp_xml = get_cot_feed(hours=24, token_valid=True, db=mock_db)
    assert resp_xml.media_type == "application/xml"
    assert b"INC-ENDPOINT-TEST" in resp_xml.body

    # Test ZIP DataPackage
    resp_zip = get_cot_zip_datapackage(hours=24, token_valid=True, db=mock_db)
    assert resp_zip.media_type == "application/zip"
    assert "attachment; filename=\"iskun_cot_" in resp_zip.headers["Content-Disposition"]
    assert len(resp_zip.body) > 0
