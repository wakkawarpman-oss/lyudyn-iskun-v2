"""
Terrain Line-of-Sight (LoS) & Radio-Horizon Masking Engine.

Implements:
1. 4/3 Effective Earth Radius model (R_eff = 8500 km) for atmospheric refraction.
2. Radio horizon boundary estimation: d = 4.123 * (sqrt(h_radar) + sqrt(h_target)).
3. Topographic river canyon masking corridors (Dnipro, Desna, Southern Buh, Dniester, Siverskyi Donets)
   where low-flying Shahed-136/238 drones (30-100m AGL) drop below radar line-of-sight.
"""
import math
import logging
import os
import json
try:
    import redis
except ImportError:
    redis = None
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_redis_client = None

def _get_redis_client():
    global _redis_client
    if _redis_client is None and redis is not None:
        try:
            _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1.0)
        except Exception as e:
            logger.debug("Terrain LoS Redis connection skipped: %s", e)
            _redis_client = None
    return _redis_client

# Atmospheric refraction constant (k = 4/3)
EARTH_RADIUS_KM = 6371.0
K_FACTOR = 4.0 / 3.0
R_EFFECTIVE_KM = EARTH_RADIUS_KM * K_FACTOR  # ~8494.7 km (~8500 km)
HORIZON_CONSTANT = math.sqrt(2.0 * R_EFFECTIVE_KM * 1000.0) / 1000.0  # ~4.122 km / sqrt(m)

# Representative regional 3D air surveillance radar nodes (e.g. 36D6, 79K6, P-18)
REGIONAL_RADAR_NODES = [
    {"name": "РЛС Північ-1 (Київщина)", "lat": 50.4501, "lng": 30.5234, "terrain_elev_m": 160.0, "mast_m": 25.0},
    {"name": "РЛС Центр-2 (Полтава)", "lat": 49.5883, "lng": 34.5514, "terrain_elev_m": 155.0, "mast_m": 20.0},
    {"name": "РЛС Південь-3 (Одещина)", "lat": 46.4825, "lng": 30.7233, "terrain_elev_m": 50.0, "mast_m": 25.0},
    {"name": "РЛС Схід-4 (Дніпро)", "lat": 48.4647, "lng": 35.0462, "terrain_elev_m": 120.0, "mast_m": 20.0},
    {"name": "РЛС Запоріжжя-5", "lat": 47.8388, "lng": 35.1396, "terrain_elev_m": 85.0, "mast_m": 20.0},
    {"name": "РЛС Поділля-6 (Умань)", "lat": 48.7500, "lng": 30.2200, "terrain_elev_m": 215.0, "mast_m": 20.0},
    {"name": "РЛС Слобожанщина-7 (Харків)", "lat": 49.9935, "lng": 36.2304, "terrain_elev_m": 140.0, "mast_m": 20.0},
    {"name": "РЛС Прибужжя-8 (Миколаїв)", "lat": 46.9750, "lng": 31.9946, "terrain_elev_m": 45.0, "mast_m": 20.0},
]

# Major Ukrainian River Canyon Corridors where UAVs utilize terrain masking
RIVER_CORRIDORS = [
    {
        "name": "Дніпровський каньйон та заплава",
        "river": "Дніпро",
        "points": [
            (51.30, 30.50), (50.50, 30.55), (50.15, 30.75), (49.75, 31.46),
            (49.44, 32.06), (49.06, 33.42), (48.51, 34.61), (48.46, 35.04),
            (47.83, 35.14), (47.56, 34.39), (46.85, 33.40), (46.63, 32.61)
        ],
        "canyon_depth_m": 85.0,
        "masking_buffer_km": 12.0
    },
    {
        "name": "Русло р. Десна (Чернігів-Київ)",
        "river": "Десна",
        "points": [
            (52.01, 33.27), (51.80, 32.50), (51.49, 31.29), (50.95, 30.88), (50.55, 30.60)
        ],
        "canyon_depth_m": 65.0,
        "masking_buffer_km": 8.0
    },
    {
        "name": "Русло р. Південний Буг",
        "river": "Південний Буг",
        "points": [
            (49.42, 26.98), (49.23, 28.47), (48.80, 29.50), (48.04, 30.85),
            (47.57, 31.33), (46.97, 31.99)
        ],
        "canyon_depth_m": 75.0,
        "masking_buffer_km": 9.0
    },
    {
        "name": "Дністровський каньйон",
        "river": "Дністер",
        "points": [
            (49.12, 24.73), (48.85, 25.20), (48.64, 25.73), (48.45, 27.79), (48.15, 28.25)
        ],
        "canyon_depth_m": 120.0,
        "masking_buffer_km": 10.0
    },
    {
        "name": "Русло р. Сіверський Донець",
        "river": "Сіверський Донець",
        "points": [
            (50.25, 36.90), (49.83, 36.68), (49.60, 36.35), (49.12, 37.28), (48.98, 37.90)
        ],
        "canyon_depth_m": 70.0,
        "masking_buffer_km": 8.0
    }
]


