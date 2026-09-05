"""
Aviation ADS-B Strategic Launch Early Warning Module.

Monitors military transport, strategic aviation, and airborne radar nodes (adsb.lol API)
for launch corroboration of Shahed swarms and missile strikes.
"""
import datetime
import json
import logging
import math
import os
import urllib.request
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_KEY_ADSB = "tactical:aviation:adsb_intel_v1"
CACHE_TTL_ADSB = 60  # 1 minute

# Target military types / hex prefixes
MILITARY_AIRCRAFT_PROFILES = {
    "A50": {"role": "ДРЛВ / Повітряний командний пункт", "threat": "CRITICAL", "icon": "radar"},
    "IL76": {"role": "Військово-транспортний (Логістика БпЛА/Ракет)", "threat": "ELEVATED", "icon": "transport"},
    "T95": {"role": "Стратегічний ракетоносець Ту-95МС", "threat": "CRITICAL", "icon": "bomber"},
    "T22M": {"role": "Дальній бомбардувальник Ту-22М3", "threat": "CRITICAL", "icon": "bomber"},
    "MIG31": {"role": "Носій Х-47М2 «Кинджал»", "threat": "CRITICAL", "icon": "fast_jet"},
    "IL20": {"role": "Літак РЕР / РЕБ Іл-20М", "threat": "ELEVATED", "icon": "sigint"},
    "IL22": {"role": "Повітряний пункт управління Іл-22М", "threat": "ELEVATED", "icon": "c2"},
}

LAUNCH_ZONES = [
    {"name": "Приморсько-Ахтарськ", "lat": 46.050, "lng": 38.150, "radius_km": 120.0},
    {"name": "Єйськ", "lat": 46.680, "lng": 38.250, "radius_km": 100.0},
    {"name": "Сеща (Брянська обл.)", "lat": 53.716, "lng": 33.350, "radius_km": 150.0},
    {"name": "Міллерово / Ростов", "lat": 48.950, "lng": 40.300, "radius_km": 150.0},
    {"name": "Чауда / Крим", "lat": 45.010, "lng": 35.840, "radius_km": 100.0},
    {"name": "Курськ (Східний)", "lat": 51.750, "lng": 36.300, "radius_km": 120.0},
]

try:
    import redis
except ImportError:
    redis = None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_live_adsb_military() -> List[dict]:
    """
    Queries adsb.lol open API for military and special flights in Eastern European sector.
    Returns parsed list of candidate military flights.
    """
    url = "https://api.adsb.lol/v2/mil"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OKINT-PRO-C4ISR/3.0 (Defense Intel)"}
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw_ac = data.get("ac", [])
        active_threats = []

        for ac in raw_ac:
            lat = ac.get("lat")
            lon = ac.get("lon")
            if lat is None or lon is None:
                continue

            t_type = (ac.get("t") or "").upper()
            callsign = (ac.get("flight") or "").strip().upper()
            alt_baro = ac.get("alt_baro")
            speed = ac.get("gs") or 0.0
            track = ac.get("track") or 0.0
            hex_code = ac.get("hex") or ""

            # Match against known military types
            matched_profile = None
            for p_code, p_info in MILITARY_AIRCRAFT_PROFILES.items():
                if p_code in t_type or p_code in callsign:
                    matched_profile = {**p_info, "type_code": p_code}
                    break

            # Check distance to any launch zone
            in_launch_zone = None
            for zone in LAUNCH_ZONES:
                dist = haversine_km(lat, lon, zone["lat"], zone["lng"])
                if dist <= zone["radius_km"]:
                    in_launch_zone = {"zone_name": zone["name"], "distance_km": round(dist, 1)}
                    break

            # If military profile matched OR inside high-risk launch zone
            if matched_profile or in_launch_zone:
                active_threats.append({
                    "hex": hex_code,
                    "callsign": callsign or "UNKNOWN_MIL",
                    "aircraft_type": t_type or (matched_profile["type_code"] if matched_profile else "MIL_CONTACT"),
                    "role": matched_profile["role"] if matched_profile else "Невстановлений військовий борт",
                    "threat_level": matched_profile["threat"] if matched_profile else "ELEVATED",
                    "lat": float(lat),
                    "lng": float(lon),
                    "altitude_m": round(alt_baro * 0.3048) if isinstance(alt_baro, (int, float)) else None,
                    "ground_speed_kmh": round(speed * 1.852) if speed else None,
                    "heading_deg": round(track),
                    "near_launch_zone": in_launch_zone["zone_name"] if in_launch_zone else None,
                    "distance_to_launch_hub_km": in_launch_zone["distance_km"] if in_launch_zone else None,
                    "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
                })

        return active_threats

    except Exception as e:
        logger.warning(f"ADSB live military query failed: {e}")
        return []


def get_aviation_intel_summary(force_refresh: bool = False) -> dict:
    """
    Returns summary of military aviation activity with caching.
    """
    r = None
    if redis:
        try:
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            if not force_refresh:
                cached = r.get(CACHE_KEY_ADSB)
                if cached:
                    return json.loads(cached)
        except Exception as e:
            logger.debug(f"Redis adsb cache read error: {e}")

    threats = fetch_live_adsb_military()

    # Determine overall status
    critical_count = sum(1 for t in threats if t.get("threat_level") == "CRITICAL")
    elevated_count = sum(1 for t in threats if t.get("threat_level") == "ELEVATED")

    if critical_count > 0:
        overall_status = "CRITICAL"
        status_label = "🔴 КРИТИЧНО: Зафіксовано стратегічні носії / ДРЛВ РФ"
    elif elevated_count > 0:
        overall_status = "ELEVATED"
        status_label = "🟡 ПІДВИЩЕНО: Активність військово-транспортної авіації"
    else:
        overall_status = "NORMAL"
        status_label = "🟢 НОРМА: Аномальної авіаційної активності не виявлено"

    result = {
        "status": overall_status,
        "status_label": status_label,
        "threat_count": len(threats),
        "critical_count": critical_count,
        "elevated_count": elevated_count,
        "active_aircraft": threats,
        "monitored_launch_zones": [z["name"] for z in LAUNCH_ZONES],
        "source": "adsb.lol Military Feeds",
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    if r:
        try:
            r.setex(CACHE_KEY_ADSB, CACHE_TTL_ADSB, json.dumps(result))
        except Exception as e:
            logger.debug(f"Redis adsb cache write error: {e}")

    return result
