"""
Router: api.routes.openwebui_tools
Exposes structured Function Calling / Tools endpoints for Open WebUI and AI Agents.
"""

from fastapi import APIRouter, Query
from typing import Optional, Dict, Any

router = APIRouter(prefix="/api/v1/tools", tags=["OpenWebUI Tools"])


@router.get("/manifest")
def get_tools_manifest() -> Dict[str, Any]:
    """
    Returns Open WebUI / Agent tool schemas for automated tool registration.
    """
    return {
        "tools": [
            {
                "name": "c4isr_radar_threats",
                "description": "Retrieves live airborne targets (Shahed/Geran drones, cruise missiles) from Neptun military radar across Ukraine.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "oblast": {"type": "string", "description": "Optional oblast code (e.g. kharkiv, kyiv_city, dnipropetrovsk)"}
                    }
                }
            },
            {
                "name": "c4isr_alert_status",
                "description": "Checks the verified air raid alert status and 'Відбій' (all-clear) signal for a given oblast to determine if civilian transport and shops are open.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "oblast": {"type": "string", "description": "Oblast code (e.g. kyiv_city, odesa, lviv, kharkiv)"}
                    },
                    "required": ["oblast"]
                }
            },
            {
                "name": "c4isr_similar_channels",
                "description": "Discovers related Telegram channels and Russian propaganda networks using MTProto channel recommendations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Telegram username or channel name (e.g. rybar, kpszsu)"}
                    },
                    "required": ["channel"]
                }
            },
            {
                "name": "c4isr_infrastructure_proximity",
                "description": "Checks proximity of target coordinates to 192 high-value Ukrainian energy sub-stations (750kV), defense factories, and transport hubs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Target latitude"},
                        "lon": {"type": "number", "description": "Target longitude"},
                        "radius_km": {"type": "number", "description": "Search radius in kilometers", "default": 5.0}
                    },
                    "required": ["lat", "lon"]
                }
            },
            {
                "name": "c4isr_apt_threat_scan",
                "description": "Analyzes incident text for MITRE ATT&CK TTPs and Russian cyber-kinetic warfare groups (Gamaredon, Sandworm, Volt Typhoon).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Incident report or news text to analyze"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "c4isr_verify_address",
                "description": "Extracts street-level address, geocodes it, and performs live multi-sensor verification (Neptun radar drones, shelters, critical infrastructure proximity, alert status, and confidence score 0-100%).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Incident report, address or coordinates to verify (e.g. 'вул. Соборна, 57 у Рівному' or '50.4501, 30.5234')"},
                        "city": {"type": "string", "description": "Optional default city context"}
                    },
                    "required": ["text"]
                }
            }
        ]
    }


@router.get("/radar/threats")
def execute_radar_threats(oblast: Optional[str] = None):
    """Executes live radar threat search."""
    from worker.osint.neptun_radar import get_live_radar_threats
    return get_live_radar_threats(oblast=oblast)


@router.get("/alerts/check")
def execute_alert_check(oblast: str = Query("kyiv_city")):
    """Executes alert and all-clear check."""
    from bot.alert_monitor import get_current_kyiv_alert_status
    return get_current_kyiv_alert_status(oblast=oblast)


@router.get("/channels/similar")
def execute_similar_channels(channel: str = Query(..., description="Channel username")):
    """Discovers similar channels and bot clusters."""
    from worker.osint.similar_channels import discover_similar_channels_sync
    return {
        "channel": channel,
        "results": discover_similar_channels_sync(channel)
    }


@router.get("/infrastructure/proximity")
def execute_poi_proximity(lat: float, lon: float, radius_km: float = 5.0):
    """Checks proximity to critical infrastructure."""
    from worker.geo_extractors.poi_matcher import find_nearby_critical_infrastructure
    pois = find_nearby_critical_infrastructure(lat, lon, max_radius_m=radius_km * 1000.0)
    return {
        "target": {"lat": lat, "lon": lon},
        "radius_km": radius_km,
        "nearby_critical_pois": [
            {
                "poi_id": p.poi_id,
                "name": p.name,
                "category": p.category,
                "distance_m": p.distance_m
            }
            for p in pois
        ]
    }


@router.post("/apt/scan")
def execute_apt_scan(payload: Dict[str, str]):
    """Scans text for APT threats."""
    from worker.osint.apt_matcher import analyze_threat_actors
    text = payload.get("text", "")
    return analyze_threat_actors(text)


@router.post("/verify/address")
def execute_verify_address(payload: Dict[str, Any]):
    """Executes live address extraction and multi-sensor target verification."""
    from dataclasses import asdict
    from worker.verification.live_target_verifier import LiveTargetVerifier

    text = payload.get("text", "")
    default_city = payload.get("city")
    report = LiveTargetVerifier.verify(text, default_city=default_city)
    return asdict(report)
