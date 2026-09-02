import os
import json
import logging
import base64
import requests

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ти професійний OSINT-аналітик військової розвідки.
ТВОЯ ЗОНА ВІДПОВІДАЛЬНОСТІ — ВИКЛЮЧНО МІСТО КИЇВ ТА КИЇВСЬКА ОБЛАСТЬ!
Якщо повідомлення стосується інших міст чи країн (Дніпро, Одеса, Суми, Харків, Росія, закордон) — поверни "is_kyiv_region": false.

Поверни ТІЛЬКИ валідний JSON:
{
  "is_kyiv_region": true/false,
  "is_confirmed_incident": true/false,
  "is_radar_track": true/false,
  "event_type": "direct_strike|explosion|fire|destruction|casualties|armed_conflict|radar_track|general_alert",
  "location": "точна назва району/вулиці/міста на Київщині",
  "osm_query": "вибери ЛИШЕ ОДНУ найбільш конкретну локацію для OpenStreetMap (заборонено використовувати 'та' чи коми для перелічення кількох місць)",
  "casualties": true/false,
  "damage_level": "none|low|medium|high|critical",
  "short_summary": "стислий факт без води (1 речення)"
}
"""


def clean_json_response(text: str) -> dict:
    import json
    import re
    import logging
    logger = logging.getLogger(__name__)
    
    # 1. Clean markdown blocks explicitly
    cleaned = text.strip()
    if cleaned.startswith('```json'):
        cleaned = cleaned[7:]
    elif cleaned.startswith('```'):
        cleaned = cleaned[3:]
    if cleaned.endswith('```'):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    
    # 2. Fix Python boolean capitalization (True/False to true/false)
    # This prevents json.loads from crashing if LLM outputs Python booleans
    cleaned = cleaned.replace(": True", ": true").replace(": False", ": false")
    cleaned = cleaned.replace(":True", ": true").replace(":False", ": false")

    # 3. Try parsing directly first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
        
    # 4. Deep fallback: Use regex to extract everything between { and }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        json_str = match.group(0)
        json_str = json_str.replace(": True", ": true").replace(": False", ": false")
        try:
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"Failed regex JSON decode: {e} | Raw text: {text}")
    
    logger.error(f"Completely failed to decode JSON. Raw text: {text}")
    return {}

def rule_based_fallback_parser(raw_text: str) -> dict:
    if not raw_text:
        return {"is_kyiv_region": False}
        
    text = str(raw_text)
    t_lower = text.lower()
    
    regional_cities = ['бровари', 'вишгород', 'бориспіль', 'ірпінь', 'буча', 'фастів', 'біла церква', 'обухів']
    kyiv_districts = ['оболонь', 'поділ', 'печерськ', 'солом', 'дарниц']
    kyiv_keywords = ['київ', 'київськ', 'столиц', 'kyiv'] + regional_cities + kyiv_districts
    
    is_kyiv = any(k in t_lower for k in kyiv_keywords)
    
    event_type = "general_alert"
    if 'вибух' in t_lower: event_type = "explosion"
    elif 'приліт' in t_lower or 'влучання' in t_lower: event_type = "direct_strike"
    elif 'шахед' in t_lower or 'ракет' in t_lower or 'ціль' in t_lower or 'рух' in t_lower: event_type = "radar_track"
    elif 'пожеж' in t_lower or 'загорян' in t_lower: event_type = "fire"
    
    loc_name = "Київ та область"
    osm_query = "Київ"
    
    for k in regional_cities:
        if k in t_lower:
            loc_name = k.capitalize()
            osm_query = f"{loc_name}, Київська область, Україна"
            break
    
    if loc_name == "Київ та область":
        for k in kyiv_districts:
            if k in t_lower:
                loc_name = k.capitalize()
                osm_query = f"{loc_name}, Київ"
                break
                
    return {
        "is_kyiv_region": is_kyiv,
        "is_confirmed_incident": True,
        "is_radar_track": event_type == "radar_track",
        "event_type": event_type,
        "location": loc_name,
        "osm_query": osm_query,
        "short_summary": raw_text[:120] if raw_text else "Оперативна інформація"
    }

def process_with_llm(text: str, media_path: str = None) -> dict:
    llm_data = {}
    try:
        if media_path and os.path.exists(media_path) and OPENAI_API_KEY:
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
                            {"type": "text", "text": f"{SYSTEM_PROMPT}\n\nТекст повідомлення: {text[:1000]}"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1
            }
            resp = requests.post(OPENAI_URL, headers=headers, json=data, timeout=20)
            resp.raise_for_status()
            llm_data = clean_json_response(resp.json()["choices"][0]["message"]["content"])
            
        else:
            if not text:
                return {}
                
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            data = {
                "model": "llama-3.1-70b-versatile",
                "messages": [
                    {"role": "system", "content": f"{SYSTEM_PROMPT} json:"},
                    {"role": "user", "content": text[:1500]}
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }
            resp = requests.post(GROQ_URL, headers=headers, json=data, timeout=10)
            if resp.status_code in (429, 503, 500) and OPENAI_API_KEY:
                logger.warning(f"Groq API returned {resp.status_code}. Switching to OpenAI fallback...")
                headers_oai = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}"
                }
                data_oai = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text[:1500]}
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
                resp = requests.post(OPENAI_URL, headers=headers_oai, json=data_oai, timeout=15)
            elif resp.status_code != 200:
                data["model"] = "mixtral-8x7b-32768"
                resp = requests.post(GROQ_URL, headers=headers, json=data, timeout=10)
                
            if resp.status_code != 200:
                llm_data = rule_based_fallback_parser(text)
            else:
                llm_data = clean_json_response(resp.json()["choices"][0]["message"]["content"])
            
    except Exception as e:
        logger.warning(f"LLM API rate-limited or error ({e}). Using Rule-Based OSINT Fallback Parser.")
        llm_data = rule_based_fallback_parser(text)
    finally:
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
            except Exception as e:
                logger.error(f"Failed to remove media file {media_path}: {e}")
            
    return llm_data

