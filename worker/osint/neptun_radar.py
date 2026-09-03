import datetime
import json
import logging
import math
import os
import urllib.request
import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
KYIV_LAT = 50.4501
KYIV_LON = 30.5234
CACHE_KEY = "radar:neptun:live_drones"
CACHE_TTL = 15  # 15 seconds cache


def calculate_distance_km(lat1: float, lon1: float, lat2: float = KYIV_LAT, lon2: float = KYIV_LON) -> float:
    """Haversine distance in km between two GPS coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)


def classify_threat(threat_type: str, text: str) -> tuple[str, str, str]:
    """Classifies raw threat text into (label, color_hex, category)."""
    s = f"{threat_type or ''} {text or ''}".lower()
    if any(k in s for k in ['shahed', 'шахед', 'бпла', 'дрон', 'герань']):
        return 'БПЛА Shahed', '#ff3366', 'drone'
    if any(k in s for k in ['крилат', 'калібр', 'х-101', 'ракет', 'раке', 'missile', 'cruise']):
        return 'Крилата Ракета', '#ff0044', 'missile'
    if any(k in s for k in ['баліст', 'іскандер', 'кинжал', 'кинджал']):
        return 'Балістична Ракета', '#ff00cc', 'ballistic'
    if any(k in s for k in ['каб', 'керована', 'бомб', 'авіабомб']):
        return 'КАБ / Авіабомба', '#ffaa00', 'kab'
    if any(k in s for k in ['розвід', 'zala', 'supercam', 'орлан']):
        return 'Розвідувальний БПЛА', '#00bfff', 'recon'
    return 'Повітряна Ціль', '#ff9900', 'generic'


def get_live_radar_threats(force_refresh: bool = False) -> dict:
    """Fetches live air threats from Neptun API with Redis caching."""
    r_client = None
    try:
        r_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning(f"Neptun radar: Redis connection unavailable: {e}")

    if not force_refresh and r_client:
        try:
            cached = r_client.get(CACHE_KEY)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Neptun radar cache get error: {e}")

    # Fetch from Neptun endpoint
    url = "https://neptun.in.ua/api/data"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OKINT-PRO/2.0 (Tactical Defense Intelligence)",
            "Accept": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Neptun radar live fetch failed: {e}")
        # Return fallback empty state if network fails
        return {
            "count": 0,
            "kyiv_threat_count": 0,
            "ballistic_threat": False,
            "drones": [],
            "source": "Neptun",
            "status": "offline_fallback",
            "updated": datetime.datetime.utcnow().isoformat() + "Z",
        }

    raw_markers = data.get("markers") or data.get("tracks") or []
    ballistic = bool(data.get("ballistic_threat"))

    drones = []
    kyiv_threats = 0

    for m in raw_markers:
        lat = m.get("lat")
        lng = m.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue

        label, color, category = classify_threat(m.get("threat_type"), m.get("text"))
        dist_kyiv = calculate_distance_km(lat, lng)

        # Build trail (last 20 coordinates)
        raw_positions = m.get("positions") or []
        trail = []
        if isinstance(raw_positions, list):
            for p in raw_positions[-20:]:
                if isinstance(p, dict) and "lat" in p and "lng" in p:
                    trail.append([p["lat"], p["lng"]])

        is_kyiv_threat = dist_kyiv <= 180.0
        if is_kyiv_threat:
            kyiv_threats += 1

        drone_obj = {
            "id": str(m.get("id") or m.get("track_id") or f"{lat:.4f}_{lng:.4f}"),
            "label": label,
            "category": category,
            "color": color,
            "threat_type": m.get("threat_type") or category,
            "lat": float(lat),
            "lng": float(lng),
            "heading": float(m.get("course_bearing") or 0),
            "speed_kmh": float(m.get("speed_kmh") or m.get("computed_speed_kmh") or 0),
            "confidence": int(m.get("confidence_0_100") or 0),
            "place": m.get("place") or "",
            "region": m.get("region") or m.get("oblast") or "",
            "text": m.get("text") or "",
            "time": m.get("date") or datetime.datetime.utcnow().isoformat() + "Z",
            "distance_to_kyiv_km": dist_kyiv,
            "is_kyiv_threat": is_kyiv_threat,
            "trail": trail,
        }
        drones.append(drone_obj)

    # Sort drones by distance to Kyiv (closest first)
    drones.sort(key=lambda d: d["distance_to_kyiv_km"])

    result = {
        "count": len(drones),
        "kyiv_threat_count": kyiv_threats,
        "ballistic_threat": ballistic,
        "drones": drones,
        "source": "Neptun (neptun.in.ua)",
        "status": "online",
        "updated": datetime.datetime.utcnow().isoformat() + "Z",
    }

    if r_client:
        try:
            r_client.setex(CACHE_KEY, CACHE_TTL, json.dumps(result))
        except Exception as e:
            logger.warning(f"Neptun radar cache set error: {e}")

    return result
