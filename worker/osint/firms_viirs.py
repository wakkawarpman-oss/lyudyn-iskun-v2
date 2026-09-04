"""
NASA FIRMS (Fire Information for Resource Management System) Engine.
Ingests real-time Suomi-NPP VIIRS 375m active fire / thermal anomaly data for Ukraine.
Cross-verifies physical explosions, strikes, and fires with orbital infrared satellite passes.
"""

import os
import csv
import io
import json
import logging
import math
import urllib.request
from datetime import datetime, timezone
from typing import List, Dict, Optional
import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHE_KEY = "firms:viirs:ukraine_anomalies"
CACHE_TTL = 900  # 15 minutes

# NASA VIIRS 375m NRT active fire global 24h feed (open NASA EOSDIS URL, zero-key)
NASA_FIRMS_VIIRS_CSV_URL = (
    "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv"
)

# Geographic Bounding Box for Ukraine
UKRAINE_BBOX = {
    "min_lat": 44.0,
    "max_lat": 52.5,
    "min_lon": 22.0,
    "max_lon": 40.5
}


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS coordinates in kilometers."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 2)


def parse_firms_time(acq_date_str: str, acq_time_str: str) -> Optional[datetime]:
    """
    Parses NASA FIRMS date and time strings (e.g. '2026-09-03', '0215')
    into a timezone-aware UTC datetime.
    """
    try:
        t_clean = acq_time_str.zfill(4)
        hour = int(t_clean[:2])
        minute = int(t_clean[2:4])
        dt = datetime.strptime(acq_date_str, "%Y-%m-%d")
        return dt.replace(hour=hour, minute=minute, tzinfo=timezone.utc)
    except Exception as exc:
        logger.warning(f"Error parsing FIRMS time {acq_date_str} {acq_time_str}: {exc}")
        return None


def fetch_ukraine_thermal_anomalies(force_refresh: bool = False) -> Dict:
    """
    Fetches 24-hour VIIRS thermal anomalies filtered to Ukraine territory.
    Caches parsed results in Redis for 15 minutes.
    """
    r = None
    try:
        r = redis.Redis.from_url(REDIS_URL)
        if not force_refresh:
            cached = r.get(CACHE_KEY)
            if cached:
                return json.loads(cached)
    except Exception as exc:
        logger.warning(f"Redis cache check failed in firms_viirs: {exc}")

    anomalies: List[Dict] = []
    server_time = datetime.now(timezone.utc).isoformat()

    if ("PYTEST_CURRENT_TEST" in os.environ or os.getenv("TESTING") == "true") and not force_refresh:
        return {
            "status": "test_mode",
            "source": "NASA FIRMS (Suomi-NPP VIIRS)",
            "count": 0,
            "updated_at": server_time,
            "anomalies": []
        }

    try:
        req = urllib.request.Request(
            NASA_FIRMS_VIIRS_CSV_URL,
            headers={"User-Agent": "LyudynIskun-OSINT/2.0 (Defense Intel Pipeline)"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (ValueError, KeyError):
                continue

            # Filter Ukraine Bounding Box
            if not (UKRAINE_BBOX["min_lat"] <= lat <= UKRAINE_BBOX["max_lat"] and
                    UKRAINE_BBOX["min_lon"] <= lon <= UKRAINE_BBOX["max_lon"]):
                continue

            bright_ti4 = float(row.get("bright_ti4", 0.0))
            bright_ti5 = float(row.get("bright_ti5", 0.0))
            frp = float(row.get("frp", 0.0))  # Fire Radiative Power (MW)
            confidence = str(row.get("confidence", "nominal")).lower()
            acq_date = row.get("acq_date", "")
            acq_time = row.get("acq_time", "")
            daynight = str(row.get("daynight", "D")).upper()

            dt = parse_firms_time(acq_date, acq_time)
            iso_str = dt.isoformat() if dt else f"{acq_date}T{acq_time[:2]}:{acq_time[2:]}:00Z"

            anomalies.append({
                "lat": lat,
                "lon": lon,
                "brightness_k": bright_ti4,
                "bright_ti5_k": bright_ti5,
                "frp_mw": frp,
                "confidence": confidence,
                "daynight": daynight,
                "acq_time": iso_str,
                "satellite": "Suomi-NPP VIIRS (375m)"
            })

        result = {
            "status": "live",
            "source": "NASA FIRMS (Suomi-NPP VIIRS)",
            "count": len(anomalies),
            "updated_at": server_time,
            "anomalies": anomalies
        }

        if r:
            try:
                r.setex(CACHE_KEY, CACHE_TTL, json.dumps(result))
            except Exception as e:
                logger.warning(f"Failed to cache FIRMS anomalies: {e}")

        return result

    except Exception as exc:
        logger.error(f"Failed to fetch NASA FIRMS feed: {exc}")
        return {
            "status": "offline_fallback",
            "source": "NASA FIRMS (Suomi-NPP VIIRS)",
            "count": 0,
            "updated_at": server_time,
            "anomalies": []
        }


def find_nearby_thermal_anomaly(
    lat: float,
    lon: float,
    event_dt: Optional[datetime] = None,
    max_distance_km: float = 7.0,
    max_hours_diff: float = 8.0
) -> Optional[Dict]:
    """
    Cross-references an event location and timestamp with NASA orbital thermal anomalies.
    Returns the nearest matching anomaly if within spatial and temporal thresholds.
    """
    feed = fetch_ukraine_thermal_anomalies(force_refresh=False)
    anomalies = feed.get("anomalies", [])
    if not anomalies:
        return None

    best_match = None
    min_dist = 999999.0

    target_dt = event_dt or datetime.now(timezone.utc)
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)

    for a in anomalies:
        dist = haversine_distance_km(lat, lon, a["lat"], a["lon"])
        if dist <= max_distance_km:
            # Check time correlation if timestamp available
            if a.get("acq_time"):
                try:
                    a_dt = datetime.fromisoformat(a["acq_time"].replace("Z", "+00:00"))
                    time_diff = abs((target_dt - a_dt).total_seconds()) / 3600.0
                    if time_diff > max_hours_diff:
                        continue
                except Exception:
                    pass

            if dist < min_dist:
                min_dist = dist
                best_match = dict(a)
                best_match["distance_km"] = dist

    return best_match
