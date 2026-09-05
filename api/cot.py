"""
Cursor on Target (CoT) XML & DataPackage (ZIP) Export for ATAK / WinTAK.

Specification & Contract Compliance:
- Format: Cursor-on-Target XML 2.0 (Event.xsd) & MIL-STD-2525C/D symbology.
- Serialization: xml.etree.ElementTree ONLY (safe escaping of &, <, >, ", ').
- Packaging: In-memory ZipFile with MANIFEST/manifest.xml.
- Authentication: Token via query (?token=...) or Header (X-Tactical-Token), checked via hmac.compare_digest.
  Fail-closed: if TACTICAL_API_TOKEN is not set in environment, returns 503.
- Filter: Strict SQL filter (geom is not None, is_fallback_geo == False, detected_at >= threshold).
- Deduplication: 1 <event> per unique incident_id (or event.id fallback).
"""
import datetime
import hmac
import io
import logging
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import DetectedEvent, SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cot", tags=["tactical_cot"])

# Mapping from internal event_type to ATAK CoT Type & UI Color (ARGB)
COT_TYPE_MAPPING = {
    "radar_track": {
        "cot_type": "a-h-A-M-F-Q",  # Hostile Air Fixed-Wing UAS / Drone
        "color_argb": "-65536",     # Red #FFFF0000
        "icon": "COT_MAPPING_2525C/Air/Hostile/UAS.png",
        "callsign_prefix": "БпЛА",
    },
    "missile": {
        "cot_type": "a-h-A-M-M",    # Hostile Air Missile
        "color_argb": "-65536",     # Red #FFFF0000
        "icon": "COT_MAPPING_2525C/Air/Hostile/Missile.png",
        "callsign_prefix": "Ракета",
    },
    "air_defense": {
        "cot_type": "a-f-G-U-C-A",  # Friendly Ground Air Defense
        "color_argb": "-16776961",  # Blue #FF0000FF
        "icon": "COT_MAPPING_2525C/Ground/Friendly/AirDefense.png",
        "callsign_prefix": "ППО",
    },
    "direct_strike": {
        "cot_type": "b-m-p-s-p-loc", # Universal Spot Marker with BDA color
        "color_argb": "-65536",     # Red #FFFF0000
        "icon": "COT_MAPPING_2525C/Emergency Operations/explosion.png",
        "callsign_prefix": "Приліт",
    },
    "explosion": {
        "cot_type": "b-m-p-s-p-loc",
        "color_argb": "-65536",     # Red #FFFF0000
        "icon": "COT_MAPPING_2525C/Emergency Operations/explosion.png",
        "callsign_prefix": "Вибух",
    },
    "fire": {
        "cot_type": "b-m-p-s-p-loc",
        "color_argb": "-39424",     # Orange #FFFF6600
        "icon": "COT_MAPPING_2525C/Emergency Operations/fire.png",
        "callsign_prefix": "Пожежа",
    },
    "destruction": {
        "cot_type": "b-m-p-s-p-loc",
        "color_argb": "-65536",
        "icon": "COT_MAPPING_2525C/Emergency Operations/damage.png",
        "callsign_prefix": "Руйнування",
    },
}

DEFAULT_COT_TYPE = {
    "cot_type": "b-m-p-s-p-loc",
    "color_argb": "-65536",
    "icon": "COT_MAPPING_2525C/Emergency Operations/spot.png",
    "callsign_prefix": "Інцидент",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_tactical_token(request: Request, token: Optional[str] = Query(None)):
    expected_token = os.getenv("TACTICAL_API_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="Tactical CoT feed unavailable: TACTICAL_API_TOKEN is not configured on server",
        )
    auth_header = request.headers.get("Authorization")
    bearer_token = None
    if auth_header and auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:].strip()
    provided_token = token or bearer_token or request.headers.get("X-Tactical-Token")
    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: invalid or missing tactical authentication token",
        )
    return True


