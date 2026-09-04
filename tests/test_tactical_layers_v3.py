"""
Test Suite for Tactical C4ISR Layers & Target Verification (V3 Master Plan).
=============================================================================
Verifies:
1. Weapon Engagement Zones (WEZ) Air Defense Envelope Engine
2. Line of Bearing (LOB) & Geodesic Triangulation Engine
3. Optical CCTV Reconnaissance Registry for TOT
4. NOAA Solar Position & Shadow Chronolocation Engine
5. Offline MBTiles Container Status
"""

import os
import pytest
from datetime import datetime, timezone

os.environ["SECRET_KEY"] = "test_tactical_layers_verification_secret_2026"
os.environ["TESTING"] = "true"

from worker.osint.wez_envelopes import generate_wez_geojson, AIR_DEFENSE_TTX
from worker.osint.lob_triangulation import compute_lob_triangulation, forward_geodesic, intersect_two_bearings
from worker.osint.cctv_registry import get_cctv_recon_nodes, CCTV_NODES_REGISTRY
from worker.osint.geoint_engine import geoint_engine
from api.mbtiles_server import get_mbtiles_status


def test_wez_envelopes_structure():
    """Verify WEZ GeoJSON FeatureCollection conforms to C4ISR schema."""
    geojson = generate_wez_geojson()
    assert geojson["type"] == "FeatureCollection"
    assert geojson["count"] >= 5
    assert len(geojson["features"]) == geojson["count"]

    # Verify Tor-M2 and S-400 properties
    systems = [f["properties"]["system_type"] for f in geojson["features"]]
    assert "TOR_M2" in systems
    assert "S400_TRIUMF" in systems
    assert "PANTSIR_S1" in systems

    for feat in geojson["features"]:
        props = feat["properties"]
        assert props["kill_radius_m"] > 0
        assert props["radar_radius_m"] > props["kill_radius_m"]
        assert props["color"].startswith("#")


def test_lob_forward_geodesic():
    """Verify forward geodesic coordinate projection on WGS-84."""
    start_lat, start_lon = 50.4501, 30.5234 # Kyiv center
    # Project 10 km East (Azimuth 90 deg)
    pt = forward_geodesic(start_lat, start_lon, 90.0, 10000.0)
    assert round(pt["lat"], 2) == 50.45
    assert pt["lon"] > start_lon


def test_lob_triangulation_convergence():
    """Verify multi-bearing intersection converges and calculates CEP."""
    bearings = [
        {"lat": 46.40640, "lon": 32.63750, "azimuth": 250.0, "observer": "CP 1"},
        {"lat": 46.43500, "lon": 32.58000, "azimuth": 165.0, "observer": "OP 2"}
    ]
    res = compute_lob_triangulation(bearings)
    assert res["status"] == "success"
    assert "target" in res
    assert 46.35 < res["target"]["lat"] < 46.45
    assert 32.55 < res["target"]["lon"] < 32.65
    assert res["cep_radius_m"] >= 20.0
    assert len(res["rays"]) == 2


def test_lob_triangulation_alternate_keys():
    """Verify LOB triangulation supports station_id, observer_lat/lon and bearing_deg."""
    bearings = [
        {"station_id": "P-1", "observer_lat": 50.40, "observer_lon": 30.50, "bearing_deg": 45.0, "sigma_deg": 1.0},
        {"station_id": "P-2", "observer_lat": 50.40, "observer_lon": 30.70, "bearing_deg": 315.0, "sigma_deg": 1.0}
    ]
    res = compute_lob_triangulation(bearings)
    assert res["status"] == "success"
    assert "target" in res
    assert "lat" in res["target"]
    assert "lon" in res["target"]
    assert len(res["rays"]) == 2


def test_lob_triangulation_diverging():
    """Verify diverging bearings are detected and handled gracefully."""
    diverging = [
        {"lat": 50.0, "lon": 30.0, "azimuth": 0.0},
        {"lat": 50.0, "lon": 31.0, "azimuth": 180.0}
    ]
    res = compute_lob_triangulation(diverging)
    assert res["status"] in ("diverging_bearings", "insufficient_data")


def test_cctv_registry_coverage():
    """Verify CCTV registry includes nodes across key TOT sectors."""
    cctv = get_cctv_recon_nodes()
    assert cctv["status"] == "success"
    assert cctv["count"] >= 7

    cities = [n["city"] for n in cctv["nodes"]]
    assert any("Донецьк" in c for c in cities)
    assert any("Севастополь" in c for c in cities)
    assert any("Харків" in c for c in cities)


def test_sun_shadow_chronolocation_kyiv():
    """Verify solar elevation and shadow calculations for known timestamp."""
    dt_noon = datetime(2026, 9, 4, 10, 0, 0, tzinfo=timezone.utc) # 13:00 Kyiv daylight time
    res = geoint_engine.calculate_sun_position(50.4501, 30.5234, dt_noon)
    
    assert res["is_daylight"] is True
    assert 35.0 < res["solar_elevation_deg"] < 60.0
    assert 150.0 < res["solar_azimuth_deg"] < 210.0
    # Shadow direction is exactly opposite to solar azimuth
    expected_shadow = (res["solar_azimuth_deg"] + 180.0) % 360.0
    assert abs(res["shadow_direction_deg"] - expected_shadow) < 0.1
    assert isinstance(res["shadow_ratio"], (int, float))
    assert res["shadow_ratio"] > 0


def test_mbtiles_server_status():
    """Verify MBTiles status endpoint handles unmounted state gracefully."""
    status = get_mbtiles_status()
    assert "status" in status
    assert status["status"] in ("offline_bundle_missing", "online")
    assert "download_url" in status or "total_tiles" in status


def test_cot_datapackage_zip_export():
    """Verify CoT DataPackage ZIP export returns valid ZIP with manifest and XML."""
    import zipfile
    import io
    from database.models import SessionLocal
    from api.cot import get_cot_zip_datapackage, verify_tactical_token
    from fastapi import HTTPException

    token = "tac_bb322f2ef46e0ca293a54ef4dc1bc882de9f9f4c"
    os.environ["TACTICAL_API_TOKEN"] = token

    # 1. Test token verification
    class DummyRequest:
        headers = {}

    with pytest.raises(HTTPException) as exc_info:
        verify_tactical_token(DummyRequest(), token="wrong_token")
    assert exc_info.value.status_code == 401

    assert verify_tactical_token(DummyRequest(), token=token) is True

    # 2. Test get_cot_zip_datapackage execution on current DB (SQLite)
    from database.models import init_db
    init_db()
    db = SessionLocal()
    try:
        response = get_cot_zip_datapackage(hours=48, token_valid=True, db=db)
        assert response.status_code == 200
        assert response.media_type == "application/zip"
        assert "attachment; filename=\"iskun_cot_" in response.headers["content-disposition"]

        # 3. Verify ZIP contents structure
        zf = zipfile.ZipFile(io.BytesIO(response.body))
        file_list = zf.namelist()
        assert "MANIFEST/manifest.xml" in file_list
        assert "events.cot" in file_list

        manifest_xml = zf.read("MANIFEST/manifest.xml").decode("utf-8")
        assert "MissionPackageManifest" in manifest_xml

        events_cot = zf.read("events.cot").decode("utf-8")
        assert "<?xml" in events_cot
        assert "<events" in events_cot
    finally:
        db.close()


def test_api_sync_endpoint():
    """Verify POST /api/v1/sync endpoint returns valid response structure."""
    from api.main import trigger_sync
    res = trigger_sync()
    assert "status" in res
    assert res["status"] in ("success", "error")



