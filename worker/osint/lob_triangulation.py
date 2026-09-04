"""
Line of Bearing (LOB) & Acoustic/Visual Sensor Triangulation Engine.
===================================================================
Provides WGS-84 forward geodesic projections and multi-bearing intersection
with Circular Error Probable (CEP) calculations for target verification.
"""

import math
from typing import Dict, List, Any, Optional

EARTH_RADIUS_M = 6371000.0


def forward_geodesic(lat: float, lon: float, azimuth_deg: float, distance_m: float) -> Dict[str, float]:
    """
    Direct Geodetic Problem on WGS-84 spherical approximation.
    Returns destination (lat, lon) given starting point, bearing, and distance.
    """
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    brng_r = math.radians(azimuth_deg)
    d_div_r = distance_m / EARTH_RADIUS_M

    target_lat_r = math.asin(
        math.sin(lat_r) * math.cos(d_div_r) +
        math.cos(lat_r) * math.sin(d_div_r) * math.cos(brng_r)
    )

    target_lon_r = lon_r + math.atan2(
        math.sin(brng_r) * math.sin(d_div_r) * math.cos(lat_r),
        math.cos(d_div_r) - math.sin(lat_r) * math.sin(target_lat_r)
    )

    return {
        "lat": round(math.degrees(target_lat_r), 6),
        "lon": round(math.degrees(target_lon_r), 6)
    }


def intersect_two_bearings(
    lat1: float, lon1: float, brng1_deg: float,
    lat2: float, lon2: float, brng2_deg: float
) -> Optional[Dict[str, float]]:
    """
    Calculates intersection point of two great circle bearing lines.
    Returns None if lines are parallel or do not converge.
    """
    phi1, lam1 = math.radians(lat1), math.radians(lon1)
    phi2, lam2 = math.radians(lat2), math.radians(lon2)
    theta13, theta23 = math.radians(brng1_deg), math.radians(brng2_deg)

    dphi = phi2 - phi1
    dlam = lam2 - lam1

    # Angular distance between points 1 and 2
    delta12 = 2.0 * math.asin(math.sqrt(
        math.sin(dphi / 2.0) ** 2 +
        math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    ))

    if delta12 < 1e-7:
        return {"lat": lat1, "lon": lon1}

    # Initial/final bearings between points 1 and 2
    theta_a = math.acos(min(1.0, max(-1.0,
        (math.sin(phi2) - math.sin(phi1) * math.cos(delta12)) / (math.cos(phi1) * math.sin(delta12))
    )))
    theta_b = math.acos(min(1.0, max(-1.0,
        (math.sin(phi1) - math.sin(phi2) * math.cos(delta12)) / (math.cos(phi2) * math.sin(delta12))
    )))

    if math.sin(lam2 - lam1) > 0:
        theta12 = theta_a
        theta21 = 2.0 * math.pi - theta_b
    else:
        theta12 = 2.0 * math.pi - theta_a
        theta21 = theta_b

    alpha1 = (theta13 - theta12 + math.pi) % (2.0 * math.pi) - math.pi
    alpha2 = (theta21 - theta23 + math.pi) % (2.0 * math.pi) - math.pi

    if math.sin(alpha1) == 0 and math.sin(alpha2) == 0:
        return None  # Infinite intersections
    if math.sin(alpha1) * math.sin(alpha2) < 0:
        return None  # Rays diverge

    alpha3 = math.acos(min(1.0, max(-1.0,
        -math.cos(alpha1) * math.cos(alpha2) + math.sin(alpha1) * math.sin(alpha2) * math.cos(delta12)
    )))

    delta13 = math.atan2(
        math.sin(delta12) * math.sin(alpha1) * math.sin(alpha2),
        math.cos(alpha2) + math.cos(alpha1) * math.cos(alpha3)
    )

    phi3 = math.asin(min(1.0, max(-1.0,
        math.sin(phi1) * math.cos(delta13) + math.cos(phi1) * math.sin(delta13) * math.cos(theta13)
    )))

    dlam13 = math.atan2(
        math.sin(theta13) * math.sin(delta13) * math.cos(phi1),
        math.cos(delta13) - math.sin(phi1) * math.sin(phi3)
    )
    lam3 = lam1 + dlam13

    return {
        "lat": round(math.degrees(phi3), 6),
        "lon": round(math.degrees(lam3), 6)
    }


def compute_lob_triangulation(bearings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes weighted multi-bearing triangulation solution and CEP.
    bearings format: [{"lat": float, "lon": float, "azimuth": float, "weight": Optional[float]}]
    """
    if len(bearings) < 2:
        return {
            "status": "insufficient_data",
            "message": "At least 2 LOB bearings required for triangulation."
        }

    intersections = []
    rays = []

    for b in bearings:
        # Generate 15 km ray vector for UI rendering
        end_pt = forward_geodesic(b["lat"], b["lon"], b["azimuth"], 15000.0)
        rays.append({
            "start": [b["lat"], b["lon"]],
            "end": [end_pt["lat"], end_pt["lon"]],
            "azimuth": b["azimuth"],
            "observer": b.get("observer", "Пост спостереження")
        })

    # Pairwise intersections
    for i in range(len(bearings)):
        for j in range(i + 1, len(bearings)):
            b1, b2 = bearings[i], bearings[j]
            pt = intersect_two_bearings(
                b1["lat"], b1["lon"], b1["azimuth"],
                b2["lat"], b2["lon"], b2["azimuth"]
            )
            if pt:
                intersections.append(pt)

    if not intersections:
        return {
            "status": "diverging_bearings",
            "message": "Bearings do not converge to a single target sector.",
            "rays": rays
        }

    # Centroid
    avg_lat = sum(p["lat"] for p in intersections) / len(intersections)
    avg_lon = sum(p["lon"] for p in intersections) / len(intersections)

    # Estimate CEP (Circular Error Probable) in meters
    dists_m = []
    for p in intersections:
        dlat = math.radians(p["lat"] - avg_lat)
        dlon = math.radians(p["lon"] - avg_lon)
        dist = EARTH_RADIUS_M * math.sqrt(dlat ** 2 + (dlon * math.cos(math.radians(avg_lat))) ** 2)
        dists_m.append(dist)

    cep_m = round(max(dists_m) if dists_m else 25.0, 1)

    return {
        "status": "success",
        "target": {
            "lat": round(avg_lat, 6),
            "lon": round(avg_lon, 6)
        },
        "cep_radius_m": max(cep_m, 20.0),
        "converged_intersections": len(intersections),
        "rays": rays,
        "confidence": 90 if len(intersections) >= 3 else 75
    }