def validate_cot_event_element(elem: ET.Element) -> bool:
    """Strictly validates a single CoT <event> against Cursor on Target 2.0 (Event.xsd) schema rules.
    
    Validates:
    - Root tag is 'event' with version='2.0'
    - Required attributes: uid, type, time, start, stale, how
    - Time format: strict ISO-8601 with trailing 'Z'
    - start <= stale temporal order
    - Mandatory <point> child with valid lat [-90, 90], lon [-180, 180], hae, ce >= 0, le >= 0
    - Mandatory <detail> child with <contact callsign="..." />
    """
    if elem.tag != "event":
        return False
    
    attrib = elem.attrib
    required_attrs = ("version", "uid", "type", "how", "time", "start", "stale")
    for attr in required_attrs:
        if not attrib.get(attr):
            logger.warning(f"CoT XSD validation error: missing required attribute '{attr}'")
            return False
            
    if attrib["version"] != "2.0":
        logger.warning(f"CoT XSD validation error: version must be '2.0', got '{attrib['version']}'")
        return False

    # Timestamp format check
    iso_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
    for t_attr in ("time", "start", "stale"):
        val = attrib.get(t_attr, "")
        if not iso_pattern.match(val):
            logger.warning(f"CoT XSD validation error: attribute '{t_attr}' has invalid ISO-8601 format '{val}'")
            return False
            
    if attrib["stale"] < attrib["start"]:
        logger.warning("CoT XSD validation error: stale timestamp is before start timestamp")
        return False

    # <point> check
    point = elem.find("point")
    if point is None:
        logger.warning("CoT XSD validation error: missing <point> element")
        return False

    try:
        lat = float(point.attrib.get("lat", ""))
        lon = float(point.attrib.get("lon", ""))
        float(point.attrib.get("hae", "0.0"))
        ce = float(point.attrib.get("ce", "9999999.0"))
        le = float(point.attrib.get("le", "9999999.0"))
    except (ValueError, TypeError) as pe:
        logger.warning(f"CoT XSD validation error: numeric conversion error in <point>: {pe}")
        return False

    if not (-90.0 <= lat <= 90.0):
        logger.warning(f"CoT XSD validation error: latitude out of bounds: {lat}")
        return False
    if not (-180.0 <= lon <= 180.0):
        logger.warning(f"CoT XSD validation error: longitude out of bounds: {lon}")
        return False
    if ce < 0.0 or le < 0.0:
        logger.warning(f"CoT XSD validation error: negative error radius (ce={ce}, le={le})")
        return False

    # <detail>/<contact> check
    detail = elem.find("detail")
    if detail is None:
        logger.warning("CoT XSD validation error: missing <detail> element")
        return False
    contact = detail.find("contact")
    if contact is None or not contact.attrib.get("callsign"):
        logger.warning("CoT XSD validation error: missing or empty <contact callsign=...>")
        return False

    return True


def build_cot_event_element(e) -> ET.Element:
    """Builds a single <event> XML Element using xml.etree.ElementTree."""
    cfg = COT_TYPE_MAPPING.get(e.event_type, DEFAULT_COT_TYPE)
    uid = e.incident_id or f"INC-{e.detected_at.strftime('%Y%m%d%H%M')}-{e.id}"
    
    now_utc = e.detected_at or datetime.datetime.utcnow()
    time_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_dt = now_utc + datetime.timedelta(hours=2)
    stale_str = stale_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    event_elem = ET.Element(
        "event",
        version="2.0",
        uid=str(uid),
        type=cfg["cot_type"],
        how="m-g",
        time=time_str,
        start=time_str,
        stale=stale_str,
    )

    # <point>
    lat_val = f"{float(e.lat):.6f}" if e.lat is not None else "50.450100"
    lon_val = f"{float(e.lon):.6f}" if e.lon is not None else "30.523400"
    ET.SubElement(
        event_elem,
        "point",
        lat=lat_val,
        lon=lon_val,
        hae="160.0",
        ce="25.0",
        le="10.0",
    )

    # <detail>
    detail = ET.SubElement(event_elem, "detail")
    callsign_text = f"{cfg['callsign_prefix']}: {e.location_text or 'Київ'}"
    ET.SubElement(detail, "contact", callsign=callsign_text)
    
    sig = getattr(e, "significance_score", 50) or 50
    conf = getattr(e, "confidence_score", 50) or 50
    src_cnt = getattr(e, "sources_count", 1) or 1
    remarks_text = (
        f"Загроза: {sig}/100 | Довіра: {conf}/100 | Консенсус: {src_cnt} дж. | ОКІНТ-ПРО C4ISR"
    )
    remarks_elem = ET.SubElement(detail, "remarks")
    remarks_elem.text = remarks_text

    ET.SubElement(detail, "color", argb=cfg["color_argb"])
    ET.SubElement(detail, "precisionlocation", geopointsrc="canonical_geo", altsrc="DTED0")
    if cfg.get("icon"):
        ET.SubElement(detail, "usericon", iconsetpath=cfg["icon"])

    return event_elem


