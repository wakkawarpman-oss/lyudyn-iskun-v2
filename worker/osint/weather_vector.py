"""
Atmospheric Wind Vector & Ground Speed Drift Engine for Drone Interception.

Calculates real aerodynamic ground speed and trajectory drift for Shahed-136/238
at 900-925 hPa (~750m AGL) cruise altitude using Open-Meteo REST API.
"""
import datetime
import json
import logging
import math
import os
import urllib.request
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_KEY_WIND = "tactical:weather:wind_vectors_v1"
CACHE_TTL_WIND = 900  # 15 minutes

DEFENSE_SECTORS = {
    "kyiv": {"name": "Київський сектор", "lat": 50.4501, "lng": 30.5234},
    "chernihiv": {"name": "Чернігівський сектор", "lat": 51.4982, "lng": 31.2893},
    "sumy": {"name": "Сумський сектор", "lat": 50.9077, "lng": 34.7981},
    "poltava": {"name": "Полтавський сектор", "lat": 49.5883, "lng": 34.5514},
    "kharkiv": {"name": "Харківський сектор", "lat": 49.9935, "lng": 36.2304},
    "dnipro": {"name": "Дніпровський сектор", "lat": 48.4647, "lng": 35.0462},
    "zaporizhzhia": {"name": "Запорізький сектор", "lat": 47.8388, "lng": 35.1396},
    "mykolaiv": {"name": "Миколаївський сектор", "lat": 46.9750, "lng": 31.9946},
    "odesa": {"name": "Одеський сектор", "lat": 46.4825, "lng": 30.7233},
    "vinnytsia": {"name": "Вінницький сектор", "lat": 49.2331, "lng": 28.4682},
    "cherkasy": {"name": "Черкаський сектор", "lat": 49.4444, "lng": 32.0598},
    "zhytomyr": {"name": "Житомирський сектор", "lat": 50.2547, "lng": 28.6587},
}

_IN_MEMORY_WIND_CACHE: Dict[str, dict] = {}
_LAST_WIND_FETCH_TIME = None

try:
    import redis
except ImportError:
    redis = None


def compute_wind_drift(
    heading_deg: float,
    air_speed_kmh: float = 185.0,
    wind_deg: float = 0.0,
    wind_speed_kmh: float = 0.0
) -> Dict[str, float]:
    """
    Computes ground speed, drift angle, and headwind/crosswind components.
    wind_deg: Direction from which the wind is blowing (0 = North).
    Wind pushes in direction: (wind_deg + 180) % 360.
    """
    if air_speed_kmh <= 0:
        air_speed_kmh = 185.0

    wind_to_rad = math.radians((wind_deg + 180.0) % 360.0)
    heading_rad = math.radians(heading_deg % 360.0)

    vx_air = air_speed_kmh * math.sin(heading_rad)
    vy_air = air_speed_kmh * math.cos(heading_rad)

    vx_wind = wind_speed_kmh * math.sin(wind_to_rad)
    vy_wind = wind_speed_kmh * math.cos(wind_to_rad)

    vx_ground = vx_air + vx_wind
    vy_ground = vy_air + vy_wind

    ground_speed = math.sqrt(vx_ground**2 + vy_ground**2)
    ground_heading = (math.degrees(math.atan2(vx_ground, vy_ground)) + 360.0) % 360.0

    drift_angle = (ground_heading - heading_deg + 180.0) % 360.0 - 180.0
    speed_delta = ground_speed - air_speed_kmh

    return {
        "air_speed_kmh": round(air_speed_kmh, 1),
        "ground_speed_kmh": round(ground_speed, 1),
        "ground_heading_deg": round(ground_heading, 1),
        "drift_angle_deg": round(drift_angle, 1),
        "speed_delta_kmh": round(speed_delta, 1),
        "wind_speed_kmh": round(wind_speed_kmh, 1),
        "wind_dir_deg": round(wind_deg, 1),
    }


