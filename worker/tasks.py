import os
import json
import logging
import base64
from celery import shared_task
from geoalchemy2.elements import WKTElement
from database.models import SessionLocal, DetectedEvent
import requests
from geopy.geocoders import Nominatim
from datetime import datetime, timedelta

from worker.osint.exif_extractor import EXIFExtractor
from worker.osint.ai_geolocation import ai_geo

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

geolocator = Nominatim(user_agent="lyudyn_iskun_v2_prod", timeout=10)
logger = logging.getLogger(__name__)

# Official government/military channels
OFFICIAL_SOURCES = {
    'kpszsu', 'comafua', 'va_kyiv', 'kyivcityofficial', 'dsns_kyiv_region', 
    'dsns_telegram', 'generalstaffzsu', 'mvs_ua'
}

# In-memory Geocoding Cache to prevent rate limiting
_GEO_CACHE = {}

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
  "osm_query": "коротка адреса для OpenStreetMap (напр: 'Шевченківський район, Київ' або 'Біла Церква')",
  "casualties": true/false,
  "damage_level": "none|low|medium|high|critical",
  "short_summary": "стислий факт без води (1 речення)"
}
"""

def rule_based_fallback_parser(raw_text: str) -> dict:
    t_lower = (raw_text or "").lower()
    kyiv_keywords = ['київ', 'київщин', 'бровар', 'борисп', 'ірпін', 'буч', 'вишгород', 'обух', 'фастів', 'васильк', 'біла церк', 'поділ', 'оболонь', 'печерськ', 'голосіїв', 'солом', 'дарниц', 'позняк', 'троєщин', 'борщагів', 'святошин', 'нивки', 'шуляв', 'татарк', 'загорівськ', 'лук']
    is_kyiv = any(k in t_lower for k in kyiv_keywords)
    
    event_type = "general_alert"
    if any(k in t_lower for k in ['радар', 'бпла', 'дрон', 'шахед', 'реактив', 'трек']):
        event_type = "radar_track"
    elif any(k in t_lower for k in ['приліт', 'вибух', 'удар', 'ракета', 'влучан']):
        event_type = "direct_strike"
    elif any(k in t_lower for k in ['пожеж', 'горить', 'руйнув']):
        event_type = "fire"
    elif any(k in t_lower for k in ['ппо', 'збито', 'робота ппо']):
        event_type = "air_defense"
        
    loc_name = "Київська область"
    for k in ['бровари', 'бориспіль', 'ірпінь', 'буча', 'вишгород', 'обухів', 'фастів', 'васильків', 'біла церква', 'поділ', 'оболонь', 'печерськ', 'голосієво', 'солом\'янка', 'дарниця', 'позняки', 'троєщина', 'борщагівка', 'святошин', 'нивки', 'шулявка', 'татарка', 'загорівська', 'лук\'янівка']:
        if k in t_lower:
            loc_name = k.capitalize()
            break

    return {
        "is_kyiv_region": is_kyiv,
        "is_confirmed_incident": True,
        "is_radar_track": event_type == "radar_track",
        "event_type": event_type,
        "location": loc_name,
        "osm_query": f"{loc_name}, Київ",
        "short_summary": raw_text[:120] if raw_text else "Оперативна інформація"
    }

exif_extractor = EXIFExtractor()

@shared_task(name="worker.tasks.process_message", bind=True, rate_limit="40/m", time_limit=30, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_message(self, payload_str):
    payload = json.loads(payload_str)
    text = payload.get("text", "")
    media_path = payload.get("media_path")
    channel = payload.get("channel", "")
    channel_clean = channel.lstrip('@').lower()
    message_id = payload.get("message_id")
    
    if not text and not media_path:
        return
        
    llm_data = {}
    geom_wkt = None
    osint_location = None
    
    # 0. OSINT Image Extraction (EXIF & GeoSpy)
    if media_path and os.path.exists(media_path):
        try:
            exif_data = exif_extractor.extract(media_path)
            if exif_data.get("has_gps") and exif_data.get("latitude") and exif_data.get("longitude"):
                geom_wkt = f"POINT({exif_data['longitude']} {exif_data['latitude']})"
                osint_location = f"EXIF GPS: {exif_data['latitude']}, {exif_data['longitude']}"
                logger.info(f"EXIF coordinates found: {geom_wkt}")
            else:
                geospy_data = ai_geo.analyze_image(media_path)
                if geospy_data and geospy_data.get("coordinates"):
                    lat, lon = geospy_data["coordinates"]
                    geom_wkt = f"POINT({lon} {lat})"
                    osint_location = f"GeoSpy AI: {geospy_data.get('predicted_location', 'Unknown')}"
                    logger.info(f"GeoSpy AI coordinates found: {geom_wkt}")
        except Exception as osint_err:
            logger.warning(f"OSINT Image Extraction error: {osint_err}")
    
    # 1. Analyze with LLM
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
            llm_data = json.loads(resp.json()["choices"][0]["message"]["content"])
            
            if os.path.exists(media_path):
                os.remove(media_path)
            
        else:
            if not text:
                if media_path and os.path.exists(media_path):
                    os.remove(media_path)
                return
                
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            data = {
                "model": "openai/gpt-oss-120b",
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
                data["model"] = "qwen/qwen3.6-27b"
                resp = requests.post(GROQ_URL, headers=headers, json=data, timeout=10)
                
            if resp.status_code != 200:
                llm_data = rule_based_fallback_parser(text)
            else:
                llm_data = json.loads(resp.json()["choices"][0]["message"]["content"])
            
    except Exception as e:
        logger.warning(f"LLM API rate-limited or error ({e}). Using Rule-Based OSINT Fallback Parser.")
        llm_data = rule_based_fallback_parser(text)
        if media_path and os.path.exists(media_path):
            os.remove(media_path)

    is_kyiv = llm_data.get("is_kyiv_region", False)
    if not is_kyiv:
        logger.info(f"Skipping non-Kyiv event: {llm_data.get('location')}")
        return

    is_confirmed = llm_data.get("is_confirmed_incident", False)
    is_radar = llm_data.get("is_radar_track", False)
    event_type = llm_data.get("event_type", "radar_track" if is_radar else "unknown")

    if not is_confirmed and not is_radar:
        return

    # 2. Factchecking & Consensus Classification
    is_official_src = channel_clean in OFFICIAL_SOURCES
    text_lower = text.lower()
    
    # Check for panic/IPSO markers in unconfirmed single source
    is_panic = any(w in text_lower for w in ['масований прорив', 'все палає', 'все знищено', 'терміново тікайте', 'зрада'])

    # 3. Geocoding
    location = llm_data.get("location")
    osm_query = llm_data.get("osm_query") or location
    
    if not geom_wkt and osm_query:
        if osm_query in _GEO_CACHE:
            geom_wkt = _GEO_CACHE[osm_query]
        else:
            try:
                geo = geolocator.geocode(osm_query)
                if not geo and location:
                    geo = geolocator.geocode(f"{location}, Київська область, Україна")
                if geo:
                    geom_wkt = f"POINT({geo.longitude} {geo.latitude})"
                    _GEO_CACHE[osm_query] = geom_wkt
                    logger.info(f"Geocoded {osm_query} -> {geom_wkt}")
                else:
                    logger.warning(f"Could not geocode {osm_query}")
            except Exception as e:
                logger.error(f"Geocoding Error: {e}")
            
    final_location_text = f"{location} | 🔍 {osint_location}" if osint_location else location
    final_message_text = llm_data.get("short_summary") or text[:2000]

    # Base resonance
    base_resonance = 65 if is_confirmed else 35
    if llm_data.get('casualties') is True or any(w in text_lower for w in ['загибл', 'поранен', 'жертв', 'постраждал']):
        base_resonance += 25
    if llm_data.get('damage_level') in ['high', 'critical']:
        base_resonance += 15
    if event_type in ['direct_strike', 'explosion']:
        base_resonance += 15
    if is_official_src:
        base_resonance += 10

    views = payload.get("views", 0)
    forwards = payload.get("forwards", 0)
    if views > 20000:
        base_resonance += 10
    if forwards > 100:
        base_resonance += 10

    # 4. Save with Multi-Source Consensus Clustering
    db = SessionLocal()
    try:
        # Check if already exists exactly
        existing = db.query(DetectedEvent).filter(
            DetectedEvent.source_channel == channel,
            DetectedEvent.message_id == message_id
        ).first()
        
        if existing:
            existing.resonance_score = max(existing.resonance_score, min(base_resonance, 100))
            existing.event_type = event_type
            db.commit()
            return

        # Multi-Source Consensus Cluster Search (within 30 minutes in same location)
        threshold_30m = datetime.utcnow() - timedelta(minutes=30)
        cluster_match = None
        if location:
            cluster_match = db.query(DetectedEvent).filter(
                DetectedEvent.detected_at >= threshold_30m,
                DetectedEvent.location_text.ilike(f"%{location}%"),
                DetectedEvent.source_channel != channel
            ).first()

        if cluster_match and is_confirmed:
            # Add to consensus cluster
            sources_set = set(cluster_match.sources_list.split(',')) if cluster_match.sources_list else {cluster_match.source_channel}
            sources_set.add(channel)
            cluster_match.sources_list = ",".join(filter(None, sources_set))
            cluster_match.sources_count = len(sources_set)
            cluster_match.is_official = cluster_match.is_official or is_official_src
            
            # Upgrade verification status
            if cluster_match.sources_count >= 2 or cluster_match.is_official or cluster_match.has_media:
                cluster_match.verification_status = "VERIFIED"
                cluster_match.resonance_score = min(cluster_match.resonance_score + 15, 100)
            
            db.commit()
            logger.info(f"Consensus Cluster updated for event {cluster_match.id} (Sources: {cluster_match.sources_list})")
            return

        # Determine initial verification status
        if is_official_src:
            verif_status = "OFFICIAL"
        elif payload.get("has_media"):
            verif_status = "VERIFIED"
        elif is_panic:
            verif_status = "POSSIBLE_IPSO"
            base_resonance = max(base_resonance - 20, 20)
        else:
            verif_status = "UNVERIFIED_SINGLE_SOURCE"

        event = DetectedEvent(
            source_channel=channel,
            message_id=message_id,
            message_text=final_message_text,
            event_type=event_type,
            location_text=final_location_text,
            geom=WKTElement(geom_wkt, srid=4326) if geom_wkt else None,
            resonance_score=min(base_resonance, 100),
            has_media=payload.get("has_media", False),
            raw_message=payload_str,
            verification_status=verif_status,
            sources_count=1,
            sources_list=channel,
            is_official=is_official_src
        )
        db.add(event)
        db.commit()
        logger.info(f"Saved event {event.id} [{verif_status}] from @{event.source_channel}")
    except Exception as e:
        db.rollback()
        logger.error(f"DB Error: {e}")
        raise
    finally:
        db.close()

@shared_task(name="worker.tasks.cleanup_old_events")
def cleanup_old_events():
    db = SessionLocal()
    try:
        threshold = datetime.utcnow() - timedelta(hours=24)
        deleted = db.query(DetectedEvent).filter(DetectedEvent.detected_at < threshold).delete()
        db.commit()
        logger.info(f"Cleaned up {deleted} old events.")
    except Exception as e:
        db.rollback()
        logger.error(f"Cleanup Error: {e}")
    finally:
        db.close()
