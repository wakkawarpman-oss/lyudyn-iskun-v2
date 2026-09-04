"""
Reverse Launch Triangulation & Forward Substation Threat Projection Module
=========================================================================
Synthesized from AlabugaLeaks, CTGNN telecom intercepts, and 924th Drone Center intelligence.
"""

import math
from typing import Dict, List, Optional

# Verified Ground Truth Enemy Launch Sites & Production/C2 Facilities
KNOWN_ENEMY_FACILITIES: List[Dict] = [
    {
        "id": "navlya",
        "name": "Навля (Брянська обл., РФ)",
        "lat": 52.8491,
        "lon": 34.4865,
        "type": "launch_site",
        "threat_level": "CRITICAL",
        "sector": "Північний (на Чернігів / Суми / Київ)",
        "dossier": "Активний стартовий майданчик Shahed-136/131. Фіксація перехоплень бойового розрахунку в/ч 20924."
    },
    {
        "id": "tsymbulovo",
        "name": "Цимбулове (Орловська обл., РФ)",
        "lat": 53.3656,
        "lon": 35.7974,
        "type": "launch_site",
        "threat_level": "MAXIMUM",
        "sector": "Північно-східний (на Суми / Харків / Полтаву / Київ)",
        "dossier": "Пусковий хаб високої інтенсивності. Використовує мобільні пускові на шасі КамАЗ."
    },
    {
        "id": "kursk_hq",
        "name": "Курськ / Клюква (РФ)",
        "lat": 51.7308,
        "lon": 36.1930,
        "type": "launch_site",
        "threat_level": "HIGH",
        "sector": "Сумський напрямок",
        "dossier": "Штабний та логістичний вузол 448-ї ракетної бригади (в/ч 35535) та мобільних пускових БпЛА."
    },
    {
        "id": "primorsko_akhtarsk",
        "name": "Приморсько-Ахтарськ (Краснодарський край, РФ)",
        "lat": 46.0500,
        "lon": 38.1600,
        "type": "launch_site",
        "threat_level": "CRITICAL",
        "sector": "Південний (через Азовське море на Дніпро / Запоріжжя / Одесу)",
        "dossier": "Основна південна авіабаза запусків Шахедів (148-й змішаний авіаполк)."
    },
    {
        "id": "yeysk",
        "name": "Єйськ (Краснодарський край, РФ)",
        "lat": 46.6800,
        "lon": 38.2500,
        "type": "launch_site",
        "threat_level": "HIGH",
        "sector": "Південно-східний (на східні та центральні області)",
        "dossier": "Авіабаза та 859-й Центр бойового застосування морської авіації РФ."
    },
    {
        "id": "chauda",
        "name": "Мис Чауда (окупований Крим)",
        "lat": 45.0000,
        "lon": 35.8300,
        "type": "launch_site",
        "threat_level": "CRITICAL",
        "sector": "Південний морський коридор (на Миколаїв / Одесу)",
        "dossier": "Військовий полігон у Криму, що використовується для масованих запусків Shahed."
    },
    {
        "id": "alabuga",
        "name": "ОЕЗ «Алабуга» / ТОВ «Альбатрос» (Татарстан)",
        "lat": 55.7800,
        "lon": 52.0900,
        "type": "factory",
        "threat_level": "STRATEGIC",
        "sector": "ВПК / Серійне складання",
        "dossier": "Завод серійного випуску «Герань-2/3» (Проєкт Dolphin 632, корпус Синергія 8.2, ГД Олексій Флоров)."
    },
    {
        "id": "kolomna",
        "name": "924-й ДЦ БпЛА (в/ч 20924, Коломна, РФ)",
        "lat": 55.0800,
        "lon": 38.7800,
        "type": "command_center",
        "threat_level": "STRATEGIC",
        "sector": "Командування БпЛА МО РФ",
        "dossier": "Центр планування операцій та підготовки інструкторів БпЛА (екс-командир полковник Коломєйцев ліквідований)."
    },
    {
        "id": "kashan",
        "name": "Аеродром Кашан (Іран, база КВІР)",
        "lat": 33.9853,
        "lon": 51.7118,
        "type": "training_base",
        "threat_level": "FOREIGN_ACTOR",
        "sector": "Іранська навчальна інфраструктура",
        "dossier": "База Корпусу вартових ісламської революції (КВІР), де офіцери в/ч 20924 проходили навчання з експлуатації Шахедів."
    },
    {
        "id": "senezh",
        "name": "322-й центр ССО «Сенеж» (в/ч 92154, Солнечногорськ)",
        "lat": 56.1800,
        "lon": 36.9800,
        "type": "command_center",
        "threat_level": "STRATEGIC",
        "sector": "Кібер / РЕБ / Спецоперації",
        "dossier": "Підрозділ розробки прошивок обходу РЕБ для ударних БпЛА (фігурант капітан Дмитро Кузнєцов 'Кодер')."
    }
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS coordinates in kilometers."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates forward azimuth bearing from point 1 to point 2 in degrees [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def angular_difference(angle1: float, angle2: float) -> float:
    """Calculates minimum angular difference between two bearings in degrees [0, 180]."""
    diff = abs(angle1 - angle2) % 360.0
    return diff if diff <= 180.0 else 360.0 - diff


def estimate_launch_origin(
    current_lat: float,
    current_lon: float,
    heading_deg: float,
    speed_kmh: float = 185.0,
    max_angular_tolerance: float = 35.0
) -> Optional[Dict]:
    """
    Reverse Launch Triangulation:
    Projects backwards along the reverse heading vector (heading + 180°)
    to match against verified enemy launch sites.
    """
    if heading_deg is None or current_lat is None or current_lon is None:
        return None

    reverse_bearing = (heading_deg + 180.0) % 360.0
    launch_sites = [f for f in KNOWN_ENEMY_FACILITIES if f.get("type") == "launch_site"]
    
    candidates = []
    for site in launch_sites:
        dist_km = haversine_km(current_lat, current_lon, site["lat"], site["lon"])
        bearing_to_site = calculate_bearing(current_lat, current_lon, site["lat"], site["lon"])
        angle_diff = angular_difference(reverse_bearing, bearing_to_site)
        
        if angle_diff <= max_angular_tolerance:
            flight_time_min = round((dist_km / max(speed_kmh, 50.0)) * 60.0)
            confidence = max(40, round(95 - (angle_diff * 1.5)))
            candidates.append({
                "site_id": site["id"],
                "site_name": site["name"],
                "site_lat": site["lat"],
                "site_lon": site["lon"],
                "distance_km": round(dist_km, 1),
                "angular_error_deg": round(angle_diff, 1),
                "flight_time_minutes": flight_time_min,
                "confidence_score": confidence,
                "sector": site["sector"],
                "dossier": site["dossier"]
            })

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x["angular_error_deg"], x["distance_km"]))
    return candidates[0]