def haversine_dist_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two GPS coordinates in kilometers."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    return r * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def compute_radio_horizon_km(radar_antenna_h_m: float, target_alt_m: float) -> float:
    """
    Computes optical / radio horizon distance in km accounting for 4/3 atmospheric refraction:
    D = 4.122 * (sqrt(h_radar) + sqrt(h_target))
    """
    h_r = max(0.1, radar_antenna_h_m)
    h_t = max(0.1, target_alt_m)
    return round(HORIZON_CONSTANT * (math.sqrt(h_r) + math.sqrt(h_t)), 1)


def distance_point_to_segment_km(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Approximate distance in km from point (px, py) to line segment (x1, y1) - (x2, y2)."""
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return haversine_dist_km(px, py, x1, y1)

    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_lat = x1 + t * dx
    proj_lng = y1 + t * dy
    return haversine_dist_km(px, py, proj_lat, proj_lng)


def find_nearest_river_corridor(lat: float, lng: float) -> Optional[dict]:
    """Finds if a target is traversing along any known river canyon corridor with spatial grid caching."""
    grid_lat = round(lat, 3)
    grid_lng = round(lng, 3)
    cache_key = f"tactical:cache:river_mask:{grid_lat}_{grid_lng}"

    r = _get_redis_client()
    if r is not None:
        try:
            cached = r.get(cache_key)
            if cached == "NULL":
                return None
            elif cached:
                return json.loads(cached)
        except Exception as e:
            logger.debug("Redis read failed for %s: %s", cache_key, e)

    closest_corridor = None
    min_dist = float('inf')

    for corridor in RIVER_CORRIDORS:
        pts = corridor['points']
        for i in range(len(pts) - 1):
            p1 = pts[i]
            p2 = pts[i + 1]
            dist = distance_point_to_segment_km(lat, lng, p1[0], p1[1], p2[0], p2[1])
            if dist < min_dist:
                min_dist = dist
                closest_corridor = {
                    'corridor_name': corridor['name'],
                    'river': corridor['river'],
                    'canyon_depth_m': corridor['canyon_depth_m'],
                    'masking_buffer_km': corridor['masking_buffer_km'],
                    'distance_to_river_km': round(dist, 1)
                }

    result = None
    if closest_corridor and closest_corridor['distance_to_river_km'] <= closest_corridor['masking_buffer_km']:
        result = closest_corridor

    if r is not None:
        try:
            if result:
                r.set(cache_key, json.dumps(result), ex=3600)
            else:
                r.set(cache_key, "NULL", ex=3600)
        except Exception as e:
            logger.debug("Redis write failed for %s: %s", cache_key, e)

    return result


def evaluate_terrain_masking(lat: float, lng: float, target_alt_agl_m: float = 60.0) -> dict:
    """
    Evaluates whether an aerial target is obscured by terrain masking or radio-horizon cutoff.
    """
    river_info = find_nearest_river_corridor(lat, lng)

    nearest_radar = None
    min_radar_dist = float('inf')
    closest_horizon = 0.0

    for r in REGIONAL_RADAR_NODES:
        dist = haversine_dist_km(lat, lng, r['lat'], r['lng'])
        radar_eff_h = r['terrain_elev_m'] + r['mast_m']
        horizon = compute_radio_horizon_km(radar_eff_h, target_alt_agl_m)

        if dist < min_radar_dist:
            min_radar_dist = dist
            nearest_radar = r['name']
            closest_horizon = horizon

    is_masked = False
    masking_type = 'NONE'
    directive = '🟢 ПРЯМА ВИДИМІСТЬ РЛС (LoS Clear)'

    if river_info and target_alt_agl_m <= (river_info['canyon_depth_m'] + 35.0):
        is_masked = True
        masking_type = 'RIVER_CANYON'
        directive = f'⛰️ ТАКТИЧНЕ МАСКУВАННЯ: політ у річищі ({river_info["river"]}), висота {int(target_alt_agl_m)}м нижче берегового схилу'
    elif min_radar_dist > closest_horizon:
        is_masked = True
        masking_type = 'RADIO_HORIZON_SHADOW'
        directive = f'📡 РАДІОГОРИЗОНТ: Ціль нижче горизонту {nearest_radar} ({round(min_radar_dist, 1)} км > {closest_horizon} км)'

    return {
        'is_terrain_masked': is_masked,
        'masking_type': masking_type,
        'river_corridor': river_info['corridor_name'] if river_info else None,
        'river_distance_km': river_info['distance_to_river_km'] if river_info else None,
        'nearest_radar': nearest_radar,
        'dist_to_radar_km': round(min_radar_dist, 1),
        'radio_horizon_km': closest_horizon,
        'horizon_delta_km': round(min_radar_dist - closest_horizon, 1),
        'target_alt_agl_m': target_alt_agl_m,
        'directive': directive
    }
