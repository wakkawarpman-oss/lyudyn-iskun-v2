"""
Two-Dimensional Verification & Threat Scoring Engine
Decouples Physical Severity (Significance 0-100) from Verification Trust (Confidence 0-100).
"""
from typing import List, Union
from worker.source_registry import get_source_metadata

# Base Physical Significance Scale by Event Type
SIGNIFICANCE_TABLE = {
    "direct_strike": 95,
    "casualties": 95,
    "destruction": 90,
    "explosion": 85,
    "fire": 75,
    "armed_conflict": 85,
    "air_defense": 65,
    "radar_track": 50,
    "general_alert": 30,
    "other": 30
}

def calculate_significance_score(event_type: str, has_media: bool = False, message_text: str = "") -> int:
    """
    Computes Physical Significance (0 - 100).
    Measures the destructive kinetic impact, lethality, and tactical severity.
    """
    et = (event_type or "other").lower()
    base = SIGNIFICANCE_TABLE.get(et, 40)

    # Contextual boosters
    txt = (message_text or "").lower()
    boost = 0
    if any(w in txt for w in ["загибл", "поранен", "жертв", "постраждал"]):
        boost += 10
    if any(w in txt for w in ["шахед", "ракета", "іскандер", "калібр", "х-101"]):
        boost += 5
    if has_media and et in ["direct_strike", "explosion", "fire", "destruction"]:
        boost += 5

    return min(100, max(15, base + boost))

def calculate_confidence_score(
    sources: Union[List[str], str],
    is_official: bool = False,
    has_photo_evidence: bool = False
) -> int:
    """
    Computes Verification Confidence (0 - 100).
    Measures the degree of cross-source consensus and source reliability.
    """
    if isinstance(sources, str):
        src_list = [s.strip().replace("@", "") for s in sources.split(",") if s.strip()]
    else:
        src_list = [str(s).strip().replace("@", "") for s in sources if str(s).strip()]

    if not src_list:
        return 35

    # 1. Base weights from Source Registry
    total_weight = 0.0
    official_count = 0
    monitoring_count = 0

    for src in src_list:
        meta = get_source_metadata(src)
        total_weight += meta["base_weight"]
        if meta["type"] in ["OFFICIAL", "MILITARY"]:
            official_count += 1
        elif "MONITOR" in meta["type"]:
            monitoring_count += 1

    # 2. Multi-source consensus computation
    unique_sources = len(set(src_list))
    
    if official_count >= 1:
        base_score = 90 + min(10, unique_sources * 2)
    elif unique_sources >= 3:
        base_score = 85 + min(10, unique_sources * 2)
    elif unique_sources == 2:
        base_score = 70 + int(total_weight * 5)
    else:
        # Single source
        single_meta = get_source_metadata(src_list[0])
        if single_meta["type"] in ["OFFICIAL", "MILITARY"]:
            base_score = 90
        elif "MONITOR" in single_meta["type"]:
            base_score = 60
        else:
            base_score = 35

    if has_photo_evidence:
        base_score += 8

    if is_official:
        base_score = max(base_score, 90)

    return min(100, max(15, base_score))

def compute_composite_resonance(significance: int, confidence: int) -> int:
    """
    Blends Significance and Confidence into a single unified 0-100 metric for sorting/legacy compatibility.
    Resonance = 0.55 * Significance + 0.45 * Confidence
    """
    composite = int(0.55 * significance + 0.45 * confidence)
    return min(100, max(10, composite))
