"""
Tactical Geospatial Disambiguation & Regional Context Resolver.
Prevents false-positive geocoding of homonymous toponyms across Ukraine
(e.g., Dniprovsky district, Shevchenkivsky district, Vasylkiv vs Vasylkivka, Kalynivka).
"""
import re
from typing import Dict, Optional, Tuple, Any

# Regional keywords and stems indicating non-Kyiv administrative entities
EXTERNAL_OBLAST_STEMS: Dict[str, list] = {
    "kherson": [
        "херсон", "херсонськ", "херсонщин", "берислав", "білозерк", "чорнобаївк",
        "тягинк", "антонівк", "каховк", "скадовськ", "олешк", "дніпровського району херсона",
        "дніпровський район херсона", "корабельний район херсона"
    ],
    "kharkiv": [
        "харків", "харківськ", "харківщин", "куп'янськ", "купянськ", "вовчанськ",
        "ізюм", "чугуїв", "балаклі", "лозов", "богодухів", "дергач", "шевченківський район харкова"
    ],
    "odesa": [
        "одес", "одещин", "чорноморськ", "іллічівськ", "білгород-дністровськ",
        "южне", "подільськ одеської", "подільського району одеської", "ізмаїл", "рені"
    ],
    "zaporizhzhia": [
        "запоріз", "запоріжж", "бердянськ", "мелітопол", "оріхів", "гуляйпол",
        "василівк", "полог", "дніпровський район запоріжжя"
    ],
    "dnipropetrovsk": [
        "дніпропетровськ", "дніпропетровщин", "кривий ріг", "криворіж", "нікопол",
        "марганець", "павлоград", "кам'янськ", "синельников", "васильківк", "васильківка",
        "дніпровський район дніпропетровської"
    ],
    "sumy": [
        "сумськ", "суми", "конотоп", "шостк", "охтирк", "ромен", "глухів", "білопілл", "краснопілл"
    ],
    "mykolaiv": [
        "миколаїв", "миколаївськ", "миколаївщин", "очаків", "вознесенськ", "первомайськ", "баштанськ"
    ],
    "donetsk": [
        "донецьк", "донеччин", "донбас", "бахмут", "покровськ", "костянтинівк",
        "краматорськ", "слов'янськ", "авдіївк", "торецьк", "часов яр", "селидов", "курахов"
    ],
    "luhansk": [
        "луганськ", "луганщин", "сєвєродонецьк", "лисичанськ", "рубіжне", "кремінн", "сватов"
    ],
    "poltava": [
        "полтав", "полтавщин", "кременчук", "миргород", "лубни"
    ],
    "vinnytsia": [
        "вінниц", "вінниччин", "жмеринк", "хмільник", "могилів-подільськ"
    ],
    "chernihiv": [
        "чернігів", "чернігівськ", "чернігівщин", "ніжин", "прилук", "новгород-сіверськ", "семенівк"
    ],
    "zhytomyr": [
        "житомир", "житомирськ", "житомирщин", "коростень", "бердичів", "звягель"
    ]
}

KYIV_EXPLICIT_STEMS = [
    "київ", "києв", "київськ", "київщин", "столиц", "кмва", "кличко", "омелянович",
    "бровар", "бориспіл", "ірпін", "буч", "гостомель", "ворзель", "вишгород",
    "фастів", "біла церкв", "обухів", "українк", "васильків київ", "васильківськ",
    "лівий берег києва", "правий берег києва"
]

# Canonical coordinates for common non-Kyiv homonyms to prevent misplacing on Kyiv map
HOMONYM_RESOLUTIONS = {
    # Dniprovsky district homonyms
    ("дніпровський район", "kherson"): {
        "canonical": "Дніпровський район, Херсон",
        "oblast": "kherson",
        "lat": 46.6611,
        "lon": 32.6582,
        "is_kyiv": False
    },
    ("дніпровський район", "zaporizhzhia"): {
        "canonical": "Дніпровський район, Запоріжжя",
        "oblast": "zaporizhzhia",
        "lat": 47.8833,
        "lon": 35.0833,
        "is_kyiv": False
    },
    ("дніпровський район", "dnipropetrovsk"): {
        "canonical": "Дніпровський район, Дніпропетровська область",
        "oblast": "dnipropetrovsk",
        "lat": 48.5152,
        "lon": 35.0234,
        "is_kyiv": False
    },
    ("дніпровський район", "kyiv"): {
        "canonical": "Дніпровський район, Київ",
        "oblast": "kyiv_city",
        "lat": 50.4528,
        "lon": 30.5982,
        "is_kyiv": True
    },

    # Shevchenkivsky district homonyms
    ("шевченківський район", "kharkiv"): {
        "canonical": "Шевченківський район, Харків",
        "oblast": "kharkiv",
        "lat": 50.0242,
        "lon": 36.2185,
        "is_kyiv": False
    },
    ("шевченківський район", "zaporizhzhia"): {
        "canonical": "Шевченківський район, Запоріжжя",
        "oblast": "zaporizhzhia",
        "lat": 47.8385,
        "lon": 35.2152,
        "is_kyiv": False
    },
    ("шевченківський район", "kyiv"): {
        "canonical": "Шевченківський район, Київ",
        "oblast": "kyiv_city",
        "lat": 50.46288,
        "lon": 30.451795,
        "is_kyiv": True
    },

    # Podilsky district homonyms
    ("подільський район", "odesa"): {
        "canonical": "Подільський район, Одеська область",
        "oblast": "odesa",
        "lat": 47.7412,
        "lon": 29.5350,
        "is_kyiv": False
    },
    ("подільський район", "kyiv"): {
        "canonical": "Подільський район, Київ",
        "oblast": "kyiv_city",
        "lat": 50.469128,
        "lon": 30.516624,
        "is_kyiv": True
    },

    # Vasylkiv vs Vasylkivka
    ("васильків", "dnipropetrovsk"): {
        "canonical": "Васильківка, Дніпропетровська область",
        "oblast": "dnipropetrovsk",
        "lat": 48.2082,
        "lon": 36.0275,
        "is_kyiv": False
    },
    ("васильків", "kyiv"): {
        "canonical": "Васильків, Київська область",
        "oblast": "kyiv_region",
        "lat": 50.178137,
        "lon": 30.317504,
        "is_kyiv": True
    },

    # Kalynivka
    ("калинівка", "vinnytsia"): {
        "canonical": "Калинівка, Вінницька область",
        "oblast": "vinnytsia",
        "lat": 49.4522,
        "lon": 28.5238,
        "is_kyiv": False
    },
    ("калинівка", "kyiv"): {
        "canonical": "Калинівка, Фастівський район, Київська область",
        "oblast": "kyiv_region",
        "lat": 50.225725,
        "lon": 30.226178,
        "is_kyiv": True
    },
}


