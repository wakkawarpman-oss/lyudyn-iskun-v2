import os
import json
import logging
import base64
import requests
import datetime
from zoneinfo import ZoneInfo
from worker.schemas import ParsedEventSchema

KYIV_TZ = ZoneInfo("Europe/Kyiv")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

logger = logging.getLogger(__name__)

def get_current_time_str() -> str:
    now_kyiv = datetime.datetime.now(datetime.timezone.utc).astimezone(KYIV_TZ)
    return now_kyiv.strftime("%Y-%m-%d %H:%M:%S (Kyiv)")

def build_system_prompt() -> str:
    current_time = get_current_time_str()
    return f"""Ти професійний OSINT-аналітик військової розвідки.
ТВОЯ ЗОНА ВІДПОВІДАЛЬНОСТІ — ВИКЛЮЧНО МІСТО КИЇВ ТА КИЇВСЬКА ОБЛАСТЬ!
ПОТОЧНИЙ СИСТЕМНИЙ ЧАС: {current_time}. Будь-які події за цю дату є актуальними.
Якщо повідомлення стосується інших міст чи областей (Херсон, Харків, Одеса, Запоріжжя, Дніпро, Суми, Донеччина, Миколаїв тощо) — поверни "is_kyiv_region": false.

УВАГА НА ТОПОНІМИ-ОМОНІМИ:
- "Дніпровський район Херсона" або "Дніпровський район Запоріжжя" — це ХЕРСОН або ЗАПОРІЖЖЯ, це НЕ КИЇВ! ("is_kyiv_region": false).
- "Васильківка" або Синельниківський район — це ДНІПРОПЕТРОВСЬКА область, а не Васильків! ("is_kyiv_region": false).
- "Шевченківський район Харкова" — це ХАРКІВ! ("is_kyiv_region": false).
- "Подільський район Одеської області" — це ОДЕЩИНА! ("is_kyiv_region": false).
- Якщо київський канал робить репост про обстріл Херсона чи Харкова — це НЕ Київ! ("is_kyiv_region": false).

ЯКЩО ТОБІ НАДАНО ФОТО — ПРОВЕДИ ВІЗУАЛЬНИЙ АНАЛІЗ ФОТО:
ЗАБОРОНЕНО вгадувати точний район за типовою архітектурою (наприклад, панельні будинки чи хрущовки є по всьому Києву). 
Якщо на фото немає унікальних орієнтирів (чіткі вивіски, відомі пам'ятники, унікальні перехрестя, читабельний текст вулиці), локація ПОВИННА бути визначена як загальна (наприклад, 'Київ' або 'Київська область'). 
Краще вказати загальний регіон, ніж згенерувати хибну точну координату, яка призведе до паніки.
Використай ці підказки, щоб безпечно і відповідально витягти `location`.

Поверни ТІЛЬКИ валідний JSON у такій структурі:
{{
  "is_kyiv_region": true/false,
  "is_confirmed_incident": true/false,
  "is_radar_track": true/false,
  "event_type": "air_defense|direct_strike|explosion|fire|destruction|casualties|armed_conflict|radar_track|general_alert",
  "location": "точна назва району/вулиці/міста на Київщині",
  "osm_query": "вибери ЛИШЕ ОДНУ найбільш конкретну локацію для OpenStreetMap (заборонено використовувати 'та' чи коми для перелічення кількох місць)",
  "casualties": true/false,
  "damage_level": "none|low|medium|high|critical",
  "short_summary": "стислий факт без води (1 речення)"
}}
"""

def clean_and_validate_json_response(text: str) -> dict:
    """Extracts, cleans, and strictly validates LLM response using Pydantic."""
    import re
    cleaned = text.strip()
    if cleaned.startswith('```json'):
        cleaned = cleaned[7:]
    elif cleaned.startswith('```'):
        cleaned = cleaned[3:]
    if cleaned.endswith('```'):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    cleaned = cleaned.replace(": True", ": true").replace(": False", ": false")
    cleaned = cleaned.replace(":True", ": true").replace(":False", ": false")

    raw_dict = None
    try:
        raw_dict = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            json_str = match.group(0).replace(": True", ": true").replace(": False", ": false")
            try:
                raw_dict = json.loads(json_str)
            except Exception as e:
                logger.error(f"Failed regex JSON decode: {e}")

    if not raw_dict or not isinstance(raw_dict, dict):
        logger.error(f"Invalid JSON structure received from LLM: {text[:200]}")
        return {}

    # Strict Pydantic Validation Guard
    try:
        validated = ParsedEventSchema(**raw_dict)
        return validated.model_dump()
    except Exception as ve:
        logger.warning(f"Pydantic validation warning ({ve}), attempting safe coercion...")
        # Safe fallback coercion
        return {
            "is_kyiv_region": bool(raw_dict.get("is_kyiv_region", False)),
            "is_confirmed_incident": bool(raw_dict.get("is_confirmed_incident", False)),
            "is_radar_track": bool(raw_dict.get("is_radar_track", False)),
            "event_type": str(raw_dict.get("event_type", "general_alert")).lower(),
            "location": str(raw_dict.get("location", "Київ та область")),
            "osm_query": str(raw_dict.get("osm_query", "Київ")),
            "casualties": bool(raw_dict.get("casualties", False)),
            "damage_level": str(raw_dict.get("damage_level", "none")).lower(),
            "short_summary": str(raw_dict.get("short_summary", "Оперативна інформація"))[:150]
        }

