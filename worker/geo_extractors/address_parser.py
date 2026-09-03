"""
Deterministic Ukrainian Address and Highway Extractor for Kyiv & Oblast.
Parses natural language texts from OSINT Telegram channels into structured addresses.
"""
import re
from dataclasses import dataclass
from typing import List, Optional

from worker.canonical_geo import CANONICAL_TOPONYMS


@dataclass
class ParsedAddress:
    street: str
    building: Optional[str]
    district: Optional[str]
    city: Optional[str]
    raw: str
    normalized_query: str
    precision: str  # "address" (street+bldg) or "street" (street only)


# Kyiv microdistricts and administrative districts mapped to canonical district names
KYIV_DISTRICTS_MAP = {
    'оболон': ('Оболонський район', 'Київ'),
    'поділ': ('Подільський район', 'Київ'),
    'печерськ': ('Печерський район', 'Київ'),
    'солом\'ян': ('Солом\'янський район', 'Київ'),
    'соломян': ('Солом\'янський район', 'Київ'),
    'дарниц': ('Дарницький район', 'Київ'),
    'шевченківськ': ('Шевченківський район', 'Київ'),
    'голосіїв': ('Голосіївський район', 'Київ'),
    'святошин': ('Святошинський район', 'Київ'),
    'деснянськ': ('Деснянський район', 'Київ'),
    'дніпровськ': ('Дніпровський район', 'Київ'),
    'троєщин': ('Деснянський район', 'Київ'),
    'борщагівк': ('Святошинський район', 'Київ'),
    'позняк': ('Дарницький район', 'Київ'),
    'осокорк': ('Дарницький район', 'Київ'),
    'виноградар': ('Подільський район', 'Київ'),
    'шулявк': ('Шевченківський район', 'Київ'),
    'лук\'янівк': ('Шевченківський район', 'Київ'),
    'луканівк': ('Шевченківський район', 'Київ'),
    'видубич': ('Печерський район', 'Київ'),
    'березняк': ('Дніпровський район', 'Київ'),
    'воскресенк': ('Дніпровський район', 'Київ'),
    'теремк': ('Голосіївський район', 'Київ'),
    'деміївк': ('Голосіївський район', 'Київ'),
    'куренівк': ('Подільський район', 'Київ'),
    'нивк': ('Шевченківський район', 'Київ'),
    'русанівк': ('Дніпровський район', 'Київ'),
    'сирець': ('Шевченківський район', 'Київ'),
    'татарк': ('Шевченківський район', 'Київ'),
    'пріорк': ('Подільський район', 'Київ'),
    'чоколівк': ('Солом\'янський район', 'Київ'),
    'липк': ('Печерський район', 'Київ'),
}

# Regex for building numbers: strictly matches digits optionally followed by letter suffix or slash sub-number
BUILDING_REGEX = re.compile(
    r'(?:буд(?:\.|инку|инок)?\s*|№\s*)?(\b\d{1,4}(?:[/\-]\d{1,3}|[А-Яа-яA-Za-z](?=\s|$|,|\.))?)\b',
    re.IGNORECASE
)

# Adjective forms of highway / avenue to nominative mapping
HIGHWAY_ADJECTIVES = {
    'харківськ': 'Харківське шосе',
    'столичн': 'Столичне шосе',
    'брест-литовськ': 'Брест-Литовське шосе',
    'житомирськ': 'Житомирське шосе',
    'обухівськ': 'Обухівське шосе',
    'броварськ': 'Броварський проспект',
    'набережно-хрещатицьк': 'Набережно-Хрещатицька вулиця',
    'дніпровськ': 'Дніпровська набережна',
    'оболонськ': 'Оболонська набережна',
    'русанівськ': 'Русанівська набережна',
}


