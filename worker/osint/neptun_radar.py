import datetime
import json
import logging
import math
import os
import urllib.request
import redis
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
NEPTUN_FEED_URL = "https://neptun.in.ua/api/data"
OBLAST_CENTERS = {
    "kyiv_city": (50.4501, 30.5234, 60.0),
    "kyiv_oblast": (50.3500, 30.2000, 130.0),
    "kyiv": (50.4501, 30.5234, 130.0),
    "dnipropetrovsk": (48.4647, 35.0462, 140.0),
    "zaporizhzhia": (47.8388, 35.1396, 140.0),
    "kharkiv": (49.9935, 36.2304, 140.0),
    "odesa": (46.4825, 30.7233, 140.0),
    "mykolaiv": (46.9750, 31.9946, 140.0),
    "poltava": (49.5883, 34.5514, 140.0),
    "sumy": (50.9077, 34.7981, 140.0),
    "chernihiv": (51.4982, 31.2893, 140.0),
}
KYIV_LAT = 50.4501
KYIV_LON = 30.5234
DNIPRO_LAT = 48.4647
DNIPRO_LON = 35.0462
ZAPORIZHZHIA_LAT = 47.8388
ZAPORIZHZHIA_LON = 35.1396

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


def get_live_radar_threats(force_refresh: bool = False, oblast: Optional[str] = None) -> dict:
    """
    Polls the live Neptun tactical feed and returns processed radar tracks.
    Optionally filters by specific oblast.
    """
    raw_json = None
    r = None
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        if not force_refresh:
            raw_json = r.get(CACHE_KEY)
    except Exception as e:
        logger.warning(f"Redis cache check failed in neptun_radar: {e}")

    if raw_json:
        try:
            cached_res = json.loads(raw_json)
            if oblast and oblast != "all":
                filtered_drones = [
                    d for d in cached_res.get("drones", [])
                    if oblast in d.get("relevant_oblasts", [])
                ]
                return {
                    **cached_res,
                    "drones": filtered_drones,
                    "count": len(filtered_drones)
                }
            return cached_res
        except Exception:
            pass

    # Fetch live from Neptun feed
    req = urllib.request.Request(
        NEPTUN_FEED_URL,
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
    oblast_threat_counts = {ob: 0 for ob in OBLAST_CENTERS}

    for m in raw_markers:
        lat = m.get("lat")
        lng = m.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue

        label, color, category = classify_threat(m.get("threat_type"), m.get("text"))
        dist_kyiv = calculate_distance_km(lat, lng, KYIV_LAT, KYIV_LON)
        dist_dnipro = calculate_distance_km(lat, lng, DNIPRO_LAT, DNIPRO_LON)
        dist_zp = calculate_distance_km(lat, lng, ZAPORIZHZHIA_LAT, ZAPORIZHZHIA_LON)

        # Calculate proximity to each oblast center
        relevant_obs = []
        for ob_code, (c_lat, c_lon, max_d) in OBLAST_CENTERS.items():
            d_km = calculate_distance_km(lat, lng, c_lat, c_lon)
            if d_km <= max_d:
                relevant_obs.append(ob_code)
                oblast_threat_counts[ob_code] = oblast_threat_counts.get(ob_code, 0) + 1

        # Build trail (last 20 coordinates)
        raw_positions = m.get("positions") or []
        trail = []
        if isinstance(raw_positions, list):
            for p in raw_positions[-20:]:
                if isinstance(p, dict) and "lat" in p and "lng" in p:
                    trail.append([p["lat"], p["lng"]])

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
            "distance_to_dnipro_km": dist_dnipro,
            "distance_to_zaporizhzhia_km": dist_zp,
            "is_kyiv_threat": "kyiv_city" in relevant_obs or "kyiv_oblast" in relevant_obs,
            "is_dnipro_threat": "dnipropetrovsk" in relevant_obs,
            "is_zaporizhzhia_threat": "zaporizhzhia" in relevant_obs,
            "relevant_oblasts": relevant_obs,
            "trail": trail,
        }
        drones.append(drone_obj)

    # Sort drones by distance to Kyiv (closest first)
    drones.sort(key=lambda d: d["distance_to_kyiv_km"])

    result = {
        "count": len(drones),
        "kyiv_threat_count": oblast_threat_counts.get("kyiv_city", 0),
        "dnipro_threat_count": oblast_threat_counts.get("dnipropetrovsk", 0),
        "zaporizhzhia_threat_count": oblast_threat_counts.get("zaporizhzhia", 0),
        "oblast_threat_counts": oblast_threat_counts,
        "ballistic_threat": ballistic,
        "drones": drones,
        "source": "Neptun (neptun.in.ua)",
        "status": "online",
        "updated": datetime.datetime.utcnow().isoformat() + "Z",
    }

    if r:
        try:
            r.setex(CACHE_KEY, CACHE_TTL, json.dumps(result))
        except Exception as e:
            logger.warning(f"Neptun radar cache set error: {e}")

    # Return filtered by oblast if requested
    if oblast and oblast != "all":
        filtered_drones = [d for d in drones if oblast in d.get("relevant_oblasts", [])]
        return {
            **result,
            "drones": filtered_drones,
            "count": len(filtered_drones)
        }

    return result
