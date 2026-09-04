"""
Module: worker.osint.similar_channels
Discovers related Telegram channels and propaganda botnets using MTProto recommendations (GetChannelRecommendationsRequest)
and historical forward graph correlation.
"""

import json
import logging
from typing import Dict, List, Optional
import redis
import os

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CACHE_TTL = 86400 * 3  # Cache for 3 days to avoid FloodWait

try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
except Exception:
    redis_client = None

# Known intelligence classifications
PROPAGANDA_SIGNATURES = [
    "readovkanews", "rybar", "milinfolive", "voenkorKotenok", "dva_majors",
    "boris_rozhin", "wargonzo", "operational_space", "grey_zone"
]

UKR_OFFICIAL_SIGNATURES = [
    "kpszsu", "va_kyiv", "kyivcityofficial", "dsns_go_ua", "suspilne",
    "generalstaffukr", "diu_ua", "ssu_gov_ua"
]


def classify_channel_affiliation(username: str, title: str = "") -> str:
    """Classifies a Telegram channel into tactical affiliation categories."""
    u_lower = (username or "").lower().replace("@", "")
    t_lower = (title or "").lower()

    if any(s in u_lower for s in UKR_OFFICIAL_SIGNATURES) or any(w in t_lower for w in ["повітряні сили", "кмва", "генштаб", "гур", "сбу"]):
        return "UKRAINIAN_OFFICIAL"
    if any(s in u_lower for s in PROPAGANDA_SIGNATURES) or any(w in t_lower for w in ["военкор", "сводка", "минобороны", "z", "v"]):
        return "ADVERSARY_PROPAGANDA"
    if any(w in u_lower for w in ["radar", "eradar", "alert", "monitor"]):
        return "TACTICAL_MONITORING"
    return "CIVILIAN_OR_OSINT"


def get_cached_similar_channels(channel_username: str) -> Optional[List[Dict[str, any]]]:
    """Retrieves cached channel recommendations from Redis."""
    if not redis_client:
        return None
    try:
        clean = channel_username.lower().replace("@", "")
        cached = redis_client.get(f"c4isr:similar_channels:{clean}")
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.debug(f"Redis get cache failed: {e}")
    return None


def cache_similar_channels(channel_username: str, results: List[Dict[str, any]]) -> None:
    """Caches channel recommendations in Redis with TTL."""
    if not redis_client:
        return
    try:
        clean = channel_username.lower().replace("@", "")
        redis_client.setex(f"c4isr:similar_channels:{clean}", CACHE_TTL, json.dumps(results))
    except Exception as e:
        logger.debug(f"Redis set cache failed: {e}")


async def discover_similar_channels_mtproto(client, channel_entity) -> List[Dict[str, any]]:
    """
    Invokes Telegram MTProto GetChannelRecommendationsRequest via an active Telethon client.
    """
    from telethon.tl.functions.channels import GetChannelRecommendationsRequest
    
    results = []
    try:
        res = await client(GetChannelRecommendationsRequest(channel=channel_entity))
        chats = getattr(res, "chats", [])
        for c in chats:
            username = getattr(c, "username", None) or f"id_{c.id}"
            title = getattr(c, "title", "Unknown Channel")
            participants = getattr(c, "participants_count", 0)
            affiliation = classify_channel_affiliation(username, title)

            results.append({
                "id": c.id,
                "username": username,
                "title": title,
                "participants_count": participants,
                "affiliation": affiliation,
                "verified": getattr(c, "verified", False),
                "fake": getattr(c, "fake", False),
                "scam": getattr(c, "scam", False)
            })
    except Exception as e:
        logger.warning(f"MTProto GetChannelRecommendationsRequest failed: {e}")
        
    return results


def discover_similar_channels_sync(channel_username: str) -> List[Dict[str, any]]:
    """
    Synchronous fallback / cached query for similar channels.
    """
    clean = channel_username.lower().replace("@", "")
    cached = get_cached_similar_channels(clean)
    if cached is not None:
        return cached

    # Pre-seeded tactical clusters for high-priority monitoring channels
    KNOWN_CLUSTERS = {
        "kpszsu": [
            {"username": "va_kyiv", "title": "КМВА", "participants_count": 320000, "affiliation": "UKRAINIAN_OFFICIAL"},
            {"username": "air_alert_ua", "title": "Повітряна Тривога", "participants_count": 890000, "affiliation": "TACTICAL_MONITORING"},
            {"username": "monitor_ukr", "title": "Monitor", "participants_count": 750000, "affiliation": "TACTICAL_MONITORING"}
        ],
        "rybar": [
            {"username": "milinfolive", "title": "Военный Осведомитель", "participants_count": 610000, "affiliation": "ADVERSARY_PROPAGANDA"},
            {"username": "dva_majors", "title": "Два Майора", "participants_count": 1100000, "affiliation": "ADVERSARY_PROPAGANDA"},
            {"username": "boris_rozhin", "title": "Colonelcassad", "participants_count": 780000, "affiliation": "ADVERSARY_PROPAGANDA"}
        ]
    }

    if clean in KNOWN_CLUSTERS:
        res = KNOWN_CLUSTERS[clean]
        cache_similar_channels(clean, res)
        return res

    # Heuristic fallback
    affiliation = classify_channel_affiliation(clean)
    fallback = [{
        "username": clean,
        "title": clean.capitalize(),
        "participants_count": 0,
        "affiliation": affiliation,
        "note": "Initial node (no cluster expansion recorded yet)"
    }]
    cache_similar_channels(clean, fallback)
    return fallback
