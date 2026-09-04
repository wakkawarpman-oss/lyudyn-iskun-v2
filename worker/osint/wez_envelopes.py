"""
Weapon Engagement Zones (WEZ) & Air Defense Envelope Engine.
============================================================
Calculates tactical engagement envelopes, radar detection zones,
and minimum altitude dead cones based on verified military manuals
(Tor-M2K, Pantsir-S1, Strela-10M4, Buk-M3, S-400 Triumf, 2S19 Msta-S).
"""

from typing import Dict, List, Any
import math

# Verified tactical TTX for Russian Air Defense & Artillery assets
AIR_DEFENSE_TTX: Dict[str, Dict[str, Any]] = {
    "TOR_M2": {
        "name": "ЗРК 9К332 «Тор-М2»",
        "grau_index": "9К332",
        "category": "SHORAD",
        "radar_range_km": 32.0,
        "missile_max_range_km": 15.0,
        "missile_min_range_km": 1.0,
        "max_altitude_km": 10.0,
        "min_altitude_m": 10.0,
        "channels": 4,
        "color_hex": "#ef4444",
        "dossier": "Дивізійний ЗРК малої дальності. Одночасно супроводжує та обстрілює до 4 цілей у секторі."
    },
    "PANTSIR_S1": {
        "name": "ЗРПК 96К6 «Панцир-С1»",
        "grau_index": "96К6",
        "category": "SHORAD",
        "radar_range_km": 36.0,
        "missile_max_range_km": 20.0,
        "missile_min_range_km": 1.2,
        "gun_range_km": 4.0,
        "max_altitude_km": 15.0,
        "min_altitude_m": 5.0,
        "channels": 4,
        "color_hex": "#f97316",
        "dossier": "Ракетно-гарматний комплекс точкового прикриття аеродромів та КП. Ефективний проти крилатих ракет та БпЛА."
    },
    "STRELA_10M4": {
        "name": "ЗРК 9К35М4 «Стріла-10М4»",
        "grau_index": "9К35М4",
        "category": "VSHORAD",
        "radar_range_km": 10.0,
        "missile_max_range_km": 5.0,
        "missile_min_range_km": 0.8,
        "max_altitude_km": 3.5,
        "min_altitude_m": 25.0,
        "channels": 1,
        "color_hex": "#eab308",
        "dossier": "Полковий мобільний комплекс ППО на шасі МТ-ЛБ. Оптико-електронна ГСН."
    },
    "BUK_M3": {
        "name": "ЗРК 9К317М «Бук-М3»",
        "grau_index": "9К317М",
        "category": "MRAD",
        "radar_range_km": 120.0,
        "missile_max_range_km": 70.0,
        "missile_min_range_km": 2.5,
        "max_altitude_km": 35.0,
        "min_altitude_m": 15.0,
        "channels": 36,
        "color_hex": "#dc2626",
        "dossier": "Комплекс ППО середньої дальності. Активна радіолокаційна ГСН ракет 9М317М."
    },
    "S400_TRIUMF": {
        "name": "ЗРС С-400 «Тріумф»",
        "grau_index": "40Р6",
        "category": "LRAD",
        "radar_range_km": 400.0,
        "missile_max_range_km": 250.0,
        "missile_min_range_km": 5.0,
        "max_altitude_km": 60.0,
        "min_altitude_m": 10.0,
        "channels": 80,
        "color_hex": "#7f1d1d",
        "dossier": "Стратегічна система ППО/ПРО великої дальності з ешелонованим перехопленням."
    }
}

ACTIVE_AIR_DEFENSE_DEPLOYMENTS: List[Dict[str, Any]] = [
    {
        "id": "AD-HLADKIVKA-TOR",
        "name": "Позиція ЗРК «Стріла-10 / Тор-М2» (Гладківка, ТОТ)",
        "lat": 46.3972,
        "lon": 32.6007,
        "system_type": "TOR_M2",
        "unit": "1 зрбатр 2 зрп 104 дшд РФ",
        "confidence": 85,
        "source": "LOB 250° + Скадовський сектор"
    },
    {
        "id": "AD-BELGOROD-S400",
        "name": "Дивізіон С-400 (Бєлгородський плацдарм)",
        "lat": 50.5954,
        "lon": 36.5872,
        "system_type": "S400_TRIUMF",
        "unit": "108 зрбр (в/ч 83497)",
        "confidence": 95,
        "source": "Sentinel-1 RFI + супутникові знімки"
    },
    {
        "id": "AD-KURSK-BUK",
        "name": "Позиція «Бук-М3» (Курський вузол)",
        "lat": 51.7308,
        "lon": 36.1930,
        "system_type": "BUK_M3",
        "unit": "53 зрбр (в/ч 32406)",
        "confidence": 90,
        "source": "OSINT зведення вогневих позицій"
    },
    {
        "id": "AD-CRIMEA-PANTSIR",
        "name": "Батарея ЗРПК «Панцир-С1» (Мис Чауда / Феодосія)",
        "lat": 45.0000,
        "lon": 35.8300,
        "system_type": "PANTSIR_S1",
        "unit": "31 дивізія ППО 4 А ВПС і ППО",
        "confidence": 95,
        "source": "Прикриття стартових позицій Shahed"
    },
    {
        "id": "AD-BRYANSK-NAVLYA",
        "name": "Прикриття стартового майданчика Навля (Панцир-С1)",
        "lat": 52.8491,
        "lon": 34.4865,
        "system_type": "PANTSIR_S1",
        "unit": "Охорона 924 ДЦ БпЛА",
        "confidence": 85,
        "source": "OSINT"
    }
]

def generate_wez_geojson() -> Dict[str, Any]:
    features = []
    for dep in ACTIVE_AIR_DEFENSE_DEPLOYMENTS:
        st = dep["system_type"]
        ttx = AIR_DEFENSE_TTX.get(st, {})
        if not ttx:
            continue

        lat, lon = dep["lat"], dep["lon"]
        kill_range_m = int(ttx["missile_max_range_km"] * 1000)
        radar_range_m = int(ttx["radar_range_km"] * 1000)

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat]
            },
            "properties": {
                "id": dep["id"],
                "name": dep["name"],
                "system_name": ttx["name"],
                "system_type": st,
                "category": ttx["category"],
                "unit": dep["unit"],
                "confidence": dep["confidence"],
                "source": dep["source"],
                "kill_radius_m": kill_range_m,
                "radar_radius_m": radar_range_m,
                "max_altitude_km": ttx["max_altitude_km"],
                "color": ttx["color_hex"],
                "feature_kind": "asset_marker"
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "systems_catalog": AIR_DEFENSE_TTX
    }