def detect_external_oblast(text: str) -> Optional[str]:
    """
    Detects if the text has explicit geographic references to non-Kyiv oblasts.
    Returns oblast key (e.g., 'kherson', 'kharkiv', 'odesa') or None.
    """
    if not text:
        return None
    t_lower = text.lower()

    # Direct phrase matches have highest priority
    if "херсон" in t_lower:
        return "kherson"
    if "харків" in t_lower or "харков" in t_lower:
        return "kharkiv"
    if "одес" in t_lower:
        return "odesa"
    if "запоріж" in t_lower or "запоріз" in t_lower:
        return "zaporizhzhia"
    if "дніпропетровськ" in t_lower or "кривий ріг" in t_lower or "нікопол" in t_lower or "павлоград" in t_lower or "васильківк" in t_lower:
        return "dnipropetrovsk"
    if "сумськ" in t_lower or "суми" in t_lower:
        return "sumy"
    if "миколаїв" in t_lower or "миколаєв" in t_lower:
        return "mykolaiv"
    if "чернігів" in t_lower or "чернігов" in t_lower:
        return "chernihiv"
    if "донеччин" in t_lower or "донбас" in t_lower or "покровськ" in t_lower or "краматорськ" in t_lower:
        return "donetsk"

    # Scan external stems
    for ob, stems in EXTERNAL_OBLAST_STEMS.items():
        for stem in stems:
            if re.search(r'\b' + re.escape(stem), t_lower):
                return ob

    return None


def is_explicitly_kyiv_context(text: str) -> bool:
    """Checks if the text contains explicit Kyiv-specific keywords or institutions."""
    if not text:
        return False
    t_lower = text.lower()
    for stem in KYIV_EXPLICIT_STEMS:
        if stem in t_lower:
            return True
    return False


def disambiguate_toponym(
    candidate_name: str,
    full_text: str = "",
    channel_oblast: Optional[str] = None
) -> Dict[str, Any]:
    """
    Disambiguates a toponym candidate using message context and channel origins.
    Returns:
    {
        "canonical": str,
        "oblast": str,
        "lat": Optional[float],
        "lon": Optional[float],
        "is_kyiv": bool,
        "is_homonym": bool
    }
    """
    norm_candidate = (candidate_name or "").strip().lower()
    norm_candidate = re.sub(r'["\']', '', norm_candidate)

    # 1. Check if candidate is Vasylkivka directly
    if "васильківк" in norm_candidate or "васильківка" in norm_candidate:
        return {
            "canonical": "Васильківка, Дніпропетровська область",
            "oblast": "dnipropetrovsk",
            "lat": 48.2082,
            "lon": 36.0275,
            "is_kyiv": False,
            "is_homonym": True
        }

    # 2. Check general external oblast context in the message
    detected_oblast = detect_external_oblast(full_text)
    has_kyiv_context = is_explicitly_kyiv_context(full_text)

    # Determine dominant oblast
    dominant_oblast = "kyiv"
    if detected_oblast and not has_kyiv_context:
        dominant_oblast = detected_oblast
    elif channel_oblast and channel_oblast not in ["all", "national"]:
        dominant_oblast = channel_oblast

    # 3. Match against homonym matrix
    for (homonym_key, ob_key), res in HOMONYM_RESOLUTIONS.items():
        if homonym_key in norm_candidate or norm_candidate in homonym_key:
            if dominant_oblast == ob_key:
                return {
                    "canonical": res["canonical"],
                    "oblast": res["oblast"],
                    "lat": res["lat"],
                    "lon": res["lon"],
                    "is_kyiv": res["is_kyiv"],
                    "is_homonym": True
                }

    # If an external oblast was detected and NO Kyiv context exists, flag as non-Kyiv!
    if detected_oblast and not has_kyiv_context:
        return {
            "canonical": f"{candidate_name} ({detected_oblast.capitalize()})",
            "oblast": detected_oblast,
            "lat": None,
            "lon": None,
            "is_kyiv": False,
            "is_homonym": True
        }

    # Default fallback for regular Kyiv-region toponym
    return {
        "canonical": candidate_name,
        "oblast": "kyiv_city" if "київ" in norm_candidate else "kyiv_region",
        "lat": None,
        "lon": None,
        "is_kyiv": True,
        "is_homonym": False
    }
