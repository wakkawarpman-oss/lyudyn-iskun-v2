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
    ],
    "rivne": [
        "рівне", "рівненськ", "рівненщин", "квасилів", "дубно", "ваcell", "сарни", "шакирзян", "острог", "костопіль"
    ],
    "volyn": [
        "луцьк", "волин", "волинськ", "ковель", "нововолинськ", "володимир"
    ],
    "lviv": [
        "львів", "львівськ", "львівщин", "дрогобич", "стрий", "червоноград", "самбір", "трускавець", "садовий"
    ],
    "ternopil": [
        "тернопіль", "тернопільськ", "тернопільщин", "чортків", "кременець", "бережани"
    ],
    "ivano-frankivsk": [
        "івано-франківськ", "прикарпатт", "калуш", "коломи", "надвірн", "яремч"
    ],
    "zakarpattia": [
        "ужгород", "закарпатт", "мукачев", "берегов", "хуст", "виноградів"
    ],
    "chernivtsi": [
        "чернівц", "чернівецьк", "буковин", "новоселиц", "сторожинець"
    ],
    "khmelnytskyi": [
        "хмельницьк", "хмельниччин", "кам'янець-подільськ", "шепетівк", "славут", "нетішин"
    ],
    "cherkasy": [
        "черкас", "черкащин", "умань", "сміла", "золотонош", "канів"
    ],
    "kirovohrad": [
        "кропивницьк", "кіровоград", "олександрі", "знам'янк", "світловодськ"
    ],
    "crimea": [
        "крим", "севастопол", "сімферопол", "керч", "євпаторі", "ялта", "феодосі", "джанкой"
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


CHANNEL_OBLAST_MAP = {
    "suspilnerivne": "rivne",
    "suspilnelviv": "lviv",
    "suspilnevolyn": "volyn",
    "suspilneternopil": "ternopil",
    "suspilnecherkasy": "cherkasy",
    "suspilnechernihiv": "chernihiv",
    "suspilnesumy": "sumy",
    "suspilnekharkiv": "kharkiv",
    "suspilnednipro": "dnipropetrovsk",
    "suspilnezaporizhzhya": "zaporizhzhia",
    "suspilnekherson": "kherson",
    "suspilnemykolaiv": "mykolaiv",
    "suspilneodesa": "odesa",
    "suspilnezhytomyr": "zhytomyr",
    "suspilnepoltava": "poltava",
    "suspilnevinnytsya": "vinnytsia",
    "suspilnekhmelnytskyi": "khmelnytskyi",
    "suspilnekropyvnytskyi": "kirovohrad",
    "suspilneuzhhorod": "zakarpattia",
    "suspilnechernivtsi": "chernivtsi",
    "dnepr_operativ": "dnipropetrovsk",
    "ny_i_dnipro": "dnipropetrovsk",
    "dp_trevoga": "dnipropetrovsk",
    "sirena_dp": "dnipropetrovsk",
    "adm_dp": "dnipropetrovsk",
    "dnipropetrovskaoda": "dnipropetrovsk",
    "ivan_fedorov_zp": "zaporizhzhia",
    "zoda_gov_ua": "zaporizhzhia",
    "sirenazaporizhzhia": "zaporizhzhia",
    "tryvoga_zp": "zaporizhzhia",
    "info_zp": "zaporizhzhia",
    "synegubov": "kharkiv",
    "ihor_terekhov": "kharkiv",
    "kharkiv_life": "kharkiv",
    "kharkov_radar": "kharkiv",
    "odessa_typical": "odesa",
    "our_odessa": "odesa",
    "dnepr_live": "dnipropetrovsk",
    "hyevuy_dnepr": "dnipropetrovsk",
    "zaporozhye_city": "zaporizhzhia",
    "zp_radar": "zaporizhzhia",
    "novostiniko": "mykolaiv",
    "nikolaev_live": "mykolaiv",
    "senkevichonline": "mykolaiv",
    "mykolaivskaoda": "mykolaiv",
    "sumy_radar": "sumy",
    "sumy_glavnoe": "sumy",
    "poltava_alerts": "poltava",
    "pvp_poltava": "poltava",
    "lviv_typical": "lviv",
    "lviv_radar": "lviv",
    "delta_odesa": "odesa",
    "khersonskaoda": "kherson",
    "vinnytsiaoda": "vinnytsia",
    "poltavskaoda": "poltava",
    "kirovohradskaoda": "kirovohrad",
    "luhanskavtsa": "luhansk",
    "krymrealii": "crimea"
}

_REGISTRY_OBLAST_CACHE = None

def _load_registry_channel_map():
    global _REGISTRY_OBLAST_CACHE
    if _REGISTRY_OBLAST_CACHE is not None:
        return _REGISTRY_OBLAST_CACHE
    mapping = {}
    import json, os
    reg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "channels", "channel_registry.json")
    if os.path.exists(reg_path):
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            for ob, items in d.items():
                for item in items:
                    u = item.get("username", "").lstrip("@").lower().strip()
                    if u:
                        mapping[u] = ob
        except Exception:
            pass
    _REGISTRY_OBLAST_CACHE = mapping
    return mapping

