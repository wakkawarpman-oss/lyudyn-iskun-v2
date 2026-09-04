"""
Module: worker.osint.threat_dispatcher
Automated dispatch engine for critical energy infrastructure (substations 110-750 kV).
Calculates threat cones, warns dispatchers, and generates actionable C2 alert packages.
"""

import time
from typing import Dict, List, Any, Optional
from worker.osint.launch_triangulation import project_forward_substation_threats
from worker.geo_extractors.poi_matcher import POI_DATABASE

# Alert cache for deduplication (key: alert_key -> timestamp)
_ALERT_CACHE: Dict[str, float] = {}
ALERT_DEDUP_WINDOW_SEC = 300  # 5 minutes suppression for identical drone-target pairs


def generate_substation_alerts(drones: List[Dict], max_cone_deg: float = 35.0, max_distance_km: float = 75.0) -> List[Dict[str, Any]]:
    """
    Scans all active drones, calculates forward threat intersections with 110-750 kV substations,
    and returns prioritized dispatch alert packages.
    """
    if not drones:
        return []

    # Filter target facilities from POI database
    strategic_targets = [
        {
            "name": name,
            "lat": data["lat"],
            "lon": data["lon"],
            "category": data.get("category", "substation"),
            "voltage": data.get("voltage", "110-750 кВ"),
            "address": data.get("address", "")
        }
        for name, data in POI_DATABASE.items()
        if data.get("category") in ("substation", "energy", "fuel_depot", "defense_industry")
    ]

    active_alerts: List[Dict[str, Any]] = []
    current_time = time.time()

    for drone in drones:
        lat = drone.get("lat")
        lng = drone.get("lng")
        heading = drone.get("heading")
        speed = drone.get("speed_kmh") or 185.0
        drone_id = drone.get("id", "unknown")
        drone_label = drone.get("label", "БпЛА Shahed-136")

        if lat is None or lng is None or heading is None or heading <= 0:
            continue

        threats = project_forward_substation_threats(
            current_lat=lat,
            current_lon=lng,
            heading_deg=heading,
            speed_kmh=speed,
            substations=strategic_targets,
            max_cone_deg=max_cone_deg,
            max_distance_km=max_distance_km
        )

        for target in threats:
            eta = target.get("eta_minutes", 0.0)
            target_name = target.get("name", "Енергопідстанція")
            voltage = target.get("voltage", "110-750 кВ")
            dist_km = target.get("distance_km", 0.0)

            # Classify urgency
            if eta <= 10.0:
                urgency = "CRITICAL"
                action = "НЕГАЙНО: Персонал в укриття. Підготовка резервних ліній живлення. Оповіщення МВГ ППО."
            elif eta <= 20.0:
                urgency = "HIGH"
                action = "УВАГА: Підготовка до можливого аварійного відключення. Секторальний контроль ППО."
            else:
                urgency = "ELEVATED"
                action = "МОНІТОРИНГ: Дрон на курсі наближення до енергетичного вузла."

            alert_key = f"{drone_id}_{target_name}"
            last_sent = _ALERT_CACHE.get(alert_key, 0)
            is_suppressed = (current_time - last_sent) < ALERT_DEDUP_WINDOW_SEC

            alert_pkg = {
                "alert_id": f"disp_{abs(hash(alert_key)) % 10000000}",
                "target_name": target_name,
                "voltage": voltage,
                "target_lat": target.get("lat"),
                "target_lon": target.get("lon"),
                "drone_id": drone_id,
                "drone_label": drone_label,
                "drone_speed_kmh": round(speed, 1),
                "drone_heading": round(heading, 1),
                "distance_km": dist_km,
                "eta_minutes": eta,
                "urgency": urgency,
                "estimated_launch_site": drone.get("estimated_launch", {}).get("site_name") if isinstance(drone.get("estimated_launch"), dict) else None,
                "recommended_action": action,
                "is_suppressed": is_suppressed,
                "timestamp": current_time
            }

            if not is_suppressed:
                _ALERT_CACHE[alert_key] = current_time

            active_alerts.append(alert_pkg)

    # Sort by ETA (closest threat first)
    active_alerts.sort(key=lambda a: a["eta_minutes"])
    return active_alerts


def get_active_dispatch_summary(drones: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    High-level dispatch summary for API endpoints and dashboards.
    """
    if drones is None:
        from worker.osint.neptun_radar import get_live_radar_threats
        radar_data = get_live_radar_threats()
        drones = radar_data.get("drones", [])

    alerts = generate_substation_alerts(drones)
    critical_count = sum(1 for a in alerts if a["urgency"] == "CRITICAL")
    high_count = sum(1 for a in alerts if a["urgency"] == "HIGH")

    return {
        "status": "active",
        "total_threats_detected": len(alerts),
        "critical_immediate_count": critical_count,
        "high_warning_count": high_count,
        "alerts": alerts
    }
