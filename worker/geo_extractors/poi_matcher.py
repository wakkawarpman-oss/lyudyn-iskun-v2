"""
Tactical Point of Interest (POI) Matcher for Kyiv & Kyiv Oblast.
Matches high-value civilian, logistical, industrial, and transportation landmarks.
"""
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Optional, List, Dict

POI_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "database", "kyiv_poi.json")


@dataclass
class PoiMatch:
    name: str
    lat: float
    lon: float
    category: str
    address: str
    matched_alias: str
    precision: str = "building"  # ±50m


@dataclass
class NearbyInfrastructureMatch:
    name: str
    category: str
    category_label: str
    lat: float
    lon: float
    distance_m: float
    address: str


INFRASTRUCTURE_CATEGORY_LABELS = {
    "substation": "⚡ Електрична підстанція",
    "energy": "⚡ Електростанція / ТЕЦ",
    "fuel_depot": "⛽ Нафтобаза / Склад ПММ",
    "telecom": "📡 Телекомунікаційний вузол / Телевежа",
    "defense_industry": "🏭 Об'єкт оборонної промисловості / ВПК",
    "railway": "🚆 Залізничний логістичний вузол",
    "logistics": "📦 Логістичний хаб",
    "airport": "🛫 Аеродром / Аеропорт",
    "bridge": "🌉 Мостовий перехід"
}


def _load_poi_database() -> Dict[str, dict]:
    """Loads POI database from JSON."""
    if not os.path.exists(POI_DB_PATH):
        return {}
    try:
        with open(POI_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


KYIV_POI_DATABASE = _load_poi_database()


def calculate_haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points on the Earth in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def find_nearby_critical_infrastructure(lat: float, lon: float, max_radius_m: float = 1200.0) -> List[NearbyInfrastructureMatch]:
    """
    Sightline Engine Proximity Search:
    Scans strategic critical infrastructure assets and returns those within max_radius_m,
    sorted by proximity ascending.
    """
    if lat is None or lon is None:
        return []

    matches = []
    critical_categories = {
        "substation", "energy", "fuel_depot", "telecom", "defense_industry",
        "railway", "airport", "bridge"
    }

    for name, data in KYIV_POI_DATABASE.items():
        cat = data.get("category", "")
        if cat not in critical_categories:
            continue

        poi_lat = data.get("lat")
        poi_lon = data.get("lon")
        if poi_lat is None or poi_lon is None:
            continue

        dist = calculate_haversine_distance_m(lat, lon, poi_lat, poi_lon)
        if dist <= max_radius_m:
            cat_label = INFRASTRUCTURE_CATEGORY_LABELS.get(cat, "⚠️ Стратегічний об'єкт")
            matches.append(NearbyInfrastructureMatch(
                name=name,
                category=cat,
                category_label=cat_label,
                lat=poi_lat,
                lon=poi_lon,
                distance_m=round(dist, 1),
                address=data.get("address", name)
            ))

    matches.sort(key=lambda x: x.distance_m)
    return matches


def match_poi(text: str) -> Optional[PoiMatch]:
    """Matches text against tactical POI database using case-insensitive word boundary matching."""
    if not text:
        return None

    text_lower = text.lower()

    for name, data in KYIV_POI_DATABASE.items():
        aliases: List[str] = data.get("aliases", []) + [name.lower()]
        for alias in aliases:
            # Escape for regex and allow flexible whitespace/quotes
            escaped = re.escape(alias.strip().lower())
            escaped = escaped.replace(r'\ ', r'\s+')
            # Word boundary or start/end
            pattern = rf'(?:^|[\s,.;:!?\(\)«»"\'\-])({escaped})(?:$|[\s,.;:!?\(\)«»"\'\-])'
            match = re.search(pattern, text_lower)
            if match:
                return PoiMatch(
                    name=name,
                    lat=data["lat"],
                    lon=data["lon"],
                    category=data.get("category", "landmark"),
                    address=data.get("address", name),
                    matched_alias=match.group(1),
                    precision="building"
                )

    return None
