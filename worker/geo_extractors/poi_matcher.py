"""
Tactical Point of Interest (POI) Matcher for Kyiv & Kyiv Oblast.
Matches high-value civilian, logistical, industrial, and transportation landmarks.
"""
import json
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
