"""
worker/osint/military_units.py
OSINT Military Units & Launch Sites Registry Resolver.
Provides NLP entity matching for enemy UAV units, launch bases, and retrodiction anchors.
"""
import json
import os
import re
import math
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
DATABASE_DIR = os.path.join(PROJECT_ROOT, "database")

_UNITS_REGISTRY: Optional[List[Dict[str, Any]]] = None
_LAUNCH_SITES: Optional[List[Dict[str, Any]]] = None


def _load_registries():
    global _UNITS_REGISTRY, _LAUNCH_SITES
    if _UNITS_REGISTRY is None:
        path = os.path.join(DATABASE_DIR, "military_units_registry.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _UNITS_REGISTRY = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load military_units_registry.json: {e}")
            _UNITS_REGISTRY = []

    if _LAUNCH_SITES is None:
        path = os.path.join(DATABASE_DIR, "launch_sites_registry.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _LAUNCH_SITES = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load launch_sites_registry.json: {e}")
            _LAUNCH_SITES = []


def get_all_military_units() -> List[Dict[str, Any]]:
    _load_registries()
    return list(_UNITS_REGISTRY or [])


def get_all_launch_sites() -> List[Dict[str, Any]]:
    _load_registries()
    return list(_LAUNCH_SITES or [])


def find_military_unit(text: str) -> Optional[Dict[str, Any]]:
    """
    Scans text for Russian UAV military units (by number, alias, or base name).
    E.g.: "в/ч 20924", "924 ДЦ", "Варяг", "Рубікон", "Сенеж".
    """
    if not text:
        return None
    _load_registries()
    text_lower = text.lower()

    for unit in _UNITS_REGISTRY or []:
        uid = unit.get("unit_id", "").lower()
        num_match = re.search(r"\d{4,5}", uid)
        num_str = num_match.group(0) if num_match else ""

        # Direct number match (e.g. 20924, 92154)
        if num_str and num_str in text_lower:
            return unit

        # Name / alias match
        name = unit.get("name", "").lower()
        if "варяг" in name and "варяг" in text_lower:
            return unit
        if "рубікон" in name and ("рубікон" in text_lower or "рубикон" in text_lower):
            return unit
        if "сенеж" in name and "сенеж" in text_lower:
            return unit
        if "924" in name and ("924" in text_lower or "коломн" in text_lower):
            return unit

    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2.0)**2
    return r * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def find_nearest_launch_site(lat: float, lon: float, max_dist_km: float = 600.0) -> Optional[Dict[str, Any]]:
    """
    Finds nearest known enemy launch site / airbase for trajectory retrodiction.
    """
    _load_registries()
    best_site = None
    min_dist = float("inf")

    for site in _LAUNCH_SITES or []:
        d = haversine_km(lat, lon, site["latitude"], site["longitude"])
        if d < min_dist and d <= max_dist_km:
            min_dist = d
            best_site = dict(site)
            best_site["distance_km"] = round(min_dist, 1)

    return best_site
