"""
Acoustic Sensor Gateway & Telemetry Breadcrumbs Module.

Processes microphone array detections (Sky Fortress, Zvook, Mobile Apps)
in the 80-250 Hz range (MD550 engine & 2-blade modulation) to corroborate
low-altitude drone tracks masked from radar horizon.
"""
import datetime
import json
import logging
import math
import os
import uuid
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_KEY_ACOUSTIC = "tactical:acoustic:active_hits_v1"
CACHE_TTL_ACOUSTIC = 300  # 5 minutes

_IN_MEMORY_ACOUSTIC_HITS: List[dict] = []

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


def calculate_speed_of_sound(temp_celsius: float = 15.0) -> float:
    """
    Calculates temperature-compensated speed of sound in dry air:
    c = 331.3 * sqrt(1.0 + T / 273.15) m/s
    """
    return round(331.3 * math.sqrt(max(0.0, 1.0 + float(temp_celsius) / 273.15)), 2)


def calculate_tdoa_propagation_time_sec(distance_km: float, temp_celsius: float = 15.0) -> float:
    """
    Calculates acoustic signal propagation time from drone position to sensor:
    t = distance_m / c(T)
    """
    c = calculate_speed_of_sound(temp_celsius)
    distance_m = distance_km * 1000.0
    return round(distance_m / max(1.0, c), 4)


def record_acoustic_hit(
    lat: float,
    lng: float,
    sensor_id: str,
    azimuth: Optional[float] = None,
    snr_db: float = 18.5,
    source: str = "Sky Fortress (Небесна Фортеця)",
    confidence: int = 88,
    drone_frequency_hz: float = 142.0
) -> dict:
    """
    Registers an acoustic detection hit from ground microphone network.
    """
    global _IN_MEMORY_ACOUSTIC_HITS
    hit = {
        "hit_id": str(uuid.uuid4())[:8],
        "sensor_id": sensor_id,
        "source": source,
        "lat": round(float(lat), 5),
        "lng": round(float(lng), 5),
        "azimuth": round(float(azimuth), 1) if azimuth is not None else None,
        "snr_db": round(float(snr_db), 1),
        "confidence": int(confidence),
        "frequency_hz": round(float(drone_frequency_hz), 1),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "ttl_sec": 180,
    }

    # In-memory buffer update
    now = datetime.datetime.utcnow()
    _IN_MEMORY_ACOUSTIC_HITS = [
        h for h in _IN_MEMORY_ACOUSTIC_HITS
        if (now - datetime.datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)).total_seconds() <= CACHE_TTL_ACOUSTIC
    ]
    _IN_MEMORY_ACOUSTIC_HITS.append(hit)

    if redis:
        try:
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            hits_raw = r.get(CACHE_KEY_ACOUSTIC)
            hits = json.loads(hits_raw) if hits_raw else []

            valid_hits = []
            for h in hits:
                try:
                    t = datetime.datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
                    if (now - t).total_seconds() <= CACHE_TTL_ACOUSTIC:
                        valid_hits.append(h)
                except Exception:
                    pass

            valid_hits.append(hit)
            r.setex(CACHE_KEY_ACOUSTIC, CACHE_TTL_ACOUSTIC, json.dumps(valid_hits))
        except Exception as e:
            logger.debug(f"Redis acoustic hit write error: {e}")

    return hit


def get_active_acoustic_hits() -> List[dict]:
    """Returns active acoustic detection pings for map visualization."""
    now = datetime.datetime.utcnow()
    hits_to_use = _IN_MEMORY_ACOUSTIC_HITS

    if redis:
        try:
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            hits_raw = r.get(CACHE_KEY_ACOUSTIC)
            if hits_raw:
                hits_to_use = json.loads(hits_raw)
        except Exception as e:
            logger.debug(f"Redis get acoustic hits fallback: {e}")

    valid = []
    for h in hits_to_use:
        try:
            t = datetime.datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
            age_sec = (now - t).total_seconds()
            if age_sec <= CACHE_TTL_ACOUSTIC:
                h_copy = dict(h)
                h_copy["age_seconds"] = int(age_sec)
                valid.append(h_copy)
        except Exception:
            pass
    return valid


def corroborate_drone_with_acoustics(
    drone_lat: float,
    drone_lng: float,
    max_radius_km: float = 22.0,
    temp_celsius: float = 15.0
) -> dict:
    """
    Checks if an active drone position is corroborated by nearby microphone hits,
    with weather-compensated TDoA acoustic propagation physics.
    """
    hits = get_active_acoustic_hits()
    nearby_sensors = []
    c_sound = calculate_speed_of_sound(temp_celsius)

    for h in hits:
        d = haversine_km(drone_lat, drone_lng, h["lat"], h["lng"])
        if d <= max_radius_km:
            delay_sec = calculate_tdoa_propagation_time_sec(d, temp_celsius)
            nearby_sensors.append({
                "sensor_id": h["sensor_id"],
                "source": h["source"],
                "distance_km": round(d, 1),
                "azimuth": h.get("azimuth"),
                "frequency_hz": h.get("frequency_hz", 142.0),
                "snr_db": h.get("snr_db", 18.0),
                "tdoa_delay_sec": delay_sec,
                "speed_of_sound_ms": c_sound,
            })

    return {
        "corroborated": len(nearby_sensors) > 0,
        "sensor_count": len(nearby_sensors),
        "speed_of_sound_ms": c_sound,
        "temp_celsius": float(temp_celsius),
        "sensors": nearby_sensors,
    }