def rule_based_fallback_parser(raw_text: str) -> dict:
    if not raw_text:
        return {"is_kyiv_region": False}
        
    text = str(raw_text)
    t_lower = text.lower()
    
    # Maps map a matched stem to its proper display name — kept separate from the
    # match list because several toponyms are matched on truncated stems
    # (e.g. 'дарниц' matches "Дарниця"/"Дарницький"), and capitalizing the raw
    # stem produced a cut-off name like "Дарниц" instead of "Дарниця".
    regional_city_names = {
        'бровар': 'Бровари', 'вишгород': 'Вишгород', 'бориспіл': 'Бориспіль',
        'ірпін': 'Ірпінь', 'ірпен': 'Ірпінь', 'буч': 'Буча', 'фастів': 'Фастів',
        'фастов': 'Фастів', 'біла церкв': 'Біла Церква', 'білій церкв': 'Біла Церква',
        'білої церкв': 'Біла Церква', 'білоцерків': 'Біла Церква',
        'обухів': 'Обухів', 'обухов': 'Обухів', 'гостомель': 'Гостомель',
        'ворзель': 'Ворзель', 'боярк': 'Боярка', 'глевах': 'Глеваха',
        'васильк': 'Васильків', 'макарів': 'Макарів', 'трипілл': 'Трипілля',
        'українк': 'Українка', 'славутич': 'Славутич', 'переяслав': 'Переяслав',
        'яготин': 'Яготин', 'коцюбинськ': 'Коцюбинське', 'баришівк': 'Баришівка',
        'бородянк': 'Бородянка', 'кагарлик': 'Кагарлик', 'миронівк': 'Миронівка',
        'таращ': 'Тараща', 'чабани': 'Чабани', 'софіївськ': 'Софіївська Борщагівка',
        'петропавлівськ': 'Петропавлівська Борщагівка', 'вишнев': 'Вишневе',
    }
    kyiv_district_names = {
        'оболон': 'Оболонь', 'поділ': 'Поділ', 'печерс': 'Печерськ',
        'солом': "Солом'янка", 'дарниц': 'Дарниця', 'шевченківськ': 'Шевченківський район',
        'голосіївськ': 'Голосіївський район', 'святошин': 'Святошин',
        'деснян': 'Деснянський район', 'дніпровськ': 'Дніпровський район',
        'троєщин': 'Троєщина', 'борщагівк': 'Борщагівка', 'позняк': 'Позняки',
        'осокорк': 'Осокорки', 'виноградар': 'Виноградар',
    }
    regional_cities = list(regional_city_names.keys())
    kyiv_districts = list(kyiv_district_names.keys())
    kyiv_keywords = ['київ', 'києв', 'київськ', 'столиц', 'kyiv'] + regional_cities + kyiv_districts
    
    non_kyiv_cities = [
        'кропивницьк', 'одес', 'харків', 'дніпр', 'запоріжж', 'полтав', 'кривий ріг', 'криворіж', 
        'сумськ', 'суми', 'черкас', 'вінниц', 'житомир', 'хмельницьк', 'львів', 'миколаїв', 
        'херсон', 'севастопол', 'донецьк', 'луганськ', 'бахмут', 'куп\'янськ', 'нікопол', 'павлоград', 'чернігів'
    ]
    
    from worker.geo_disambiguation import detect_external_oblast, is_explicitly_kyiv_context, disambiguate_toponym

    ext_ob = detect_external_oblast(t_lower)
    has_explicit_kyiv = is_explicitly_kyiv_context(t_lower)

    # If an external oblast is detected and no explicit Kyiv context exists, this is NOT Kyiv!
    if ext_ob and not has_explicit_kyiv:
        is_kyiv = False
    else:
        is_kyiv = any(k in t_lower for k in kyiv_keywords)
    
    event_type = "general_alert"
    if any(w in t_lower for w in ['збито', 'подавлено', 'робота ппо', 'збиття', 'відбито атаку', 'збили']):
        event_type = "air_defense"
    elif 'вибух' in t_lower:
        event_type = "explosion"
    elif 'приліт' in t_lower or 'влучання' in t_lower:
        event_type = "direct_strike"
    elif any(w in t_lower for w in ['шахед', 'ракет', 'ціль', 'рух', 'бпла', 'дрон', 'мопед', '🛵', 'курс', 'вектор']):
        event_type = "radar_track"
    elif 'пожеж' in t_lower or 'загорян' in t_lower:
        event_type = "fire"
    elif any(w in t_lower for w in ['тривог', 'відбій', 'увага']):
        event_type = "general_alert"
    
    loc_name = "Київ та область"
    osm_query = "Київ"
    
    for k in regional_cities:
        if k in t_lower:
            loc_name = regional_city_names[k]
            osm_query = f"{loc_name}, Київська область, Україна"
            break

    if loc_name == "Київ та область":
        for k in kyiv_districts:
            if k in t_lower:
                loc_name = kyiv_district_names[k]
                osm_query = f"{loc_name}, Київ"
                break

    # Contextual Disambiguation Guard
    dis = disambiguate_toponym(loc_name, full_text=raw_text)
    if dis.get("is_homonym"):
        loc_name = dis["canonical"]
        if not dis.get("is_kyiv"):
            is_kyiv = False
            osm_query = loc_name
                
    return {
        "is_kyiv_region": is_kyiv,
        "is_confirmed_incident": event_type in ["explosion", "direct_strike", "fire"],
        "is_radar_track": event_type == "radar_track",
        "event_type": event_type,
        "location": loc_name,
        "osm_query": osm_query,
        "short_summary": raw_text[:120] if raw_text else "Оперативна інформація"
    }

