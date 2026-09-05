import os
import re
import json
import logging
import base64
import requests
import datetime
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from worker.schemas import ParsedEventSchema

KYIV_TZ = ZoneInfo("Europe/Kyiv")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_URL = "https://api.x.ai/v1/chat/completions"
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.20-0309-non-reasoning")
MAX_XAI_DAILY_CALLS = int(os.getenv("MAX_XAI_DAILY_CALLS", "600"))

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

try:
    import redis
    redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
except Exception:
    redis_client = None

logger = logging.getLogger(__name__)

def get_current_time_str() -> str:
    now_kyiv = datetime.datetime.now(datetime.timezone.utc).astimezone(KYIV_TZ)
    return now_kyiv.strftime("%Y-%m-%d %H:%M:%S (Kyiv)")

def build_system_prompt() -> str:
    current_time = get_current_time_str()
    return f"""Ти професійний OSINT-аналітик військової розвідки C4ISR.
ТВОЯ ЗОНА ВІДПОВІДАЛЬНОСТІ — ВСЯ ТЕРИТОРІЯ УКРАЇНИ (24 ОБЛАСТІ, МІСТО КИЇВ, СЕВАСТОПОЛЬ ТА АР КРИМ)!
ПОТОЧНИЙ СИСТЕМНИЙ ЧАС: {current_time}. Будь-які події за цю дату є актуальними.

Визначай точну область події ('target_oblast'):
- 'kyiv_city', 'kyiv_oblast', 'kharkiv', 'dnipropetrovsk', 'odesa', 'zaporizhzhia', 'mykolaiv', 'sumy', 'poltava', 'lviv', 'chernihiv', 'vinnytsia', 'zhytomyr', 'cherkasy', 'kirovohrad', 'khmelnytskyi', 'rivne', 'volyn', 'ternopil', 'ivano_frankivsk', 'zakarpattia', 'chernivtsi', 'kherson', 'donetsk', 'luhansk', 'crimea', 'sevastopol' або 'all'.
- Якщо подія стосується Києва або Київщини, встанови "is_kyiv_region": true, для інших областей: false.

УВАГА НА ТОПОНІМИ-ОМОНІМИ ТА РЕГІОНАЛЬНИЙ КОНТЕКСТ:
- "Дніпровський район Херсона" — target_oblast: 'kherson', це ХЕРСОН!
- "Дніпровський район Запоріжжя" — target_oblast: 'zaporizhzhia', це ЗАПОРІЖЖЯ!
- "Васильківка" (Синельниківський район) — target_oblast: 'dnipropetrovsk', це ДНІПРОПЕТРОВЩИНА, а не Васильків!
- "Шевченківський район Харкова" — target_oblast: 'kharkiv', це ХАРКІВ!
- "Подільський район Одеської області" — target_oblast: 'odesa', це ОДЕЩИНА!
- "Дніпровський район Києва" / "Шевченківський район Києва" — target_oblast: 'kyiv_city'!

ЯКЩО ТОБІ НАДАНО ФОТО — ПРОВЕДИ ВІЗУАЛЬНИЙ АНАЛІЗ ФОТО:
ЗАБОРОНЕНО вгадувати точний район за типовою архітектурою (наприклад, панельні будинки чи хрущовки). 
Якщо на фото немає унікальних орієнтирів (чіткі вивіски, відомі пам'ятники, унікальні перехрестя, читабельний текст вулиці), локація ПОВИННА бути визначена як загальна (наприклад, назва міста або області). 
ЯКЩО ПОВІДОМЛЕННЯ ЦИВІЛЬНЕ АБО НЕ Є ВІЙСЬКОВОЮ ПОДІЄЮ:
- Якщо новина про політику, корупцію, кол-центри, суди, прокуратуру, НАБУ, побутовий кримінал, ТЦК, звичайні ДТП, погоду, комунальні аварії — ОБОВ'ЯЗКОВО повертай:
  "event_type": "civilian_noise", "is_confirmed_incident": false, "is_radar_track": false, "short_summary": "Не військова подія".

Поверни ТІЛЬКИ валідний JSON у такій структурі:
{{
  "is_kyiv_region": true/false,
  "target_oblast": "код області (наприклад: kharkiv, odesa, dnipropetrovsk, kyiv_city, zaporizhzhia...)",
  "is_confirmed_incident": true/false,
  "is_radar_track": true/false,
  "event_type": "air_defense|direct_strike|explosion|fire|destruction|casualties|armed_conflict|radar_track|general_alert|civilian_noise",
  "location": "точна назва району/вулиці/міста",
  "osm_query": "вибери ЛИШЕ ОДНУ найбільш конкретну локацію для OpenStreetMap (наприклад: Салтівка, Харків або Пересип, Одеса)",
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
            "target_oblast": str(raw_dict.get("target_oblast", "all")),
            "is_confirmed_incident": bool(raw_dict.get("is_confirmed_incident", False)),
            "is_radar_track": bool(raw_dict.get("is_radar_track", False)),
            "event_type": str(raw_dict.get("event_type", "general_alert")).lower(),
            "location": str(raw_dict.get("location", "Україна")),
            "osm_query": str(raw_dict.get("osm_query", "Україна")),
            "casualties": bool(raw_dict.get("casualties", False)),
            "damage_level": str(raw_dict.get("damage_level", "none")).lower(),
            "short_summary": str(raw_dict.get("short_summary", "Оперативна інформація"))[:150]
        }

def rule_based_fallback_parser(raw_text: str) -> dict:
    if not raw_text:
        return {"is_kyiv_region": False}
        
    text = str(raw_text)
    t_lower = text.lower()
    
    from worker.geo_disambiguation import (
        detect_external_oblast,
        is_explicitly_kyiv_context,
        disambiguate_toponym,
        is_civilian_non_threat_noise
    )

    # 0. Fast-reject civilian municipal maintenance / road works / traffic disruptions
    if is_civilian_non_threat_noise(text):
        return {
            "is_kyiv_region": False,
            "is_confirmed_incident": False,
            "is_radar_track": False,
            "event_type": "civilian_noise",
            "location": "Цивільні комунальні роботи",
            "osm_query": "Україна",
            "short_summary": "Цивільне комунальне / дорожнє оголошення"
        }
    
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

    ext_ob = detect_external_oblast(t_lower)
    has_explicit_kyiv = is_explicitly_kyiv_context(t_lower)

    # If an external oblast is detected and no explicit Kyiv context exists, this is NOT Kyiv!
    if ext_ob and not has_explicit_kyiv:
        is_kyiv = False
    else:
        is_kyiv = any(k in t_lower for k in kyiv_keywords)
    
    event_type = None
    if any(w in t_lower for w in ['збито', 'подавлено', 'робота ппо', 'збиття', 'відбито атаку', 'збили']):
        event_type = "air_defense"
    elif 'вибух' in t_lower:
        event_type = "explosion"
    elif 'приліт' in t_lower or 'влуч' in t_lower or 'снаряд' in t_lower or 'обстріл' in t_lower:
        event_type = "direct_strike"
    elif any(w in t_lower for w in ['шахед', 'ракет', 'ціль', 'бпла', 'дрон', 'мопед', '🛵', 'вектор ціл', 'реактив', 'каб', 'авіа']) or any(
        phrase in t_lower for phrase in ['рух ціл', 'рух бпла', 'рух ракет', 'рух дронів', 'курс на', 'летить на', 'помічено ціль', 'повітряна ціль']
    ):
        event_type = "radar_track"
    elif 'пожеж' in t_lower or 'загорян' in t_lower:
        if any(w in t_lower for w in ['приліт', 'уламк', 'атак', 'вибух', 'обстріл', 'удар']):
            event_type = "fire"
    elif any(w in t_lower for w in ['повітряна тривога', 'відбій повітряної', 'загроза балістики', 'ракетна небезпека', 'повітряної тривоги', 'тривог', 'відбій']):
        event_type = "general_alert"

    # Strict Gatekeeper: If no genuine tactical threat detected, fast-reject as civilian noise
    if not event_type:
        return {
            "is_kyiv_region": False,
            "target_oblast": "all",
            "is_confirmed_incident": False,
            "is_radar_track": False,
            "event_type": "civilian_noise",
            "location": "Цивільне повідомлення",
            "osm_query": "Україна",
            "short_summary": "Повідомлення не містить тактичних загроз"
        }
    
    loc_name = "Київ та область"
    osm_query = "Київ"
    
    for k in regional_cities:
        if k in t_lower:
            # Guard: If preceded by street designator (e.g. 'вул. Коцюбинського'), this is a street, not a town!
            if re.search(r'(?:вул\.?|вулиц[яіе]|пров\.?|проспект|просп\.?|бульвар|бул\.?)\s+' + re.escape(k), t_lower):
                continue
            # Guard: 'лесі українки' or 'українки' in street names is NOT the town 'Українка'
            if k == 'українк' and any(st in t_lower for st in ['лесі українки', 'леси украинки', 'бульвар лесі', 'проспект лесі', 'площа лесі']):
                continue
            loc_name = regional_city_names[k]
            osm_query = f"{loc_name}, Київська область, Україна"
            break

    if loc_name == "Київ та область":
        for k in kyiv_districts:
            if k in t_lower:
                # Guard: 'новопечерськ' is NOT Pechersk district in a military threat context!
                if k == 'печерс' and 'новопечерськ' in t_lower:
                    continue
                # Guard: 'дніпровський металургійний' or non-Kyiv industrial plants
                if k == 'дніпровськ' and any(ex in t_lower for ex in ['металургійн', 'завод', 'херсон', 'запоріж']):
                    continue
                loc_name = kyiv_district_names[k]
                osm_query = f"{loc_name}, Київ"
                break

    # Contextual Disambiguation Guard
    dis = disambiguate_toponym(loc_name, full_text=raw_text)
    resolved_oblast = "all"
    if dis.get("is_homonym"):
        loc_name = dis["canonical"]
        if not dis.get("is_kyiv"):
            is_kyiv = False
            osm_query = loc_name
            resolved_oblast = dis.get("oblast", "all")
    else:
        ext_ob = detect_external_oblast(raw_text)
        if ext_ob:
            resolved_oblast = ext_ob
            if not is_explicitly_kyiv_context(raw_text):
                is_kyiv = False
        elif is_kyiv:
            resolved_oblast = "kyiv_city"
                
    return {
        "is_kyiv_region": is_kyiv,
        "target_oblast": resolved_oblast,
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

def _call_ollama_text(text: str, sys_prompt: str, model: str = None) -> dict:
    """Offline / Local LLM fallback via Ollama (OPSEC Tier 1).
    Ensures zero cloud leakage and offline execution during blackouts.
    """
    model_name = model or OLLAMA_MODEL
    url = OLLAMA_URL
    payload = {
        "model": model_name,
        "prompt": f"{sys_prompt}\n\nТекст повідомлення:\n{text[:1500]}\nПоверни ТІЛЬКИ валідний JSON:",
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 512
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            raw_content = data.get("response") or ""
            if not raw_content and "choices" in data:
                raw_content = data["choices"][0]["message"]["content"]
            if raw_content:
                parsed = clean_and_validate_json_response(raw_content)
                if parsed:
                    return parsed
    except Exception as e:
        logger.debug(f"Ollama local inference unavailable: {e}")
    return {}

def _call_xai_text(text: str, sys_prompt: str) -> Optional[dict]:
    """Calls xAI Grok with intelligent token economy and budget preservation.
    - Caches responses in Redis (24h TTL) to avoid duplicate billable API calls.
    - Limits input text to 800 chars and max_tokens to 160.
    - Enforces a daily call budget circuit breaker (default 600 calls/day, ~$0.10/day).
    """
    if not XAI_API_KEY or not text:
        return None

    import hashlib
    h = hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]
    cache_key = f"xai_cache:{h}"

    # 1. Semantic cache check (0 tokens, $0.00 cost)
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                logger.debug(f"[XAI_CACHE_HIT] Reusing Grok extraction for {h}")
                return json.loads(cached)
        except Exception:
            pass

    # 2. Daily call quota circuit breaker
    today_str = datetime.date.today().isoformat()
    daily_key = f"xai_daily_calls:{today_str}"
    if redis_client:
        try:
            curr_calls = int(redis_client.get(daily_key) or 0)
            if curr_calls >= MAX_XAI_DAILY_CALLS:
                logger.warning(f"xAI Grok daily budget reached ({curr_calls}/{MAX_XAI_DAILY_CALLS}). Preserving funds, falling back to local heuristic.")
                return None
        except Exception:
            pass

    # 3. Compact payload invocation
    payload = {
        "model": XAI_MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text[:800]}
        ],
        "max_tokens": 160,
        "temperature": 0.1
    }

    try:
        resp = requests.post(
            XAI_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {XAI_API_KEY}"
            },
            json=payload,
            timeout=10
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = clean_and_validate_json_response(content)
            if parsed:
                if redis_client:
                    try:
                        redis_client.setex(cache_key, 86400, json.dumps(parsed))
                        redis_client.incr(daily_key)
                        redis_client.expire(daily_key, 86400 * 2)
                    except Exception:
                        pass
                return parsed
        else:
            logger.warning(f"xAI Grok returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"xAI Grok connection error: {e}")
    return None

def _route_text_llm(text: str, sys_prompt: str) -> dict:
    if not text:
        return {}

    # Priority 1: High-Precision xAI Grok (Budget-managed & cached)
    if XAI_API_KEY:
        xai_res = _call_xai_text(text, sys_prompt)
        if xai_res:
            return xai_res

    # Priority 2: Secondary Groq API (Free tier)
    resp = None
    if GROQ_API_KEY:
        try:
            resp = _call_groq_text(text, sys_prompt, model="qwen/qwen3.8-27b")
            if resp is not None and resp.status_code == 200:
                return clean_and_validate_json_response(resp.json()["choices"][0]["message"]["content"])
        except Exception as e:
            logger.warning(f"Groq API connection error: {e}")

    # Priority 3: Local Ollama LLM
    if resp is None or getattr(resp, 'status_code', None) in (429, 503, 500, 504):
        logger.info("Attempting local Ollama LLM fallback...")
        ollama_data = _call_ollama_text(text, sys_prompt)
        if ollama_data:
            return ollama_data

    # Priority 4: Cloud secondary fallback if OpenAI key exists
    if resp is not None and getattr(resp, 'status_code', None) in (429, 503, 500) and OPENAI_API_KEY:
        logger.warning("Switching to OpenAI fallback...")
        resp = _call_openai_text(text, sys_prompt)
        if resp.status_code == 200:
            return clean_and_validate_json_response(resp.json()["choices"][0]["message"]["content"])

    return rule_based_fallback_parser(text)

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