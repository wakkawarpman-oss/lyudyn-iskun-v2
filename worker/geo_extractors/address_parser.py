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


# Multi-city microdistricts and administrative districts mapped to canonical district & city names
CITY_DISTRICTS_MAP = {
    # ── Київ ──
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

    # ── Одеса (з урахуванням декомунізації та морських векторів) ──
    'пересип': ('Пересипський район', 'Одеса'),
    'суворовськ': ('Пересипський район', 'Одеса'),
    'поскот': ('Пересипський район', 'Одеса'),
    'котовськ': ('Пересипський район', 'Одеса'),
    'лузанівк': ('Пересипський район', 'Одеса'),
    'хаджибей': ('Хаджибейський район', 'Одеса'),
    'малиновськ': ('Хаджибейський район', 'Одеса'),
    'черемушк': ('Хаджибейський район', 'Одеса'),
    'черьомушк': ('Хаджибейський район', 'Одеса'),
    'слобідк': ('Хаджибейський район', 'Одеса'),
    'молдаванк': ('Хаджибейський район', 'Одеса'),
    'приморськ': ('Приморський район', 'Одеса'),
    'ланжерон': ('Приморський район', 'Одеса'),
    'аркаді': ('Приморський район', 'Одеса'),
    'таїров': ('Київський район', 'Одеса'),
    'таиров': ('Київський район', 'Одеса'),
    'вузівськ': ('Київський район', 'Одеса'),
    'чорноморк': ('Київський район', 'Одеса'),
    'чорноморськ': ('Чорноморськ', 'Одеська область'),
    'южне': ('Южне', 'Одеська область'),

    # ── Дніпро ──
    'соборн': ('Соборний район', 'Дніпро'),
    'перемог': ('Соборний район', 'Дніпро'),
    'нагірн': ('Соборний район', 'Дніпро'),
    'топол': ('Шевченківський район', 'Дніпро'),
    'бабушкін': ('Шевченківський район', 'Дніпро'),
    'чечелів': ('Чечелівський район', 'Дніпро'),
    'красногвардійськ': ('Чечелівський район', 'Дніпро'),
    'південмаш': ('Чечелівський район', 'Дніпро'),
    'парус': ('Новокодацький район', 'Дніпро'),
    'червоний камін': ('Новокодацький район', 'Дніпро'),
    'самарськ': ('Самарський район', 'Дніпро'),
    'придніпров': ('Самарський район', 'Дніпро'),
    'ігрен': ('Самарський район', 'Дніпро'),
    'амур': ('Амур-Нижньодніпровський район', 'Дніпро'),
    'анд': ('Амур-Нижньодніпровський район', 'Дніпро'),
    'сонячн': ('Амур-Нижньодніпровський район', 'Дніпро'),
    'індустріальн': ('Індустріальний район', 'Дніпро'),
    'слобожанськ': ('Індустріальний район', 'Дніпро'),

    # ── Запоріжжя ──
    'вознесенівськ': ('Вознесенівський район', 'Запоріжжя'),
    'бородінськ': ('Дніпровський район', 'Запоріжжя'),
    'дніпрогес': ('Дніпровський район', 'Запоріжжя'),
    'кічкас': ('Заводський район', 'Запоріжжя'),
    'павло-кічкас': ('Заводський район', 'Запоріжжя'),
    'космос': ('Комунарський район', 'Запоріжжя'),
    'піски': ('Комунарський район', 'Запоріжжя'),
    'бабурк': ('Хортицький район', 'Запоріжжя'),
    'хортиц': ('Хортицький район', 'Запоріжжя'),
    'мотор січ': ('Шевченківський район', 'Запоріжжя'),

    # ── Харків ──
    'салтів': ('Салтівський район', 'Харків'),
    'салтов': ('Салтівський район', 'Харків'),
    'павлове пол': ('Шевченківський район', 'Харків'),
    'олексіїв': ('Шевченківський район', 'Харків'),
    'холодна гор': ('Холодногірський район', 'Харків'),
    'нова баварі': ('Новобаварський район', 'Харків'),
    'основ': ('Основ\'янський район', 'Харків'),
    'слобідськ': ('Слобідський район', 'Харків'),
    'немишл': ('Немишлянський район', 'Харків'),
    'хтз': ('Індустріальний район', 'Харків'),
    'роган': ('Індустріальний район', 'Харків'),

    # ── Львів ──
    'сихів': ('Сихівський район', 'Львів'),
    'рясн': ('Шевченківський район', 'Львів'),
    'замарстинів': ('Шевченківський район', 'Львів'),
    'кульпарків': ('Франківський район', 'Львів'),
    'личаків': ('Личаківський район', 'Львів'),
    'левандівк': ('Залізничний район', 'Львів'),
    'галицьк': ('Галицький район', 'Львів'),

    # ── Миколаїв ──
    'варварів': ('Центральний район', 'Миколаїв'),
    'солян': ('Центральний район', 'Миколаїв'),
    'намив': ('Заводський район', 'Миколаїв'),
    'водопій': ('Інгульський район', 'Миколаїв'),
    'корабельн': ('Корабельний район', 'Миколаїв'),
    'кульбакин': ('Корабельний район', 'Миколаїв'),

    # ── Суми ──
    'ковпаківськ': ('Ковпаківський район', 'Суми'),
    'курськ': ('Ковпаківський район', 'Суми'),
    'зарічн': ('Зарічний район', 'Суми'),
    'хіммістеч': ('Зарічний район', 'Суми'),
    'баси': ('Зарічний район', 'Суми'),
    'сумихімпром': ('Зарічний район', 'Суми'),

    # ── Полтава ──
    'половк': ('Київський район', 'Полтава'),
    'левад': ('Подільський район', 'Полтава'),
    'алмазн': ('Шевченківський район', 'Полтава'),
    'сади': ('Шевченківський район', 'Полтава'),
}

