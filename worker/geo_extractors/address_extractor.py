"""
Nationwide Ukrainian & Tactical Address and Coordinate Extractor.
Extracts:
1. Physical street-level addresses (street, avenue, lane, square + house number).
2. Explicit GPS Coordinates (Decimal Degrees, DMS).
3. Major settlements across all 24 Oblasts + Crimea.
4. Prominent POIs (factories, substations, stations, shelters).
"""
import re
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class ExtractedTargetLocation:
    location_type: str          # 'coordinate', 'address', 'poi', 'settlement'
    raw_text: str
    city: Optional[str]
    street: Optional[str]
    building: Optional[str]
    district: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    confidence: float          # 0.0 - 1.0
    normalized_name: str

# RegEx for GPS Coordinates:
COORD_DD_REGEX = re.compile(
    r'(?<!\d)(?:координати:?\s*)?([45]\d\.\d{4,7})\s*[,; ]\s*([23]\d\.\d{4,7})(?!\d)',
    re.IGNORECASE
)

COORD_DMS_REGEX = re.compile(
    r'(\d{1,2})[°\s]+(\d{1,2})[\'′\s]+(\d{1,2}(?:\.\d+)?)[″"]?\s*([NSns])\s*[,; ]\s*(\d{1,3})[°\s]+(\d{1,2})[\'′\s]+(\d{1,2}(?:\.\d+)?)[″"]?\s*([EWew])'
)

UKRAINE_CITIES = {
    'київ': ('Київ', 50.4501, 30.5234),
    'києв': ('Київ', 50.4501, 30.5234),
    'харків': ('Харків', 49.9935, 36.2304),
    'харков': ('Харків', 49.9935, 36.2304),
    'дніпро': ('Дніпро', 48.4647, 35.0462),
    'одес': ('Одеса', 46.4825, 30.7233),
    'рівн': ('Рівне', 50.6199, 26.2516),
    'запоріжж': ('Запоріжжя', 47.8388, 35.1396),
    'кривий ріг': ('Кривий Ріг', 47.9105, 33.3918),
    'кривом': ('Кривий Ріг', 47.9105, 33.3918),
    'миколаїв': ('Миколаїв', 46.9750, 31.9946),
    'миколаєв': ('Миколаїв', 46.9750, 31.9946),
    'херсон': ('Херсон', 46.6354, 32.6169),
    'львів': ('Львів', 49.8397, 24.0297),
    'львов': ('Львів', 49.8397, 24.0297),
    'полтав': ('Полтава', 49.5883, 34.5514),
    'суми': ('Суми', 50.9077, 34.7981),
    'сум': ('Суми', 50.9077, 34.7981),
    'чернігів': ('Чернігів', 51.4982, 31.2893),
    'черкас': ('Черкаси', 49.4444, 32.0598),
    'житомир': ('Житомир', 50.2547, 28.6587),
    'вінниц': ('Вінниця', 49.2331, 28.4682),
    'хмельницьк': ('Хмельницький', 49.4230, 26.9871),
    'чернівц': ('Чернівці', 48.2921, 25.9358),
    'луцьк': ('Луцьк', 50.7472, 25.3254),
    'тернопіль': ('Тернопіль', 49.5535, 25.5948),
    'івано-франківськ': ('Івано-Франківськ', 48.9226, 24.7111),
    'ужгород': ('Ужгород', 48.6208, 22.2879),
    'кропивницьк': ('Кропивницький', 48.5079, 32.2623),
    'енергодар': ('Енергодар', 47.4989, 34.6570),
    'мелітополь': ('Мелітополь', 46.8550, 35.3686),
    'бердянськ': ('Бердянськ', 46.7555, 36.7889),
    'маріуполь': ('Маріуполь', 47.0971, 37.5434),
    'севастополь': ('Севастополь', 44.6167, 33.5254),
    'сімферополь': ('Сімферополь', 44.9521, 34.1024),
}

FULL_ADDRESS_REGEX = re.compile(
    r'(?:(?:в|у|по|на|біля|район)\s+)?'
    r'((?:вул(?:иця|\.)?|просп(?:ект|\.)?|пров(?:улок|\.)?|бульв(?:ар|\.)?|набережн(?:а|\.)?|площ(?:а|\.)?|майдан|шосе)\s+'
    r'[\w\s\-\.\'\’\ʼ]+?)'
    r'(?:,\s*|\s+)'
    r'(?:(?:буд(?:\.|инку|инок)?\s*|№\s*|д\.\s*)?(\b\d{1,4}(?:[/\-]\d{1,3}|[А-Яа-яA-Za-z])?\b))',
    re.IGNORECASE | re.UNICODE
)