def _call_openai_vision(text: str, media_path: str, sys_prompt: str) -> requests.Response:
    with open(media_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{sys_prompt}\n\nТекст повідомлення: {text[:1000]}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }
    return requests.post(OPENAI_URL, headers=headers, json=data, timeout=20)

def _call_groq_text(text: str, sys_prompt: str, model: str = "qwen/qwen3.8-27b") -> requests.Response:
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"{sys_prompt} json:"},
            {"role": "user", "content": text[:1500]}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    return requests.post(GROQ_URL, headers=headers, json=data, timeout=10)

def _call_openai_text(text: str, sys_prompt: str) -> requests.Response:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text[:1500]}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    return requests.post(OPENAI_URL, headers=headers, json=data, timeout=15)

def _route_text_llm(text: str, sys_prompt: str) -> dict:
    if not text:
        return {}
    
    resp = _call_groq_text(text, sys_prompt, model="qwen/qwen3.8-27b")
    if resp.status_code in (429, 503, 500) and OPENAI_API_KEY:
        logger.warning(f"Groq API returned {resp.status_code}. Switching to OpenAI fallback...")
        resp = _call_openai_text(text, sys_prompt)
    elif resp.status_code != 200:
        logger.warning(f"Groq API error {resp.status_code}. Switching to Qwen 3.6 fallback...")
        resp = _call_groq_text(text, sys_prompt, model="qwen/qwen3.6-27b")
        if resp.status_code != 200:
            logger.warning(f"Groq API error {resp.status_code}. Switching to Compound Mini fallback...")
            resp = _call_groq_text(text, sys_prompt, model="groq/compound-mini")

        
    if resp.status_code != 200:
        return rule_based_fallback_parser(text)
        
    return clean_and_validate_json_response(resp.json()["choices"][0]["message"]["content"])

def process_with_llm(text: str, media_path: str = None) -> dict:
    llm_data = {}
    sys_prompt = build_system_prompt()
    try:
        if media_path and os.path.exists(media_path) and OPENAI_API_KEY:
            resp = _call_openai_vision(text, media_path, sys_prompt)
            resp.raise_for_status()
            llm_data = clean_and_validate_json_response(resp.json()["choices"][0]["message"]["content"])
        else:
            llm_data = _route_text_llm(text, sys_prompt)
            
    except Exception as e:
        logger.warning(f"LLM API error ({e}). Using Rule-Based Fallback.")
        llm_data = rule_based_fallback_parser(text)
    finally:
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
            except Exception as e:
                logger.error(f"Failed to remove media file {media_path}: {e}")
                
    return llm_data