def detect_channel_oblast(channel_handle: str) -> Optional[str]:
    """Resolves channel's native oblast from handle name or registry."""
    if not channel_handle:
        return None
    ch = str(channel_handle).lstrip("@").strip().lower()
    if ch in CHANNEL_OBLAST_MAP:
        return CHANNEL_OBLAST_MAP[ch]
    reg_map = _load_registry_channel_map()
    if ch in reg_map:
        return reg_map[ch]
    for key, ob in CHANNEL_OBLAST_MAP.items():
        if key in ch:
            return ob
    for key, ob in reg_map.items():
        if key in ch:
            return ob
    # Fallback to checking oblast stems in channel handle
    for ob, stems in EXTERNAL_OBLAST_STEMS.items():
        if ob in ch:
            return ob
    return None


CIVILIAN_NOISE_PHRASES = [
    # Road, municipal, utilities
    "дорожніх робіт", "дорожні роботи", "ремонт доріг", "ремонтуватимуть",
    "прибирання листя", "прибирання доріг", "зливові каналізації", "зливова каналізація",
    "комунальні служби", "водоканал", "водопостачання", "зупинився рух тролейбусів",
    "зупинився рух трамваїв", "трамвайної колії", "ремонт трамвайн", "ускладнення руху",
    "колесовідбійник", "струменевий ремонт", "графік відключень", "планові відключення",
    "комунальники", "дрібного сміття", "прочищатимуть зливові", "механізоване прибирання",
    "міні-дтп", "дтп", "зіткнулися", "мотоцикліст", "легковик", "наїзд на пішохода",
    # Judicial, corruption, call-centers, administrative scandals
    "кол-центр", "колцентр", "генпрокурор", "офіс генпрокурора", "огп", "набу", "сап",
    "хабар", "суддя", "ухвала суду", "розкрадання", "депутат", "політик", "вибори",
    # Police operations without combat kinetic actions
    "принімал", "затримали шахра", "поліція викрила", "рейд тцк", "бійка", "крадіжк",
    # Weather forecasts and civil lifestyle
    "прогноз погоди", "синоптик", "пориви вітру", "ожеледиця", "температура повітря",
    "штормове попередження", "похолодання", "заморозки", "курс долар", "курс валют",
    "гороскоп", "футбол", "чемпіонат", "концерт"
]

RETROSPECTIVE_DIGEST_PHRASES = [
    "найважливіше за тиждень", "підсумки тижня", "головне за тиждень", "підсумки доби",
    "зведення за тиждень", "цього тижня у столиці", "цього тижня в області",
    "тижневий дайджест", "дайджест новин", "огляд тижня", "найважливіше за добу",
    "підсумки дня", "найголовніше за добу", "головні події тижня", "зведення за добу"
]

MILITARY_THREAT_KEYWORDS = [
    "вибух", "приліт", "влуч", "збит", "збили", "ппо", "пуск", "баліст", "крилат", "ракет",
    "шахед", "бпла", "дрон", "каб", "умпк", "авіа", "артобстріл", "повітрян", "тривог", "відбій",
    "детонац", "уламк", "обстріл", "артилері", "постраждал", "руйнуван", "мопед", "герань",
    "ланцет", "зала", "zala", "суперкам", "supercam", "орлан", "реактив", "калібр", "іскандер",
    "кинджал", "х-101", "х-59", "х-69", "х-22", "стратегіч", "ту-95", "ту-22", "міг-31",
    "вектор ціл", "рух ціл", "рух бпла", "курс на", "летить на", "помічено ціль", "дорозвідк",
    "швидкісн", "ціль на", "цілі на", "снаряд", "міномет"
]

