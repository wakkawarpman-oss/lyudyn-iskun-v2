"""
Tactical Geo Consensus Engine for Kyiv & Oblast.
Cross-references multi-modal spatial evidence (EXIF GPS, Vision AI, POI database, Regex Address, and Text Toponyms).
Detects and resolves spatial discrepancies (>2km conflicts) and computes weighted spatial centroids.
"""
import math
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class GeoEvidence:
    source: str          # "exif", "geospy", "poi", "regex_address", "regex_street", "text_toponym"
    lat: float
    lon: float
    confidence: float    # 0.0 to 1.0
    radius_meters: float # Uncertainty radius in meters
    label: str = ""
    is_conflict: bool = False


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS coordinates in meters."""
    R = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def resolve_geo_consensus(evidences: List[GeoEvidence]) -> Optional[GeoEvidence]:
    """
    Computes spatial consensus from multiple geographic evidences.
    If evidence sources diverge by > 2000m, flags conflict and selects the highest confidence source.
    """
    if not evidences:
        return None

    if len(evidences) == 1:
        return evidences[0]

    # Filter out invalid lat/lon
    valid_evidences = [
        e for e in evidences
        if e.lat is not None and e.lon is not None and (49.0 <= e.lat <= 51.8) and (29.0 <= e.lon <= 33.0)
    ]

    if not valid_evidences:
        return None

    if len(valid_evidences) == 1:
        return valid_evidences[0]

    # Compute inverse-variance / confidence weighted centroid
    total_weight = 0.0
    weighted_lat = 0.0
    weighted_lon = 0.0

    for e in valid_evidences:
        # Weight formula: higher confidence and tighter radius yield significantly higher weight
        w = (e.confidence * 1000.0) / max(e.radius_meters, 10.0)
        total_weight += w
        weighted_lat += e.lat * w
        weighted_lon += e.lon * w

    if total_weight <= 0:
        return max(valid_evidences, key=lambda e: e.confidence)

    centroid_lat = weighted_lat / total_weight
    centroid_lon = weighted_lon / total_weight

    # Check for divergence / conflict from centroid
    max_dispersion = max(
        haversine_distance_meters(e.lat, e.lon, centroid_lat, centroid_lon)
        for e in valid_evidences
    )

    if max_dispersion > 2000.0:
        # CONFLICT DETECTED: pick highest-confidence source and expand uncertainty radius
        best = max(valid_evidences, key=lambda e: (e.confidence, -e.radius_meters))
        return GeoEvidence(
            source=best.source,
            lat=best.lat,
            lon=best.lon,
            confidence=best.confidence,
            radius_meters=max(best.radius_meters, max_dispersion),
            label=f"{best.label} (⚠️ Конфлікт геоданих розбіжність {int(max_dispersion)}м)",
            is_conflict=True
        )

    # CONSENSUS ACHIEVED: Boost confidence and tighten uncertainty
    avg_conf = sum(e.confidence for e in valid_evidences) / len(valid_evidences)
    min_radius = min(e.radius_meters for e in valid_evidences)
    
    return GeoEvidence(
        source="consensus",
        lat=centroid_lat,
        lon=centroid_lon,
        confidence=min(1.0, avg_conf + 0.15),
        radius_meters=max(10.0, min_radius * 0.8),
        label=f"🟢 Гео-консенсус ({len(valid_evidences)} дж.)",
        is_conflict=False
    )
