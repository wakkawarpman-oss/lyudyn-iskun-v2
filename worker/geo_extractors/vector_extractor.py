"""Deterministic Threat Vector Extractor for Kyiv & Oblast.

Computes a bearing/distance/ETA from a SINGLE message when it names both an
origin and a destination (e.g. "Шахеди повз Обухів у напрямку Києва") — not
a Kalman filter. A real statistical tracker needs the data-association
problem solved first (which sequential messages describe the same physical
object), which this codebase doesn't have; this sidesteps that entirely by
never trying to link separate messages into a track.

Deliberately returns None whenever the text doesn't name two resolvable
places (e.g. "з півдня області" — a direction, not a place) rather than
guessing a vector from an unclear message.
"""
import math
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from geopy.distance import geodesic

from worker.canonical_geo import CANONICAL_TOPONYMS, resolve_canonical_toponym

EARTH_RADIUS_KM = 6371.0

# (label, km/h). Ballistic is a rough approximation — a straight-line
# constant-speed model doesn't really describe a ballistic trajectory, but
# it gives a conservative "minutes, not hours" order-of-magnitude signal.
WEAPON_SPEED_TABLE = [
    (("шахед", "дрон", "бпла", "мопед", "geran"), ("БпЛА (Shahed-136)", 170.0)),
    (("ракета", "калібр", "х-101", "крилат"), ("Крилата ракета", 800.0)),
    (("іскандер", "кинджал", "балістик"), ("Балістика (наближено)", 3000.0)),
]
DEFAULT_WEAPON = ("Невідомий засіб (оцінка БпЛА)", 170.0)

DESTINATION_PATTERNS = [
    r'\bз\s+([^,\n]+?)\s+курсом\s+на\s+([^,.\n;]+)',
    r'\bвід\s+([^,\n]+?)\s+курсом\s+на\s+([^,.\n;]+)',
    r'\bповз\s+([^,\n]+?)\s+(?:у\s+напрямку|в\s+напрямку|напрямком|в\s+бік|у\s+бік)\s+([^,.\n;]+)',
]


@dataclass
class ThreatVector:
    origin_name: str
    destination_name: str
    bearing_deg: float
    distance_km: float
    weapon_label: str
    speed_kmh: float
    eta_minutes: float
    next_landmark: Optional[str] = None
    next_landmark_eta_minutes: Optional[float] = None


def detect_weapon(text: str) -> Tuple[str, float]:
    t_lower = (text or "").lower()
    for keywords, (label, speed) in WEAPON_SPEED_TABLE:
        if any(kw in t_lower for kw in keywords):
            return label, speed
    return DEFAULT_WEAPON


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, in degrees (0-360, 0=North)."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    delta_lon = math.radians(lon2 - lon1)
    x = math.sin(delta_lon) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(delta_lon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def project_point(lat: float, lon: float, bearing_deg: float, distance_km: float) -> Tuple[float, float]:
    """Destination point given a start point, bearing, and distance (spherical Earth)."""
    lat_r, lon_r, bearing_r = math.radians(lat), math.radians(lon), math.radians(bearing_deg)
    angular_dist = distance_km / EARTH_RADIUS_KM

    lat2_r = math.asin(
        math.sin(lat_r) * math.cos(angular_dist) + math.cos(lat_r) * math.sin(angular_dist) * math.cos(bearing_r)
    )
    lon2_r = lon_r + math.atan2(
        math.sin(bearing_r) * math.sin(angular_dist) * math.cos(lat_r),
        math.cos(angular_dist) - math.sin(lat_r) * math.sin(lat2_r),
    )
    return math.degrees(lat2_r), math.degrees(lon2_r)


def find_nearest_kyiv_district(lat: float, lon: float, max_km: float = 5.0) -> Optional[Tuple[str, float]]:
    """Nearest Kyiv city district centroid to (lat, lon), within max_km."""
    best = None
    for entry in CANONICAL_TOPONYMS.values():
        if not entry or entry.get("type") != "district":
            continue
        dist = geodesic((lat, lon), (entry["lat"], entry["lon"])).km
        if dist <= max_km and (best is None or dist < best[1]):
            best = (entry["canonical"], dist)
    return best


def extract_threat_vector(text: str) -> Optional[ThreatVector]:
    if not text:
        return None

    for pattern in DESTINATION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        origin_span, dest_span = match.group(1), match.group(2)
        origin_name, origin_lat, origin_lon, _ = resolve_canonical_toponym(origin_span)
        dest_name, dest_lat, dest_lon, _ = resolve_canonical_toponym(dest_span)

        # Both ends need SOME coordinate — a direction like "з півдня
        # області" resolves to nothing at all (lat/lon stay None), so we
        # decline rather than guess. Deliberately NOT requiring
        # is_fallback=False here: that flag marks a region-level match
        # (e.g. "Київ" the whole city) as too vague to PIN AN INCIDENT to on
        # the map, but "heading toward Kyiv" as a whole is still a
        # perfectly meaningful vector destination — probably the single
        # most common real phrasing ("курсом на Київ").
        if origin_lat is None or origin_lon is None or dest_lat is None or dest_lon is None:
            continue

        bearing = calculate_bearing(origin_lat, origin_lon, dest_lat, dest_lon)
        distance_km = geodesic((origin_lat, origin_lon), (dest_lat, dest_lon)).km
        weapon_label, speed_kmh = detect_weapon(text)
        eta_minutes = (distance_km / speed_kmh) * 60 if speed_kmh else 0.0

        next_landmark = None
        next_landmark_eta = None
        # Project further along the same bearing looking for a Kyiv city
        # district — every 5km up to 40km past the named destination.
        for extra_km in range(5, 45, 5):
            proj_lat, proj_lon = project_point(dest_lat, dest_lon, bearing, extra_km)
            hit = find_nearest_kyiv_district(proj_lat, proj_lon, max_km=5.0)
            if hit:
                landmark_name, _ = hit
                if landmark_name != dest_name:
                    next_landmark = landmark_name
                    next_landmark_eta = ((distance_km + extra_km) / speed_kmh) * 60 if speed_kmh else None
                break

        return ThreatVector(
            origin_name=origin_name,
            destination_name=dest_name,
            bearing_deg=round(bearing, 1),
            distance_km=round(distance_km, 1),
            weapon_label=weapon_label,
            speed_kmh=speed_kmh,
            eta_minutes=round(eta_minutes, 1),
            next_landmark=next_landmark,
            next_landmark_eta_minutes=round(next_landmark_eta, 1) if next_landmark_eta is not None else None,
        )

    return None
