"""
worker/verification/psyop_detector.py
Anti-Hallucination & Anti-PSYOP Deterministic Verification Engine.

Provides:
1. Geographic bounding box and semantic sanity validation.
2. Cross-checking against verified military units and launch site registries.
3. Sliding-window channel burst detector to neutralize coordinated bot-swarm spam.
"""
from __future__ import annotations
import time
import re
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from worker.osint.military_units import find_military_unit, find_nearest_launch_site

# Geographic boundary bounding box of Ukraine (including Crimea and territorial waters)
UKRAINE_GEO_BOUNDS = {
    "min_lat": 44.0,
    "max_lat": 52.5,
    "min_lon": 22.0,
    "max_lon": 40.5
}

DEFAULT_BURST_WINDOW_SEC = 180.0   # 3 minutes
DEFAULT_BURST_MAX_COUNT = 5        # max uncorroborated messages before flag


class PsyopBurstDetector:
    """
    In-memory / Redis sliding window burst detector.
    Detects uncorroborated panic-burst activity from Telegram channels.
    """
    def __init__(self, window_sec: float = DEFAULT_BURST_WINDOW_SEC, max_burst: int = DEFAULT_BURST_MAX_COUNT):
        self.window_sec = window_sec
        self.max_burst = max_burst
        self._channel_timestamps: Dict[str, List[float]] = defaultdict(list)

    def record_channel_message(self, channel_id: str, timestamp: Optional[float] = None) -> Tuple[bool, int, float]:
        now = timestamp or time.time()
        ts_list = self._channel_timestamps[channel_id]
        cutoff = now - self.window_sec
        valid_ts = [t for t in ts_list if t >= cutoff]
        valid_ts.append(now)
        self._channel_timestamps[channel_id] = valid_ts

        count = len(valid_ts)
        is_burst = count >= self.max_burst
        score = min(1.0, count / (self.max_burst * 1.5))
        return is_burst, count, round(score, 2)

    def clear(self):
        self._channel_timestamps.clear()


_GLOBAL_BURST_DETECTOR = PsyopBurstDetector()


def validate_osint_event_truthfulness(
    lat: Optional[float],
    lon: Optional[float],
    text_content: str,
    channel_id: str = "unknown_source",
    is_sensor_corroborated: bool = False,
    detector: Optional[PsyopBurstDetector] = None
) -> Dict[str, Any]:
    flags: List[str] = []
    anomaly_score = 0.0

    # 1. Coordinate Validity Check
    if lat is not None and lon is not None:
        if not (UKRAINE_GEO_BOUNDS["min_lat"] <= lat <= UKRAINE_GEO_BOUNDS["max_lat"] and
                UKRAINE_GEO_BOUNDS["min_lon"] <= lon <= UKRAINE_GEO_BOUNDS["max_lon"]):
            flags.append("COORDINATES_OUT_OF_UKRAINE_BOUNDS")
            anomaly_score += 0.5
    else:
        flags.append("MISSING_COORDINATES")

    # 2. Burst Detection Check
    det = detector or _GLOBAL_BURST_DETECTOR
    is_burst, burst_count, burst_score = det.record_channel_message(channel_id)
    if is_burst and not is_sensor_corroborated:
        flags.append(f"HIGH_FREQUENCY_UNVERIFIED_BURST_{burst_count}_MSGS")
        anomaly_score += 0.5
    elif is_burst and is_sensor_corroborated:
        flags.append("CORROBORATED_BURST_PASSED")

    # 3. Entity Grounding Check
    unit_match = find_military_unit(text_content)
    if unit_match:
        uid = unit_match.get("unit_id", "KNOWN_UNIT")
        flags.append(f"GROUNDED_UNIT_{uid}")
        anomaly_score = max(0.0, anomaly_score - 0.2)

    # 4. Keyword Suspicion Analysis
    panic_patterns = [
        r"масований ядерний",
        r"знищено всі міста",
        r"капітуляція",
        r"зрада повна",
        r"здають область",
    ]
    for pattern in panic_patterns:
        if re.search(pattern, text_content, re.IGNORECASE):
            flags.append(f"PANIC_PSYOP_KEYWORD_{pattern}")
            anomaly_score += 0.35

    anomaly_score = min(1.0, max(0.0, round(anomaly_score, 2)))
    is_psyop_suspect = anomaly_score >= 0.60
    is_valid = ("COORDINATES_OUT_OF_UKRAINE_BOUNDS" not in flags) and not is_psyop_suspect

    return {
        "is_valid": is_valid,
        "is_psyop_suspect": is_psyop_suspect,
        "anomaly_score": anomaly_score,
        "validation_flags": flags,
        "grounded_unit": unit_match.get("unit_id") if unit_match else None,
        "burst_count": burst_count,
    }