def project_forward_substation_threats(
    current_lat: float,
    current_lon: float,
    heading_deg: float,
    speed_kmh: float = 185.0,
    substations: List[Dict] = None,
    max_cone_deg: float = 28.0,
    max_distance_km: float = 45.0
) -> List[Dict]:
    """
    Forward Threat Cone:
    Projects drone flight path forward and identifies high-voltage substations
    lying in the flight cone, computing accurate ETA.
    """
    if not substations or heading_deg is None:
        return []

    threats = []
    for sub in substations:
        s_lat = sub.get("lat")
        s_lon = sub.get("lon")
        if s_lat is None or s_lon is None:
            continue

        dist_km = haversine_km(current_lat, current_lon, s_lat, s_lon)
        if dist_km > max_distance_km or dist_km < 0.5:
            continue

        bearing_to_target = calculate_bearing(current_lat, current_lon, s_lat, s_lon)
        angle_diff = angular_difference(heading_deg, bearing_to_target)

        if angle_diff <= max_cone_deg:
            eta_min = round((dist_km / max(speed_kmh, 50.0)) * 60.0, 1)
            threats.append({
                "name": sub.get("name", "Енергопідстанція"),
                "lat": s_lat,
                "lon": s_lon,
                "distance_km": round(dist_km, 1),
                "angle_diff_deg": round(angle_diff, 1),
                "eta_minutes": eta_min,
                "voltage": sub.get("voltage", "110-750 kV"),
                "urgency": "IMMEDIATE" if eta_min <= 10.0 else "WARNING"
            })

    threats.sort(key=lambda x: x["eta_minutes"])
    return threats