# Backward compatibility alias
KYIV_DISTRICTS_MAP = {k: v for k, v in CITY_DISTRICTS_MAP.items() if v[1] == 'Київ'}

# Major Ukrainian metropolitan centers regex patterns with word boundary matching
METRO_CITY_PATTERNS = [
    (re.compile(r'\b(?:м\.|місто\s+)?(одес[аіеиу]|одессой|одессою)\b', re.IGNORECASE), 'Одеса'),
    (re.compile(r'\b(?:м\.|місто\s+)?(харків|харков|харкові|харькове|харкова|харькова|харкову|харькову)\b', re.IGNORECASE), 'Харків'),
    (re.compile(r'\b(?:м\.|місто\s+)?(дніпр[оеа]|днепр[оеа]|дніпрі|днепре)\b', re.IGNORECASE), 'Дніпро'),
    (re.compile(r'\b(?:м\.|місто\s+)?(запоріжж[яі]|запорожь[ея]|запоріжжям)\b', re.IGNORECASE), 'Запоріжжя'),
    (re.compile(r'\b(?:м\.|місто\s+)?(львів|львов|львові|львове|львова|львову)\b', re.IGNORECASE), 'Львів'),
    (re.compile(r'\b(?:м\.|місто\s+)?(миколаїв|николаев|миколаєві|николаеве|миколаєва|николаева)\b', re.IGNORECASE), 'Миколаїв'),
    (re.compile(r'\b(?:м\.|місто\s+)?(суми|сумах|сум|сумам)\b', re.IGNORECASE), 'Суми'),
    (re.compile(r'\b(?:м\.|місто\s+)?(полтав[аіеиу]|полтавой|полтавою)\b', re.IGNORECASE), 'Полтава'),
    (re.compile(r'\b(?:м\.|місто\s+)?(київ|киев|києві|киеве|києва|киева|столиц[іеяю])\b', re.IGNORECASE), 'Київ'),
]

# Backward compatibility alias
METRO_CITY_STEMS = {
    'одес': 'Одеса',
    'харків': 'Харків',
    'дніпр': 'Дніпро',
    'запоріж': 'Запоріжжя',
    'львів': 'Львів',
    'миколаїв': 'Миколаїв',
    'суми': 'Суми',
    'полтав': 'Полтава',
    'київ': 'Київ',
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
    """Extracts structured street/building addresses from Ukrainian text across 9 major cities."""
    if not text:
        return []

    text_lower = text.lower()
    found: List[ParsedAddress] = []

    # 1. Detect city and district context
    detected_city: Optional[str] = None
    detected_district: Optional[str] = None

    # 1. Check settlements in Canonical Toponyms (e.g. Бровари, Бориспіль, Чорноморськ, Южне)
    for key, val in CANONICAL_TOPONYMS.items():
        if val and val.get("type") in ("settlement", "raion"):
            if re.search(r'\b' + re.escape(key) + r'\b', text_lower):
                detected_city = val["canonical"]
                break

    # 2. Check explicit major metropolitan city mentions
    if not detected_city:
        for pat, c_name in METRO_CITY_PATTERNS:
            m = pat.search(text)
            if m:
                start, end = m.start(), m.end()
                pre_ctx = text[max(0, start - 15):start].lower()
                post_ctx = text[end:min(len(text), end + 20)].lower()
                # Guard: Ensure this isn't part of a highway/street adjective like "Харківському шосе" or "вул. Київська"
                if any(kw in pre_ctx for kw in ('вул', 'вулиц', 'пр-т', 'проспект', 'бул', 'бульвар', 'пров')):
                    continue
                if any(kw in post_ctx for kw in ('шосе', 'проспект', 'вулиц', 'трас', 'набережн', 'бульвар')):
                    continue
                detected_city = c_name
                break

    # 3. Check multi-city districts and microdistricts
    for root, (district_name, city_name) in CITY_DISTRICTS_MAP.items():
        if root in text_lower:
            # If city was already detected, ensure district matches the same city
            if detected_city and detected_city != city_name:
                continue
            detected_district = district_name
            if not detected_city:
                detected_city = city_name
            break

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
