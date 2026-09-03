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

def calculate_significance_score(
    event_type: str,
    has_media: bool = False,
    message_text: str = "",
    is_panic: bool = False,
) -> int:
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
    # worker/osint/sentiment.py flags eyewitness text as panicked (score <= 2/5) —
    # a modest signal that the incident is more severe than the bare event_type
    # alone suggests, not a substitute for the keyword boosters above.
    if is_panic:
        boost += 8

    return min(100, max(15, base + boost))

def calculate_confidence_score(
    sources: Union[List[str], str],
    is_official: bool = False,
    has_photo_evidence: bool = False
) -> int:
    """
    Computes Verification Confidence (0 - 100) based on weighted multi-source consensus.

    Scale (A.5 Contract):
    - combined_weight >= 2.0 and official_count >= 1 -> 95 (Official + corroboration)
    - official_count >= 1                            -> 90 (Official report)
    - combined_weight >= 1.5                         -> 85 (2+ Monitors)
    - combined_weight >= 1.2                         -> 70 (Monitor + Aggregator)
    - monitoring_count >= 1                          -> 60 (Single Monitor)
    - else                                           -> 40 (Aggregators only)
    - Photo / Vision AI evidence                     -> +8 points booster
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
        total_weight += meta.get("base_weight", 0.40)
        src_type = meta.get("type", "AGGREGATOR")
        if src_type in ["OFFICIAL", "MILITARY"]:
            official_count += 1
        elif "MONITOR" in src_type:
            monitoring_count += 1

    # 2. Weighted consensus scoring
    if official_count >= 1 and total_weight >= 2.0:
        base_score = 95
    elif official_count >= 1 or is_official:
        base_score = 90
    elif total_weight >= 1.5:
        base_score = 85
    elif total_weight >= 1.2:
        base_score = 70
    elif monitoring_count >= 1:
        base_score = 60
    else:
        base_score = 40

    if has_photo_evidence:
        base_score += 8

    return min(100, max(15, base_score))

def compute_composite_resonance(significance: int, confidence: int) -> int:
    """
    Blends Significance and Confidence into a single unified 0-100 metric for sorting/legacy compatibility.
    Resonance = 0.55 * Significance + 0.45 * Confidence
    """
    composite = int(0.55 * significance + 0.45 * confidence)
    return min(100, max(10, composite))