def fetch_sector_wind_live(lat: float, lng: float) -> Tuple[float, float]:
    """
    Fetches wind speed and direction at 900-925 hPa (~750m AGL) from Open-Meteo.
    Short timeout of 2.0s with safe fallback.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat:.4f}&longitude={lng:.4f}&"
        f"current=wind_speed_10m,wind_direction_10m&"
        f"hourly=wind_speed_900hPa,wind_direction_900hPa&"
        f"timezone=Europe%2FKyiv&forecast_days=1"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OKINT-PRO-C4ISR/3.0 (Defense Intel)"}
    )

    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        hourly = data.get("hourly", {})
        w_speeds = hourly.get("wind_speed_900hPa", [])
        w_dirs = hourly.get("wind_direction_900hPa", [])

        if w_speeds and w_dirs:
            current_hour = datetime.datetime.now().hour
            idx = min(current_hour, len(w_speeds) - 1)
            spd = float(w_speeds[idx]) if w_speeds[idx] is not None else 25.0
            deg = float(w_dirs[idx]) if w_dirs[idx] is not None else 180.0
            return spd, deg

        current = data.get("current", {})
        spd_10m = float(current.get("wind_speed_10m") or 15.0)
        deg_10m = float(current.get("wind_direction_10m") or 180.0)
        return round(spd_10m * 1.4, 1), deg_10m

    except Exception as e:
        logger.debug(f"Open-Meteo fallback for ({lat}, {lng}): {e}")
        return 22.0, 315.0


def get_all_sector_winds(force_refresh: bool = False) -> Dict[str, dict]:
    """
    Returns weather vectors for all major defense sectors with caching.
    """
    global _IN_MEMORY_WIND_CACHE, _LAST_WIND_FETCH_TIME
    now = datetime.datetime.utcnow()

    if not force_refresh and _IN_MEMORY_WIND_CACHE and _LAST_WIND_FETCH_TIME:
        if (now - _LAST_WIND_FETCH_TIME).total_seconds() < CACHE_TTL_WIND:
            return _IN_MEMORY_WIND_CACHE

    r = None
    if redis:
        try:
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            if not force_refresh:
                cached = r.get(CACHE_KEY_WIND)
                if cached:
                    _IN_MEMORY_WIND_CACHE = json.loads(cached)
                    _LAST_WIND_FETCH_TIME = now
                    return _IN_MEMORY_WIND_CACHE
        except Exception as e:
            logger.debug(f"Redis wind cache read error: {e}")

    sectors_data = {}
    for key, info in DEFENSE_SECTORS.items():
        speed, direction = fetch_sector_wind_live(info["lat"], info["lng"])
        sectors_data[key] = {
            "sector_key": key,
            "name": info["name"],
            "lat": info["lat"],
            "lng": info["lng"],
            "altitude_level": "900-925 hPa (~750m AGL)",
            "wind_speed_kmh": speed,
            "wind_direction_deg": direction,
            "updated_at": now.isoformat() + "Z",
        }

    _IN_MEMORY_WIND_CACHE = sectors_data
    _LAST_WIND_FETCH_TIME = now

    if r:
        try:
            r.setex(CACHE_KEY_WIND, CACHE_TTL_WIND, json.dumps(sectors_data))
        except Exception as e:
            logger.debug(f"Redis wind cache write error: {e}")

    return sectors_data


def get_closest_sector_wind(lat: float, lng: float, cached_sectors: Optional[Dict[str, dict]] = None) -> dict:
    """Finds the closest defense sector and returns its wind profile efficiently."""
    # First find closest sector geometry
    best_dist = float("inf")
    best_key = "kyiv"
    best_info = DEFENSE_SECTORS["kyiv"]

    for key, info in DEFENSE_SECTORS.items():
        d_lat = lat - info["lat"]
        d_lng = (lng - info["lng"]) * math.cos(math.radians(lat))
        dist = d_lat**2 + d_lng**2
        if dist < best_dist:
            best_dist = dist
            best_key = key
            best_info = info

    # Check cache
    if cached_sectors and best_key in cached_sectors:
        return cached_sectors[best_key]
    if _IN_MEMORY_WIND_CACHE and best_key in _IN_MEMORY_WIND_CACHE:
        return _IN_MEMORY_WIND_CACHE[best_key]

    # Fast on-demand fetch for this single sector
    spd, deg = fetch_sector_wind_live(best_info["lat"], best_info["lng"])
    res = {
        "sector_key": best_key,
        "name": best_info["name"],
        "lat": best_info["lat"],
        "lng": best_info["lng"],
        "altitude_level": "900-925 hPa (~750m AGL)",
        "wind_speed_kmh": spd,
        "wind_direction_deg": deg,
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    _IN_MEMORY_WIND_CACHE[best_key] = res
    return res