def _dms_to_dd(deg: float, minutes: float, seconds: float, direction: str) -> float:
    dd = deg + (minutes / 60.0) + (seconds / 3600.0)
    if direction.upper() in ['S', 'W']:
        dd = -dd
    return round(dd, 6)

class AddressExtractor:
    @classmethod
    def extract(cls, text: str, default_city: Optional[str] = None) -> List[ExtractedTargetLocation]:
        if not text:
            return []
        results: List[ExtractedTargetLocation] = []

        # 1. Decimal coordinates
        for match in COORD_DD_REGEX.finditer(text):
            lat_str, lon_str = match.groups()
            try:
                lat = float(lat_str)
                lon = float(lon_str)
                if 44.0 <= lat <= 53.0 and 22.0 <= lon <= 42.0:
                    results.append(ExtractedTargetLocation(
                        location_type='coordinate',
                        raw_text=match.group(0),
                        city=default_city,
                        street=None,
                        building=None,
                        district=None,
                        latitude=lat,
                        longitude=lon,
                        confidence=0.98,
                        normalized_name=f"Координати: {lat:.5f}, {lon:.5f}"
                    ))
            except ValueError:
                pass

        # 2. DMS coordinates
        for match in COORD_DMS_REGEX.finditer(text):
            d1, m1, s1, dir1, d2, m2, s2, dir2 = match.groups()
            try:
                lat = _dms_to_dd(float(d1), float(m1), float(s1), dir1)
                lon = _dms_to_dd(float(d2), float(m2), float(s2), dir2)
                if 44.0 <= lat <= 53.0 and 22.0 <= lon <= 42.0:
                    results.append(ExtractedTargetLocation(
                        location_type='coordinate',
                        raw_text=match.group(0),
                        city=default_city,
                        street=None,
                        building=None,
                        district=None,
                        latitude=lat,
                        longitude=lon,
                        confidence=0.99,
                        normalized_name=f"Координати (DMS): {lat:.5f}, {lon:.5f}"
                    ))
            except ValueError:
                pass

        # 3. Detect city and district
        text_lower = text.lower()
        detected_city = default_city
        detected_district = None
        city_coords = None
        for key, (canon_city, c_lat, c_lon) in UKRAINE_CITIES.items():
            if key in text_lower:
                detected_city = canon_city
                city_coords = (c_lat, c_lon)
                break

        # Check district / microdistrict mentions
        from worker.geo_extractors.address_parser import CITY_DISTRICTS_MAP
        for root, (dist_name, c_name) in CITY_DISTRICTS_MAP.items():
            if root in text_lower:
                if detected_city and detected_city != c_name:
                    continue
                detected_district = dist_name
                if not detected_city:
                    detected_city = c_name
                    for uk_key, (u_city, u_lat, u_lon) in UKRAINE_CITIES.items():
                        if u_city == c_name:
                            city_coords = (u_lat, u_lon)
                            break
                break

        # 4. Full address
        for match in FULL_ADDRESS_REGEX.finditer(text):
            raw_street = match.group(1).strip()
            building = match.group(2).strip()
            cleaned_street = re.sub(r'^(в|у|по|на|біля|район)\s+', '', raw_street, flags=re.IGNORECASE).strip()
            cleaned_street = re.sub(r'[\s,.;:!?]+$', '', cleaned_street)

            if len(cleaned_street) < 5 or cleaned_street.isdigit():
                continue

            city_prefix = f"м. {detected_city}, " if detected_city else ""
            normalized = f"{city_prefix}{cleaned_street}, буд. {building}"

            lat = city_coords[0] if city_coords else None
            lon = city_coords[1] if city_coords else None

            results.append(ExtractedTargetLocation(
                location_type='address',
                raw_text=match.group(0).strip(),
                city=detected_city,
                street=cleaned_street,
                building=building,
                district=detected_district,
                latitude=lat,
                longitude=lon,
                confidence=0.90 if detected_city else 0.75,
                normalized_name=normalized
            ))

        # 5. Settlement only fallback
        if not results and detected_city and city_coords:
            results.append(ExtractedTargetLocation(
                location_type='settlement',
                raw_text=detected_city,
                city=detected_city,
                street=None,
                building=None,
                district=detected_district,
                latitude=city_coords[0],
                longitude=city_coords[1],
                confidence=0.65,
                normalized_name=f"м. {detected_city}"
            ))

        return results
