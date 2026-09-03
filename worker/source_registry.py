"""
Source Reliability Registry & Channel Metadata Catalog
Defines authoritative hierarchy, baseline credibility weights, and latency tiers.
"""
from typing import Dict, Any

SOURCE_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ── Official Government & Emergency State Services (Tier 1: Base Weight 1.0) ──
    "dsns_kyiv_region": {
        "title": "ДСНС Київщини",
        "type": "OFFICIAL",
        "tier": "S",
        "base_weight": 1.00,
        "scope": "Kyiv Oblast",
        "latency_tier": "HIGH_ACCURACY"
    },
    "dsns_telegram": {
        "title": "ДСНС України",
        "type": "OFFICIAL",
        "tier": "S",
        "base_weight": 1.00,
        "scope": "National",
        "latency_tier": "HIGH_ACCURACY"
    },
    "KyivCityOfficial": {
        "title": "КМДА (Офіційний)",
        "type": "OFFICIAL",
        "tier": "S",
        "base_weight": 1.00,
        "scope": "Kyiv City",
        "latency_tier": "HIGH_ACCURACY"
    },
    "VA_Kyiv": {
        "title": "КМВА (Військова Адміністрація)",
        "type": "OFFICIAL",
        "tier": "S",
        "base_weight": 1.00,
        "scope": "Kyiv City",
        "latency_tier": "HIGH_ACCURACY"
    },
    "kpszsu": {
        "title": "Повітряні Сили ЗСУ",
        "type": "MILITARY",
        "tier": "S",
        "base_weight": 1.00,
        "scope": "Airspace",
        "latency_tier": "LOW_LATENCY"
    },
    "GeneralStaffZSU": {
        "title": "Генштаб ЗСУ",
        "type": "MILITARY",
        "tier": "S",
        "base_weight": 1.00,
        "scope": "National",
        "latency_tier": "HIGH_ACCURACY"
    },

    # ── Verified Real-Time OSINT & Radar Monitors (Tier 2: Base Weight 0.70 - 0.85) ──
    "war_monitor": {
        "title": "War Monitor",
        "type": "OSINT_MONITOR",
        "tier": "A",
        "base_weight": 0.80,
        "scope": "Tactical",
        "latency_tier": "INSTANT"
    },
    "eRadarrua": {
        "title": "єРадар",
        "type": "RADAR_MONITOR",
        "tier": "A",
        "base_weight": 0.80,
        "scope": "Radar",
        "latency_tier": "INSTANT"
    },
    "monitor_ukr": {
        "title": "Monitor (Ukraine)",
        "type": "OSINT_MONITOR",
        "tier": "A",
        "base_weight": 0.75,
        "scope": "Tactical",
        "latency_tier": "INSTANT"
    },
    "ssternenko": {
        "title": "Сергій Стерненко",
        "type": "VERIFIED_PUBLIC",
        "tier": "A",
        "base_weight": 0.70,
        "scope": "Ukraine",
        "latency_tier": "INSTANT"
    },
    "Pravda_Gerashchenko": {
        "title": "Правда Геращенко",
        "type": "MEDIA_OSINT",
        "tier": "A",
        "base_weight": 0.70,
        "scope": "Media",
        "latency_tier": "FAST"
    },

    # ── Situational Kyiv Channels (Tier 3: Base Weight 0.50 - 0.65) ──
    "kyivoperat": {
        "title": "Київ Оперативний",
        "type": "CITY_MONITOR",
        "tier": "B",
        "base_weight": 0.65,
        "scope": "Kyiv City",
        "latency_tier": "FAST"
    },
    "kyivoperativ": {
        "title": "Київ Оперативний",
        "type": "CITY_MONITOR",
        "tier": "B",
        "base_weight": 0.65,
        "scope": "Kyiv City",
        "latency_tier": "FAST"
    },
    "t_kyiv": {
        "title": "Типовий Київ",
        "type": "CITY_MONITOR",
        "tier": "B",
        "base_weight": 0.60,
        "scope": "Kyiv City",
        "latency_tier": "FAST"
    },
    "los_solomas": {
        "title": "Los Solomas",
        "type": "DISTRICT_MONITOR",
        "tier": "B",
        "base_weight": 0.60,
        "scope": "Solomianskyi",
        "latency_tier": "FAST"
    },
    "kyiv24": {
        "title": "Київ 24",
        "type": "MEDIA",
        "tier": "B",
        "base_weight": 0.60,
        "scope": "Kyiv City",
        "latency_tier": "FAST"
    },

    # ── Broad Aggregators (Tier 4: Base Weight 0.35 - 0.45) ──
    "povitryanatrivogaaa": {
        "title": "Повітряна Тривога",
        "type": "AGGREGATOR",
        "tier": "C",
        "base_weight": 0.45,
        "scope": "National Alerts",
        "latency_tier": "FAST"
    },
    "kyiv_alarm": {
        "title": "Київ Тривога",
        "type": "AGGREGATOR",
        "tier": "C",
        "base_weight": 0.45,
        "scope": "Kyiv Alerts",
        "latency_tier": "FAST"
    },
}

def get_source_metadata(channel_name: str) -> Dict[str, Any]:
    """Retrieves metadata profile for a source channel."""
    clean = (channel_name or "").replace("@", "").strip()
    if clean in SOURCE_REGISTRY:
        return SOURCE_REGISTRY[clean]
    return {
        "title": f"@{clean}" if clean else "Unknown Source",
        "type": "USER_GENERATED",
        "tier": "C",
        "base_weight": 0.40,
        "scope": "General",
        "latency_tier": "UNVERIFIED"
    }