def _clean_street_name(name: str) -> str:
    """Removes trailing punctuation and noise words."""
    cleaned = re.sub(r'[\s,.;:!?\(\)]+$', '', name).strip()
    cleaned = re.sub(r'^(на|по|в|у|біля|поруч|район|р-н)\s+', '', cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def extract_addresses(text: str) -> List[ParsedAddress]:
    """Extracts structured street/building addresses from Ukrainian text."""
    if not text:
        return []

    text_lower = text.lower()
    found: List[ParsedAddress] = []

    # 1. Detect city and district context
    detected_city: Optional[str] = None
    detected_district: Optional[str] = None

    # Check settlements in Kyiv Oblast first (e.g. Бровари, Бориспіль, Буча, Ірпінь)
    for key, val in CANONICAL_TOPONYMS.items():
        if val and val.get("type") == "settlement" and key in text_lower:
            detected_city = val["canonical"]
            break

    # Check Kyiv districts
    for root, (district_name, city_name) in KYIV_DISTRICTS_MAP.items():
        if root in text_lower:
            detected_district = district_name
            if not detected_city:
                detected_city = city_name
            break

    # If text explicitly mentions Kyiv or no other settlement matched
    if "київ" in text_lower or "столиц" in text_lower or "киев" in text_lower or not detected_city:
        detected_city = detected_city or "Київ"

    effective_city = detected_city or "Київ"

    # Pattern A: Direct prefix indicators (вул., проспект, шосе, провулок, бульвар, узвіз, площа)
    prefix_patterns = [
        (r'(?:на\s+|по\s+|в\s+|у\s+)?(?:вул(?:\.|иці|иця|ицею|ицю)?)\s+([А-Яа-яІіЇїЄєҐґA-Za-z0-9\s\-\'\`]+?)(?=\s*,|\s+\d|\s+буд|\s+поруч|\s+біля|\s+у\s+києві|\s+в\s+києві|$)', 'вулиця'),
        (r'(?:на\s+|по\s+|в\s+|у\s+)?(?:пр(?:-т|\.|\b)|проспект(?:у|і|ом|а)?)\s+([А-Яа-яІіЇїЄєҐґA-Za-z0-9\s\-\'\`]+?)(?=\s*,|\s+\d|\s+буд|\s+поруч|\s+біля|\s+у\s+києві|\s+в\s+києві|$)', 'проспект'),
        (r'(?:на\s+|по\s+|в\s+|у\s+)?(?:бул(?:\.|ьварі|ьвар|ьваром)?)\s+([А-Яа-яІіЇїЄєҐґA-Za-z0-9\s\-\'\`]+?)(?=\s*,|\s+\d|\s+буд|\s+поруч|\s+біля|\s+у\s+києві|\s+в\s+києві|$)', 'бульвар'),
        (r'(?:на\s+|по\s+|в\s+|у\s+)?(?:пров(?:\.|улку|улок|улком)?)\s+([А-Яа-яІіЇїЄєҐґA-Za-z0-9\s\-\'\`]+?)(?=\s*,|\s+\d|\s+буд|\s+поруч|\s+біля|\s+у\s+києві|\s+в\s+києві|$)', 'провулок'),
        (r'(?:на\s+|по\s+|в\s+|у\s+)?(?:узвоз(?:і|у|ом)|узвіз)\s+([А-Яа-яІіЇїЄєҐґA-Za-z0-9\s\-\'\`]+?)(?=\s*,|\s+\d|\s+буд|\s+поруч|\s+біля|\s+у\s+києві|\s+в\s+києві|$)', 'узвіз'),
        (r'(?:на\s+|по\s+|в\s+|у\s+)?(?:пл(?:\.|ощі|оща|ощею)?)\s+([А-Яа-яІіЇїЄєҐґA-Za-z0-9\s\-\'\`]+?)(?=\s*,|\s+\d|\s+буд|\s+поруч|\s+біля|\s+у\s+києві|\s+в\s+києві|$)', 'площа'),
        (r'(?:на\s+|по\s+|в\s+|у\s+)?(?:набережн(?:ій|а|ою))\s+([А-Яа-яІіЇїЄєҐґA-Za-z0-9\s\-\'\`]+?)(?=\s*,|\s+\d|\s+буд|\s+поруч|\s+біля|\s+у\s+києві|\s+в\s+києві|$)', 'набережна'),
    ]

    for pat, st_type in prefix_patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            raw_name = _clean_street_name(match.group(1))
            if len(raw_name) < 3 or raw_name.lower() in ('києві', 'області', 'районі', 'бучанському', 'обухівському'):
                continue

            # Look for building number in trailing text window (up to 25 chars)
            tail = text[match.end():match.end() + 25]
            building = None
            bm = BUILDING_REGEX.search(tail)
            if bm:
                b_cand = bm.group(1).strip()
                if b_cand and not b_cand.startswith('0') and len(b_cand) <= 8 and not b_cand.isalpha():
                    building = b_cand.replace(' ', '')

            # Normalize street
            normalized_street = f"{st_type} {raw_name.title()}" if not raw_name.lower().startswith(st_type) else raw_name.title()

            norm_parts = [normalized_street]
            if building:
                norm_parts.append(building)
            norm_parts.append(effective_city)
            norm_parts.append("Україна")

            found.append(ParsedAddress(
                street=normalized_street,
                building=building,
                district=detected_district,
                city=effective_city,
                raw=match.group(0),
                normalized_query=", ".join(norm_parts),
                precision="address" if building else "street"
            ))

    # Pattern B: Suffix / Adjective indicators (e.g., "на Харківському шосе", "Столичному шосе")
    suffix_patterns = [
        (r'(?:на\s+|по\s+|в\s+|у\s+)?([А-Яа-яІіЇїЄєҐґA-Za-z\-]+(?:ськ|цьк|зьк)[а-яіїє]*)\s+(?:шосе|трас[а-яіїє]*|магістрал[а-яіїє]*)', 'шосе'),
        (r'(?:на\s+|по\s+|в\s+|у\s+)?([А-Яа-яІіЇїЄєҐґA-Za-z\-]+(?:ськ|цьк|зьк)[а-яіїє]*)\s+(?:набережн[а-яіїє]*)', 'набережна'),
    ]

    for pat, st_type in suffix_patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            adj_raw = match.group(1).strip()
            # Check known highway adjectives
            matched_name = None
            for adj_root, canon_name in HIGHWAY_ADJECTIVES.items():
                if adj_root in adj_raw.lower():
                    matched_name = canon_name
                    break

            street_name = matched_name or f"{adj_raw.title()} {st_type}"

            # Look for building
            tail = text[match.end():match.end() + 25]
            building = None
            bm = BUILDING_REGEX.search(tail)
            if bm:
                b_cand = bm.group(1).strip()
                if b_cand and not b_cand.startswith('0') and len(b_cand) <= 8 and not b_cand.isalpha():
                    building = b_cand.replace(' ', '')

            norm_parts = [street_name]
            if building:
                norm_parts.append(building)
            norm_parts.append(effective_city)
            norm_parts.append("Україна")

            found.append(ParsedAddress(
                street=street_name,
                building=building,
                district=detected_district,
                city=effective_city,
                raw=match.group(0),
                normalized_query=", ".join(norm_parts),
                precision="address" if building else "street"
            ))

    return found
