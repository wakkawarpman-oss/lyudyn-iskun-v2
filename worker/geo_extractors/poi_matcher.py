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

POI_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "database", "poi", "poi_registry.json")
POI_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "database", "kyiv_poi.json")


@dataclass
class PoiMatch:
    name: str
    lat: float
    lon: float
    category: str
    address: str
    matched_alias: str
    oblast: str = "kyiv"
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
    oblast: str = "kyiv"


INFRASTRUCTURE_CATEGORY_LABELS = {
    "substation": "⚡ Електрична підстанція",
    "energy": "⚡ Електростанція / ТЕЦ / ГЕС",
    "fuel_depot": "⛽ Нафтобаза / Склад ПММ",
    "telecom": "📡 Телекомунікаційний вузол / Телевежа",
    "defense_industry": "🏭 Об'єкт оборонної промисловості / ВПК",
    "railway": "🚆 Залізничний логістичний вузол",
    "logistics": "📦 Логістичний хаб",
    "airport": "🛫 Аеродром / Аеропорт",
    "bridge": "🌉 Мостовий перехід"
}


def _load_poi_database() -> Dict[str, dict]:
    """Loads POI database from POI registry or fallback to kyiv_poi."""
    path = POI_REGISTRY_PATH if os.path.exists(POI_REGISTRY_PATH) else POI_DB_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


POI_DATABASE = _load_poi_database()
KYIV_POI_DATABASE = POI_DATABASE


def calculate_haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points on the Earth in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def find_nearby_critical_infrastructure(lat: float, lon: float, max_radius_m: float = 1200.0, oblast: Optional[str] = None) -> List[NearbyInfrastructureMatch]:
    """
    Sightline Engine Proximity Search:
    Scans strategic critical infrastructure assets and returns those within max_radius_m,
    sorted by proximity ascending. Optionally filter by oblast.
    """
    if lat is None or lon is None:
        return []

    matches = []
    critical_categories = {
        "substation", "energy", "fuel_depot", "telecom", "defense_industry",
        "railway", "airport", "bridge"
    }

    for name, data in POI_DATABASE.items():
        if oblast and data.get("oblast") and data.get("oblast") != oblast:
            continue

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
            display_name = data.get("name", name)
            matches.append(NearbyInfrastructureMatch(
                name=display_name,
                category=cat,
                category_label=cat_label,
                lat=poi_lat,
                lon=poi_lon,
                distance_m=round(dist, 1),
                address=data.get("address", display_name),
                oblast=data.get("oblast", "kyiv")
            ))

    matches.sort(key=lambda x: x.distance_m)
    return matches


def match_poi(text: str, oblast: Optional[str] = None) -> Optional[PoiMatch]:
    """Matches text against tactical POI database using case-insensitive word boundary matching, optionally filtered by oblast."""
    if not text:
        return None

    text_lower = text.lower()

    for name, data in POI_DATABASE.items():
        if oblast and data.get("oblast") and data.get("oblast") != oblast:
            continue

        aliases: List[str] = data.get("aliases", []) + [name.lower()]
        if "name" in data and data["name"].lower() not in aliases:
            aliases.append(data["name"].lower())

        for alias in aliases:
            # Escape for regex and allow flexible whitespace/quotes
            escaped = re.escape(alias.strip().lower())
            escaped = escaped.replace(r'\ ', r'\s+')
            # Word boundary or start/end
            pattern = rf'(?:^|[\s,.;:!?\(\)«»"\'\-])({escaped})(?:$|[\s,.;:!?\(\)«»"\'\-])'
            match = re.search(pattern, text_lower)
            if match:
                return PoiMatch(
                    name=data.get("name", name),
                    lat=data["lat"],
                    lon=data["lon"],
                    category=data.get("category", "landmark"),
                    address=data.get("address", name),
                    matched_alias=match.group(1),
                    oblast=data.get("oblast", "kyiv"),
                    precision="building"
                )

    return None