def generate_cot_xml(events) -> str:
    """Constructs the root <events> element containing all valid CoT incidents."""
    root = ET.Element("events", version="2.0")
    seen_uids = set()
    for e in events:
        uid = e.incident_id or f"INC-{e.detected_at.strftime('%Y%m%d%H%M')}-{e.id}"
        if uid in seen_uids:
            continue
        elem = build_cot_event_element(e)
        if validate_cot_event_element(elem):
            seen_uids.add(uid)
            root.append(elem)
        else:
            logger.warning(f"Skipping CoT event with UID {uid}: failed XSD validation")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def generate_cot_datapackage_zip(events) -> bytes:
    """Generates an ATAK MissionPackage DataPackage (.zip) in memory."""
    cot_xml_data = generate_cot_xml(events)

    manifest_root = ET.Element("MissionPackageManifest", version="2")
    config_elem = ET.SubElement(manifest_root, "Configuration")
    ET.SubElement(config_elem, "Parameter", name="uid", value="ISKUN-COT-EXPORT")
    ET.SubElement(config_elem, "Parameter", name="name", value="Iskun COT Export")
    ET.SubElement(config_elem, "Parameter", name="onReceiveDelete", value="true")

    contents_elem = ET.SubElement(manifest_root, "Contents")
    ET.SubElement(contents_elem, "Content", ignore="false", zipEntry="events.cot")

    manifest_xml_data = ET.tostring(manifest_root, encoding="utf-8", xml_declaration=True)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("MANIFEST/manifest.xml", manifest_xml_data)
        zf.writestr("events.cot", cot_xml_data.encode("utf-8"))

    buf.seek(0)
    return buf.getvalue()


@router.get("", response_class=Response)
def get_cot_feed(
    hours: int = Query(24, ge=1, le=72),
    token_valid: bool = Depends(verify_tactical_token),
    db: Session = Depends(get_db),
):
    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    events = (
        db.query(
            DetectedEvent.id,
            DetectedEvent.incident_id,
            DetectedEvent.event_type,
            DetectedEvent.location_text,
            DetectedEvent.resonance_score,
            DetectedEvent.significance_score,
            DetectedEvent.confidence_score,
            DetectedEvent.sources_count,
            DetectedEvent.is_fallback_geo,
            DetectedEvent.detected_at,
            func.ST_Y(DetectedEvent.geom).label("lat"),
            func.ST_X(DetectedEvent.geom).label("lon"),
        )
        .filter(
            DetectedEvent.geom.isnot(None),
            DetectedEvent.is_fallback_geo == False,
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike("test%"),
        )
        .order_by(DetectedEvent.detected_at.desc())
        .all()
    )
    xml_content = generate_cot_xml(events)
    return Response(content=xml_content, media_type="application/xml")


@router.get("/zip", response_class=Response)
def get_cot_zip_datapackage(
    hours: int = Query(24, ge=1, le=72),
    token_valid: bool = Depends(verify_tactical_token),
    db: Session = Depends(get_db),
):
    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    events = (
        db.query(
            DetectedEvent.id,
            DetectedEvent.incident_id,
            DetectedEvent.event_type,
            DetectedEvent.location_text,
            DetectedEvent.resonance_score,
            DetectedEvent.significance_score,
            DetectedEvent.confidence_score,
            DetectedEvent.sources_count,
            DetectedEvent.is_fallback_geo,
            DetectedEvent.detected_at,
            func.ST_Y(DetectedEvent.geom).label("lat"),
            func.ST_X(DetectedEvent.geom).label("lon"),
        )
        .filter(
            DetectedEvent.geom.isnot(None),
            DetectedEvent.is_fallback_geo == False,
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike("test%"),
        )
        .order_by(DetectedEvent.detected_at.desc())
        .all()
    )
    zip_bytes = generate_cot_datapackage_zip(events)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="iskun_cot_{datetime.datetime.utcnow().strftime("%Y%m%d_%H%M")}.zip"'
        },
    )
