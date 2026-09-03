"""
Canonical Toponym Normalizer & Geographic Coordinate Resolver
Resolves truncated stem words, colloquial terms, district aliases, and transliterations
to standardized Ukrainian canonical names with precise coordinates.
"""
from typing import Tuple, Optional, Dict
import re

# Canonical settlements & district mappings with high-precision PostGIS coordinates (WGS84)
CANONICAL_TOPONYMS: Dict[str, Dict] = {
    # ── Kyiv Capital & Districts ──
    "київ": {"canonical": "Київ", "lat": 50.450034, "lon": 30.524136, "type": "region"},
    "kyiv": {"canonical": "Київ", "lat": 50.450034, "lon": 30.524136, "type": "region"},
    "м. київ": {"canonical": "Київ", "lat": 50.450034, "lon": 30.524136, "type": "region"},
    "столиц": {"canonical": "Київ", "lat": 50.450034, "lon": 30.524136, "type": "region"},
    "столиця": {"canonical": "Київ", "lat": 50.450034, "lon": 30.524136, "type": "region"},
    "київ та область": {"canonical": "Київ та область", "lat": 50.450034, "lon": 30.524136, "type": "region"},
    "київська область": {"canonical": "Київська область", "lat": 50.178595, "lon": 30.492488, "type": "region"},
    "київщина": {"canonical": "Київська область", "lat": 50.178595, "lon": 30.492488, "type": "region"},

    # Kyiv Districts
    "голосіївськ": {"canonical": "Голосіївський район, Київ", "lat": 50.3951, "lon": 30.5126, "type": "district"},
    "голосіївський район": {"canonical": "Голосіївський район, Київ", "lat": 50.3951, "lon": 30.5126, "type": "district"},
    "голосієво": {"canonical": "Голосіївський район, Київ", "lat": 50.3951, "lon": 30.5126, "type": "district"},
    "дарницьк": {"canonical": "Дарницький район, Київ", "lat": 50.4132, "lon": 30.6558, "type": "district"},
    "дарницький район": {"canonical": "Дарницький район, Київ", "lat": 50.4132, "lon": 30.6558, "type": "district"},
    "дарниц": {"canonical": "Дарницький район, Київ", "lat": 50.4132, "lon": 30.6558, "type": "district"},
    "деснянськ": {"canonical": "Деснянський район, Київ", "lat": 50.5052, "lon": 30.6015, "type": "district"},
    "деснянський район": {"canonical": "Деснянський район, Київ", "lat": 50.5052, "lon": 30.6015, "type": "district"},
    "дніпровськ": {"canonical": "Дніпровський район, Київ", "lat": 50.4528, "lon": 30.5982, "type": "district"},
    "дніпровський район": {"canonical": "Дніпровський район, Київ", "lat": 50.4528, "lon": 30.5982, "type": "district"},
    "оболонськ": {"canonical": "Оболонський район, Київ", "lat": 50.510735, "lon": 30.50337, "type": "district"},
    "оболонський район": {"canonical": "Оболонський район, Київ", "lat": 50.510735, "lon": 30.50337, "type": "district"},
    "оболон": {"canonical": "Оболонський район, Київ", "lat": 50.510735, "lon": 30.50337, "type": "district"},
    "оболонь": {"canonical": "Оболонський район, Київ", "lat": 50.510735, "lon": 30.50337, "type": "district"},
    "печерськ": {"canonical": "Печерський район, Київ", "lat": 50.432204, "lon": 30.544583, "type": "district"},
    "печерський район": {"canonical": "Печерський район, Київ", "lat": 50.432204, "lon": 30.544583, "type": "district"},
    "подільськ": {"canonical": "Подільський район, Київ", "lat": 50.469128, "lon": 30.516624, "type": "district"},
    "подільський район": {"canonical": "Подільський район, Київ", "lat": 50.469128, "lon": 30.516624, "type": "district"},
    "поділ": {"canonical": "Подільський район, Київ", "lat": 50.469128, "lon": 30.516624, "type": "district"},
    "святошинськ": {"canonical": "Святошинський район, Київ", "lat": 50.453616, "lon": 30.371093, "type": "district"},
    "святошинський район": {"canonical": "Святошинський район, Київ", "lat": 50.453616, "lon": 30.371093, "type": "district"},
    "святошин": {"canonical": "Святошинський район, Київ", "lat": 50.453616, "lon": 30.371093, "type": "district"},
    "солом'янськ": {"canonical": "Солом'янський район, Київ", "lat": 50.42053, "lon": 30.458482, "type": "district"},
    "солом'янський район": {"canonical": "Солом'янський район, Київ", "lat": 50.42053, "lon": 30.458482, "type": "district"},
    "солом'янка": {"canonical": "Солом'янський район, Київ", "lat": 50.433513, "lon": 30.479601, "type": "district"},
    "шевченківськ": {"canonical": "Шевченківський район, Київ", "lat": 50.46288, "lon": 30.451795, "type": "district"},
    "шевченківський район": {"canonical": "Шевченківський район, Київ", "lat": 50.46288, "lon": 30.451795, "type": "district"},
    "луцьк": None, # Non-Kyiv blacklist

    # Micro-districts, Historical Localities & Metro areas in Kyiv
    "татарка": {"canonical": "Татарка, Шевченківський район, Київ", "lat": 50.4688, "lon": 30.4912, "type": "microdistrict", "district_id": "shevchenko"},
    "виноградар": {"canonical": "Виноградар, Подільський район, Київ", "lat": 50.5132, "lon": 30.4185, "type": "microdistrict", "district_id": "podil"},
    "вітряні гори": {"canonical": "Вітряні Гори, Подільський район, Київ", "lat": 50.5050, "lon": 30.4350, "type": "microdistrict", "district_id": "podil"},
    "пріорка": {"canonical": "Пріорка, Подільський район, Київ", "lat": 50.4998, "lon": 30.4612, "type": "microdistrict", "district_id": "podil"},
    "воздвиженка": {"canonical": "Воздвиженка, Подільський район, Київ", "lat": 50.4615, "lon": 30.5120, "type": "microdistrict", "district_id": "podil"},
    "кудрявець": {"canonical": "Кудрявець, Шевченківський район, Київ", "lat": 50.4570, "lon": 30.5010, "type": "microdistrict", "district_id": "shevchenko"},
    "шулявка": {"canonical": "Шулявка, Шевченківський район, Київ", "lat": 50.449983, "lon": 30.44405, "type": "microdistrict", "district_id": "shevchenko"},
    "лук'янівка": {"canonical": "Лук'янівка, Шевченківський район, Київ", "lat": 50.464446, "lon": 30.47515, "type": "microdistrict", "district_id": "shevchenko"},
    "сирець": {"canonical": "Сирець, Шевченківський район, Київ", "lat": 50.4760, "lon": 30.4380, "type": "microdistrict", "district_id": "shevchenko"},
    "дорогожичі": {"canonical": "Дорогожичі, Шевченківський район, Київ", "lat": 50.4735, "lon": 30.4490, "type": "microdistrict", "district_id": "shevchenko"},
    "нивки": {"canonical": "Нивки, Шевченківський район, Київ", "lat": 50.4589, "lon": 30.4052, "type": "microdistrict", "district_id": "shevchenko"},
    "кпі": {"canonical": "КПІ, Солом'янський район, Київ", "lat": 50.4501, "lon": 30.4550, "type": "microdistrict", "district_id": "solomiansk"},
    "політех": {"canonical": "КПІ, Солом'янський район, Київ", "lat": 50.4501, "lon": 30.4550, "type": "microdistrict", "district_id": "solomiansk"},
    "відрадний": {"canonical": "Відрадний, Солом'янський район, Київ", "lat": 50.4280, "lon": 30.4210, "type": "microdistrict", "district_id": "solomiansk"},
    "чоколівка": {"canonical": "Чоколівка, Солом'янський район, Київ", "lat": 50.4215, "lon": 30.4520, "type": "microdistrict", "district_id": "solomiansk"},
    "жуляни": {"canonical": "Жуляни, Солом'янський район, Київ", "lat": 50.3950, "lon": 30.4380, "type": "microdistrict", "district_id": "solomiansk"},
    "совки": {"canonical": "Совки, Солом'янський район, Київ", "lat": 50.4030, "lon": 30.4780, "type": "microdistrict", "district_id": "solomiansk"},
    "караваєві дачі": {"canonical": "Караваєві Дачі, Солом'янський район, Київ", "lat": 50.4350, "lon": 30.4450, "type": "microdistrict", "district_id": "solomiansk"},
    "кардачі": {"canonical": "Караваєві Дачі, Солом'янський район, Київ", "lat": 50.4350, "lon": 30.4450, "type": "microdistrict", "district_id": "solomiansk"},
    "видубичі": {"canonical": "Видубичі, Печерський район, Київ", "lat": 50.414747, "lon": 30.567991, "type": "microdistrict", "district_id": "pechersk"},
    "липки": {"canonical": "Липки, Печерський район, Київ", "lat": 50.4450, "lon": 30.5350, "type": "microdistrict", "district_id": "pechersk"},
    "звіринець": {"canonical": "Звіринець, Печерський район, Київ", "lat": 50.4220, "lon": 30.5550, "type": "microdistrict", "district_id": "pechersk"},
    "чорна гора": {"canonical": "Чорна Гора, Печерський район, Київ", "lat": 50.4120, "lon": 30.5420, "type": "microdistrict", "district_id": "pechersk"},
    "березняки": {"canonical": "Березняки, Дніпровський район, Київ", "lat": 50.42874, "lon": 30.604199, "type": "microdistrict", "district_id": "dniprovsk"},
    "русанівка": {"canonical": "Русанівка, Дніпровський район, Київ", "lat": 50.4380, "lon": 30.5980, "type": "microdistrict", "district_id": "dniprovsk"},
    "лівобережний": {"canonical": "Лівобережний масив, Дніпровський район, Київ", "lat": 50.4520, "lon": 30.5990, "type": "microdistrict", "district_id": "dniprovsk"},
    "лівобережка": {"canonical": "Лівобережний масив, Дніпровський район, Київ", "lat": 50.4520, "lon": 30.5990, "type": "microdistrict", "district_id": "dniprovsk"},
    "дврз": {"canonical": "ДВРЗ, Дніпровський район, Київ", "lat": 50.4490, "lon": 30.6720, "type": "microdistrict", "district_id": "dniprovsk"},
    "райдужний": {"canonical": "Райдужний масив, Дніпровський район, Київ", "lat": 50.4910, "lon": 30.5850, "type": "microdistrict", "district_id": "dniprovsk"},
    "воскресенка": {"canonical": "Воскресенка, Дніпровський район, Київ", "lat": 50.484215, "lon": 30.598646, "type": "microdistrict", "district_id": "dniprovsk"},
    "позняки": {"canonical": "Позняки, Дарницький район, Київ", "lat": 50.3985, "lon": 30.6342, "type": "microdistrict", "district_id": "darnytsia"},
    "осокорки": {"canonical": "Осокорки, Дарницький район, Київ", "lat": 50.3922, "lon": 30.6158, "type": "microdistrict", "district_id": "darnytsia"},
    "харківський": {"canonical": "Харківський масив, Дарницький район, Київ", "lat": 50.4080, "lon": 30.6620, "type": "microdistrict", "district_id": "darnytsia"},
    "бортничі": {"canonical": "Бортничі, Дарницький район, Київ", "lat": 50.3750, "lon": 30.6950, "type": "microdistrict", "district_id": "darnytsia"},
    "червоний хутір": {"canonical": "Червоний Хутір, Дарницький район, Київ", "lat": 50.4020, "lon": 30.6900, "type": "microdistrict", "district_id": "darnytsia"},
    "троєщина": {"canonical": "Троєщина, Деснянський район, Київ", "lat": 50.5186, "lon": 30.6015, "type": "microdistrict", "district_id": "desniansk"},
    "лісовий": {"canonical": "Лісовий масив, Деснянський район, Київ", "lat": 50.4780, "lon": 30.6350, "type": "microdistrict", "district_id": "desniansk"},
    "биківня": {"canonical": "Биківня, Деснянський район, Київ", "lat": 50.4680, "lon": 30.6720, "type": "microdistrict", "district_id": "desniansk"},
    "борщагівка": {"canonical": "Борщагівка, Святошинський район, Київ", "lat": 50.4285, "lon": 30.3802, "type": "microdistrict", "district_id": "sviatoshyn"},
    "академмістечко": {"canonical": "Академмістечко, Святошинський район, Київ", "lat": 50.4680, "lon": 30.3550, "type": "microdistrict", "district_id": "sviatoshyn"},
    "біличі": {"canonical": "Біличі, Святошинський район, Київ", "lat": 50.4620, "lon": 30.3380, "type": "microdistrict", "district_id": "sviatoshyn"},
    "новобіличі": {"canonical": "Новобіличі, Святошинський район, Київ", "lat": 50.4820, "lon": 30.3390, "type": "microdistrict", "district_id": "sviatoshyn"},
    "теремки": {"canonical": "Теремки, Голосіївський район, Київ", "lat": 50.3685, "lon": 30.4542, "type": "microdistrict", "district_id": "holosiiv"},
    "деміївка": {"canonical": "Деміївка, Голосіївський район, Київ", "lat": 50.4062, "lon": 30.5185, "type": "microdistrict", "district_id": "holosiiv"},
    "корчувате": {"canonical": "Корчувате, Голосіївський район, Київ", "lat": 50.3680, "lon": 30.5620, "type": "microdistrict", "district_id": "holosiiv"},
    "пирогово": {"canonical": "Пирогово, Голосіївський район, Київ", "lat": 50.3520, "lon": 30.5180, "type": "microdistrict", "district_id": "holosiiv"},
    "феофанія": {"canonical": "Феофанія, Голосіївський район, Київ", "lat": 50.3420, "lon": 30.4850, "type": "microdistrict", "district_id": "holosiiv"},
    "китаєво": {"canonical": "Китаєво, Голосіївський район, Київ", "lat": 50.3800, "lon": 30.5350, "type": "microdistrict", "district_id": "holosiiv"},
    "куренівка": {"canonical": "Куренівка, Подільський район, Київ", "lat": 50.4885, "lon": 30.4752, "type": "microdistrict", "district_id": "podil"},
    "мінський": {"canonical": "Мінський масив, Оболонський район, Київ", "lat": 50.5220, "lon": 30.4620, "type": "microdistrict", "district_id": "obolon"},
    "пуща-водиця": {"canonical": "Пуща-Водиця, Оболонський район, Київ", "lat": 50.5420, "lon": 30.3550, "type": "microdistrict", "district_id": "obolon"},

    # ── Major Kyiv Oblast Cities & Towns ──
    "бровар": {"canonical": "Бровари", "lat": 50.511117, "lon": 30.790048, "type": "settlement"},
    "бровари": {"canonical": "Бровари", "lat": 50.511117, "lon": 30.790048, "type": "settlement"},
    "броварський район": {"canonical": "Броварський район, Київська область", "lat": 50.47399, "lon": 31.536089, "type": "raion"},
    "велика димерка": {"canonical": "Велика Димерка, Броварський район", "lat": 50.612753, "lon": 30.874135, "type": "settlement"},
    "бориспіл": {"canonical": "Бориспіль", "lat": 50.35121, "lon": 30.95077, "type": "settlement"},
    "бориспіль": {"canonical": "Бориспіль", "lat": 50.35121, "lon": 30.95077, "type": "settlement"},
    "бориспільський район": {"canonical": "Бориспільський район, Київська область", "lat": 50.163103, "lon": 31.094936, "type": "raion"},
    "буч": {"canonical": "Буча", "lat": 50.550313, "lon": 30.210693, "type": "settlement"},
    "буча": {"canonical": "Буча", "lat": 50.550313, "lon": 30.210693, "type": "settlement"},
    "бучанський район": {"canonical": "Бучанський район, Київська область", "lat": 50.550313, "lon": 30.210693, "type": "raion"},
    "ірпін": {"canonical": "Ірпінь", "lat": 50.520678, "lon": 30.244872, "type": "settlement"},
    "ірпінь": {"canonical": "Ірпінь", "lat": 50.520678, "lon": 30.244872, "type": "settlement"},
    "гостомель": {"canonical": "Гостомель", "lat": 50.58826, "lon": 30.25909, "type": "settlement"},
    "ворзель": {"canonical": "Ворзель", "lat": 50.545729, "lon": 30.156289, "type": "settlement"},
    "коцюбинське": {"canonical": "Коцюбинське", "lat": 50.4905, "lon": 30.3342, "type": "settlement"},
    "вишгород": {"canonical": "Вишгород", "lat": 50.582433, "lon": 30.485121, "type": "settlement"},
    "вишгородський район": {"canonical": "Вишгородський район, Київська область", "lat": 51.036201, "lon": 29.991011, "type": "raion"},
    "ясногородка": {"canonical": "Ясногородка, Вишгородський район", "lat": 50.847662, "lon": 30.398479, "type": "settlement"},
    "страхолісся": {"canonical": "Страхолісся, Вишгородський район", "lat": 51.0925, "lon": 30.3921, "type": "settlement"},
    "димер": {"canonical": "Димер", "lat": 50.7852, "lon": 30.3125, "type": "settlement"},
    "васильк": {"canonical": "Васильків", "lat": 50.178137, "lon": 30.317504, "type": "settlement"},
    "васильків": {"canonical": "Васильків", "lat": 50.178137, "lon": 30.317504, "type": "settlement"},
    "васильківський район": {"canonical": "Васильків, Київська область", "lat": 50.178137, "lon": 30.317504, "type": "settlement"},
    "глеваха": {"canonical": "Глеваха", "lat": 50.2642, "lon": 30.3185, "type": "settlement"},
    "калинівка": {"canonical": "Калинівка, Фастівський район", "lat": 50.225725, "lon": 30.226178, "type": "settlement"},
    "чабани": {"canonical": "Чабани", "lat": 50.341434, "lon": 30.427101, "type": "settlement"},
    "хотів": {"canonical": "Хотів", "lat": 50.3342, "lon": 30.4682, "type": "settlement"},
    "боярк": {"canonical": "Боярка", "lat": 50.3185, "lon": 30.2982, "type": "settlement"},
    "боярка": {"canonical": "Боярка", "lat": 50.3185, "lon": 30.2982, "type": "settlement"},
    "вишнев": {"canonical": "Вишневе", "lat": 50.3882, "lon": 30.3658, "type": "settlement"},
    "вишневе": {"canonical": "Вишневе", "lat": 50.3882, "lon": 30.3658, "type": "settlement"},
    "обухів": {"canonical": "Обухів", "lat": 50.110163, "lon": 30.62697, "type": "settlement"},
    "обухівський район": {"canonical": "Обухівський район, Київська область", "lat": 50.110163, "lon": 30.62697, "type": "raion"},
    "українк": {"canonical": "Українка", "lat": 50.1458, "lon": 30.7482, "type": "settlement"},
    "українка": {"canonical": "Українка", "lat": 50.1458, "lon": 30.7482, "type": "settlement"},
    "трипілл": {"canonical": "Трипілля", "lat": 50.1252, "lon": 30.7785, "type": "settlement"},
    "трипілля": {"canonical": "Трипілля", "lat": 50.1252, "lon": 30.7785, "type": "settlement"},
    "біла церква": {"canonical": "Біла Церква", "lat": 49.79697, "lon": 30.115807, "type": "settlement"},
    "білоцерківськ": {"canonical": "Біла Церква", "lat": 49.79697, "lon": 30.115807, "type": "settlement"},
    "білоцерківський район": {"canonical": "Білоцерківський район, Київська область", "lat": 49.79697, "lon": 30.115807, "type": "raion"},
    "узин": {"canonical": "Узин", "lat": 49.8252, "lon": 30.4358, "type": "settlement"},
    "фастів": {"canonical": "Фастів", "lat": 50.0785, "lon": 29.9158, "type": "settlement"},
    "фастівський район": {"canonical": "Фастівський район, Київська область", "lat": 50.0785, "lon": 29.9158, "type": "raion"},
    "переяслав": {"canonical": "Переяслав", "lat": 50.0658, "lon": 31.4485, "type": "settlement"},
    "яготин": {"canonical": "Яготин", "lat": 50.2585, "lon": 31.7785, "type": "settlement"},
    "згурівка": {"canonical": "Згурівка", "lat": 50.4958, "lon": 31.7852, "type": "settlement"},
    "березань": {"canonical": "Березань", "lat": 50.313271, "lon": 31.468916, "type": "settlement"},
    "славутич": {"canonical": "Славутич", "lat": 51.52014, "lon": 30.75623, "type": "settlement"},
    "макарів": {"canonical": "Макарів", "lat": 50.4582, "lon": 29.8152, "type": "settlement"},
    "бородянка": {"canonical": "Бородянка", "lat": 50.6458, "lon": 29.9258, "type": "settlement"},
    "іванків": {"canonical": "Іванків", "lat": 50.9358, "lon": 29.8952, "type": "settlement"},
    "чорнобиль": {"canonical": "Чорнобиль", "lat": 51.2725, "lon": 30.2245, "type": "settlement"},
}