def is_civilian_non_threat_noise(text: str) -> bool:
    """
    Identifies civilian municipal maintenance, corruption, domestic crime, traffic,
    and domestic utility news that have no tactical or military air defense significance.
    """
    if not text:
        return False
    t_lower = text.lower()
    has_noise = any(p in t_lower for p in CIVILIAN_NOISE_PHRASES) or any(p in t_lower for p in RETROSPECTIVE_DIGEST_PHRASES)
    if not has_noise:
        return False
    # If noise word is present, only permit if strong unambiguous kinetic attack terms appear
    # Retrospective summaries are never permitted even with kinetic terms
    if any(p in t_lower for p in RETROSPECTIVE_DIGEST_PHRASES):
        return True
    strong_threat_terms = ["збит", "збили", "приліт", "влуч", "вибух", "шахед", "ракет", "каб", "снаряд", "падіння уламк"]
    has_strong_threat = any(k in t_lower for k in strong_threat_terms)
    return has_noise and not has_strong_threat


def is_tactical_threat_candidate(text: str) -> bool:
    """
    Strict C4ISR Gating: Evaluates if a raw message has legitimate tactical or military
    air defense significance. Fast-rejects general news, corruption, court hearings,
    call centers, domestic crime, civilian traffic, and retrospective digests.
    """
    if not text:
        return False
    t_lower = text.lower()

    # Fast reject retrospective weekly/daily digests which summarize past events
    if any(p in t_lower for p in RETROSPECTIVE_DIGEST_PHRASES):
        return False

    if is_civilian_non_threat_noise(t_lower):
        return False

    has_threat = any(k in t_lower for k in MILITARY_THREAT_KEYWORDS)
    return has_threat


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


def validate_tactical_coordinates(
    lat: Optional[float],
    lon: Optional[float],
    oblast: Optional[str] = None,
    is_kyiv_metro: bool = False
) -> Tuple[bool, Optional[str]]:
    """Validates coordinates against tactical geospatial bounds and inverted axis errors.
    
    Guards against:
    - Missing coordinates or invalid numeric formats
    - Inverted coordinates: (Lon, Lat) swapped, e.g. Lon > 40.5 or Lat < 44.0
    - Kyiv Metropolitan bounds: [50.2000, 50.6000] N, [30.2000, 30.8500] E (when is_kyiv_metro=True)
    - Kyiv Oblast bounds: [49.1500, 51.5500] N, [29.2000, 32.2000] E (when oblast in ['kyiv_oblast', 'kyiv_region'])
    - National Ukrainian sovereign bounds: [44.0000, 52.5000] N, [22.0000, 40.5000] E (default across all regions)
    
    Returns (is_valid, error_reason).
    """
    if lat is None or lon is None:
        return False, "missing_coordinates"

    try:
        f_lat = float(lat)
        f_lon = float(lon)
    except (ValueError, TypeError):
        return False, "invalid_numeric_format"

    # Inverted coordinate guard (Lon/Lat swapped or outside Ukrainian sovereign territory)
    if f_lon > 40.5 or f_lat < 44.0 or f_lat > 52.5 or f_lon < 22.0:
        return False, f"inverted_or_out_of_ukraine_bounds (lat={f_lat}, lon={f_lon})"

    # Kyiv Metropolitan Bounds check
    if is_kyiv_metro:
        if not (50.2000 <= f_lat <= 50.6000 and 30.2000 <= f_lon <= 30.8500):
            return False, f"outside_kyiv_metro_bounds (lat={f_lat}, lon={f_lon})"
        return True, None

    # Kyiv Oblast Bounds check (when explicitly requested)
    if oblast in ["kyiv_oblast", "kyiv_region"]:
        if not (49.1500 <= f_lat <= 51.5500 and 29.2000 <= f_lon <= 32.2000):
            return False, f"outside_kyiv_oblast_bounds (lat={f_lat}, lon={f_lon})"
        return True, None

    return True, None