def resolve_canonical_toponym(raw_location: str) -> Tuple[str, Optional[float], Optional[float], bool]:
    """
    Normalizes raw location string into a canonical entity with accurate coordinates.
    Returns: (canonical_name, latitude, longitude, is_fallback_geo)

    is_fallback_geo is True when the coordinates are a generic last-resort
    guess (city/region centroid) rather than a match against an actual named
    place in the text — callers should use this to distinguish "this really
    is downtown/Maidan" from "we don't know where this is, defaulting to the
    city center", since both currently produce the same coordinates.
    """
    if not raw_location or not raw_location.strip():
        return "Київ та область", 50.450034, 30.524136, True

    cleaned = raw_location.strip().lower()
    cleaned = re.sub(r'["\']', '', cleaned)

    # 1. Exact lookup
    if cleaned in CANONICAL_TOPONYMS and CANONICAL_TOPONYMS[cleaned]:
        entry = CANONICAL_TOPONYMS[cleaned]
        is_fallback = (entry.get("type") == "region")
        return entry["canonical"], entry["lat"], entry["lon"], is_fallback

    # 2. Fuzzy/Substring scan (matching longest canonical key first)
    sorted_keys = sorted(CANONICAL_TOPONYMS.keys(), key=lambda k: len(k), reverse=True)
    for key in sorted_keys:
        val = CANONICAL_TOPONYMS[key]
        if val is None:
            continue
        # If key is inside cleaned raw location
        pattern = r'\b' + re.escape(key) + r'\b'
        if re.search(pattern, cleaned) or key in cleaned:
            is_fallback = (val.get("type") == "region")
            return val["canonical"], val["lat"], val["lon"], is_fallback

    # 3. Fallback: If it contains 'київ' or 'область', but nothing more specific matched.
    if "київ" in cleaned:
        return "Київ та область", 50.450034, 30.524136, True

    return raw_location.strip(), None, None, True
