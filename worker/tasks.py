from worker.llm_engine import process_with_llm
from worker.osint.sentiment import sentiment_analyzer
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


geolocator = Nominatim(user_agent="lyudyn_iskun_v2_prod", timeout=10)
logger = logging.getLogger(__name__)

# Official government/military channels
OFFICIAL_SOURCES = {
    'kpszsu', 'comafua', 'va_kyiv', 'kyivcityofficial', 'dsns_kyiv_region', 
    'dsns_telegram', 'generalstaffzsu', 'mvs_ua'
}

# In-memory Geocoding Cache to prevent rate limiting

def _get_tier_info(channel: str) -> tuple:
    channel_lower = channel.lower()
    
    # Tier S (Official)
    official_keywords = ["kpszsu", "dsns", "mvs", "kmva", "kyivcity", "generalstaff", "comafua", "official"]
    if any(k in channel_lower for k in official_keywords):
        return ("S", 1.0)
        
    # Tier A (Monitors)
    monitor_keywords = ["monitor", "radar", "alert", "trivoga"]
    if any(k in channel_lower for k in monitor_keywords):
        return ("A", 0.7)
        
    # Tier B (Media & Eyewitnesses)
    return ("B", 0.5)



exif_extractor = EXIFExtractor()


import threading

_geocode_lock = threading.Lock()

_GEO_CACHE = {}

def _internal_geocode(query):
    if query in _GEO_CACHE:
        return _GEO_CACHE[query]
    try:
        geo = geolocator.geocode(query)
        if geo:
            res = f"POINT({geo.longitude} {geo.latitude})"
            if len(_GEO_CACHE) < 2000:
                _GEO_CACHE[query] = res
            return res
    except Exception as e:
        logger.error(f"Geocoding Error: {e}")
    return None

def cached_geocode(query):
    with _geocode_lock:
        return _internal_geocode(query)


from celery import chain

@shared_task(name="worker.tasks.process_message", bind=True)
def process_message(self, payload_str):
    # Entry point for the pipeline
    workflow = chain(
        pipeline_extract.s(payload_str),
        pipeline_geocode.s(),
        pipeline_cluster_and_save.s()
    )
    workflow.apply_async()

@shared_task(name="worker.tasks.pipeline_extract", bind=True, time_limit=30, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def pipeline_extract(self, payload_str):
    payload = json.loads(payload_str)
    text = payload.get("text", "")
    media_path = payload.get("media_path")
    
    if not text and not media_path:
        return {"skip": True, "reason": "empty"}
        
    geom_wkt = None
    osint_location = None
    
    if media_path and os.path.exists(media_path):
        try:
            exif_data = exif_extractor.extract(media_path)
            if exif_data.get("has_gps") and exif_data.get("latitude") and exif_data.get("longitude"):
                geom_wkt = f"POINT({exif_data['longitude']} {exif_data['latitude']})"
                osint_location = f"EXIF GPS: {exif_data['latitude']}, {exif_data['longitude']}"
            else:
                geospy_data = ai_geo.analyze_image(media_path)
                if geospy_data and geospy_data.get("coordinates"):
                    lat, lon = geospy_data["coordinates"]
                    geom_wkt = f"POINT({lon} {lat})"
                    osint_location = f"GeoSpy AI: {geospy_data.get('predicted_location', 'Unknown')}"
        except Exception as e:
            logger.warning(f"OSINT error: {e}")

    t_lower = text.lower()
    is_generic_alert = any(w in t_lower for w in ["увага! повітряна тривога", "відбій повітряної тривоги", "руйнувань та потерпілих немає", "ракетна небезпека", "загроза балістики"])
    if is_generic_alert and len(text) < 150 and not media_path:
        llm_data = {
            "is_kyiv_region": True,
            "is_confirmed_incident": True,
            "is_radar_track": False,
            "event_type": "general_alert",
            "location": "Київська область",
            "osm_query": "Київська область, Україна",
            "short_summary": text[:100]
        }
    else:
        llm_data = process_with_llm(text, media_path)

    is_kyiv_region = llm_data.get("is_kyiv_region", False)
    channel_clean = payload.get("channel", "").lstrip("@").lower()
    
    # Pure Kyiv-only channels that only post about Kyiv / Kyiv region
    pure_kyiv_channels = [
        "1181169156", "kyivlive", "kyiv_novosti", "t_kyiv", "kyiv_alarm", "va_kyiv", "vakyiv",
        "kyivcityofficial", "los_solomas", "kyivoperat", "kyivoperativ", "kontur_map",
        "dsns_kyiv_region", "kyiv24"
    ]
    if channel_clean in pure_kyiv_channels:
        is_kyiv_region = True
        
    if not is_kyiv_region:
        return {"skip": True, "reason": "not_kyiv"}

    is_confirmed = llm_data.get("is_confirmed_incident", False)
    is_radar = llm_data.get("is_radar_track", False)
    is_alert = llm_data.get("event_type") in ["general_alert", "alert", "explosion", "direct_strike", "fire", "radar_track"]
    if not is_confirmed and not is_radar and not is_alert:
        return {"skip": True, "reason": "not_confirmed"}

    return {
        "skip": False,
        "payload": payload,
        "payload_str": payload_str,
        "llm_data": llm_data,
        "geom_wkt": geom_wkt,
        "osint_location": osint_location
    }

from worker.canonical_geo import resolve_canonical_toponym
from worker.scoring import calculate_significance_score, calculate_confidence_score, compute_composite_resonance
from worker.source_registry import get_source_metadata

@shared_task(name="worker.tasks.pipeline_geocode", bind=True, time_limit=15, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def pipeline_geocode(self, data):
    if data.get("skip"):
        return data
        
    llm_data = data["llm_data"]
    geom_wkt = data.get("geom_wkt")
    
    raw_location = llm_data.get("location") or "Київ та область"
    canonical_name, lat, lon = resolve_canonical_toponym(raw_location)
    
    # Store normalized canonical name
    llm_data["location"] = canonical_name
    
    if lat is not None and lon is not None:
        geom_wkt = f"POINT({lon} {lat})"
    elif not geom_wkt:
        geom_wkt = cached_geocode(f"{canonical_name}, Київська область, Україна")
            
    data["geom_wkt"] = geom_wkt
    return data

@shared_task(name="worker.tasks.pipeline_cluster_and_save", bind=True)
def pipeline_cluster_and_save(self, data):
    if data.get("skip"):
        return
        
    payload = data["payload"]
    llm_data = data["llm_data"]
    geom_wkt = data["geom_wkt"]
    osint_location = data.get("osint_location")
    payload_str = data["payload_str"]
    
    text = payload.get("text", "")
    channel = payload.get("channel", "")
    channel_clean = channel.lstrip('@').lower()
    msg_date_str = payload.get("date")
    if msg_date_str:
        try:
            msg_date = datetime.fromisoformat(msg_date_str).replace(tzinfo=None)
        except Exception:
            msg_date = datetime.utcnow()
    else:
        msg_date = datetime.utcnow()
        
    message_id = payload.get("message_id")
    event_type = llm_data.get("event_type", "general_alert")
    location = llm_data.get("location") or "Київ та область"
    
    source_meta = get_source_metadata(channel_clean)
    is_official_src = source_meta["type"] in ["OFFICIAL", "MILITARY"]
    source_tier = source_meta["tier"]
    source_weight = source_meta["base_weight"]
    
    final_location_text = f"{location} | 🔍 {osint_location}" if osint_location else location
    final_message_text = llm_data.get("short_summary") or text[:2000]

    has_media = payload.get("has_media", False)
    sig_score = calculate_significance_score(event_type, has_media, text)
    conf_score = calculate_confidence_score([channel], is_official_src, has_media)
    res_score = compute_composite_resonance(sig_score, conf_score)

    db = SessionLocal()
    try:
        existing = db.query(DetectedEvent).filter(
            DetectedEvent.source_channel == channel,
            DetectedEvent.message_id == message_id
        ).first()
        
        if existing:
            existing.significance_score = max(existing.significance_score or 50, sig_score)
            existing.confidence_score = max(existing.confidence_score or 50, conf_score)
            existing.resonance_score = compute_composite_resonance(existing.significance_score, existing.confidence_score)
            existing.event_type = event_type
            db.commit()
            return

        # Incident Clustering: Look for active incident within 25 minutes
        threshold_25m = msg_date - timedelta(minutes=25)
        query = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= threshold_25m,
            DetectedEvent.location_text == final_location_text
        )
        
        cluster_match = query.order_by(DetectedEvent.detected_at.desc()).first()

        if cluster_match:
            # MERGE into existing incident
            sources_set = set(cluster_match.sources_list.split(',')) if cluster_match.sources_list else {cluster_match.source_channel}
            sources_set.add(channel)
            cluster_match.sources_list = ",".join(filter(None, sources_set))
            cluster_match.sources_count = len(sources_set)
            cluster_match.is_official = cluster_match.is_official or is_official_src
            cluster_match.has_media = cluster_match.has_media or has_media
            cluster_match.last_seen_at = max(cluster_match.last_seen_at or msg_date, msg_date)
            
            # Upgrade event_type to highest kinetic impact
            type_hierarchy = {
                "direct_strike": 5, "casualties": 5, "destruction": 4, "explosion": 3,
                "fire": 3, "armed_conflict": 3, "air_defense": 2, "radar_track": 1, "general_alert": 0
            }
            if type_hierarchy.get(event_type, 0) > type_hierarchy.get(cluster_match.event_type, 0):
                cluster_match.event_type = event_type
                cluster_match.message_text = f"{final_message_text} [Оновлено]"

            # Recalculate 2D scores for consolidated incident
            cluster_match.significance_score = max(cluster_match.significance_score or 50, sig_score)
            cluster_match.confidence_score = calculate_confidence_score(
                cluster_match.sources_list,
                cluster_match.is_official,
                cluster_match.has_media
            )
            cluster_match.resonance_score = compute_composite_resonance(
                cluster_match.significance_score,
                cluster_match.confidence_score
            )
            if cluster_match.confidence_score >= 85:
                cluster_match.verification_status = "VERIFIED"
            elif cluster_match.is_official:
                cluster_match.verification_status = "OFFICIAL"

            db.commit()
            return

        # NEW Incident
        import re
        loc_slug = re.sub(r'[^a-zA-Z0-9а-яА-ЯіїєґІЇЄҐ]', '', location)[:10].upper() or "KYIV"
        new_incident_id = f"INC-{msg_date.strftime('%Y%m%d%H%M')}-{loc_slug}"

        event = DetectedEvent(
            incident_id=new_incident_id,
            source_channel=channel,
            message_id=message_id,
            message_text=final_message_text,
            event_type=event_type,
            location_text=final_location_text,
            geom=WKTElement(geom_wkt, srid=4326) if geom_wkt else None,
            significance_score=sig_score,
            confidence_score=conf_score,
            resonance_score=res_score,
            detected_at=msg_date,
            first_seen_at=msg_date,
            last_seen_at=msg_date,
            has_media=has_media,
            raw_message=payload_str,
            verification_status="OFFICIAL" if is_official_src else ("VERIFIED" if conf_score >= 80 else "UNVERIFIED_SINGLE_SOURCE"),
            sources_count=1,
            sources_list=channel,
            is_official=is_official_src,
            source_tier=source_tier,
            source_weight=source_weight
        )
        db.add(event)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"DB Error: {e}")
        raise
    finally:
        db.close()

@shared_task(name="worker.tasks.cleanup_old_events")
def cleanup_old_events(retention_hours: int = 24):
    db = SessionLocal()
    deleted = 0
    try:
        threshold = datetime.utcnow() - timedelta(hours=retention_hours)
        deleted = db.query(DetectedEvent).filter(DetectedEvent.detected_at < threshold).delete()
        db.commit()
        logger.info(f"Daily Prune: Cleaned up {deleted} events older than {retention_hours}h.")
        
        # Flush redis API caches so all map/stats caches refresh immediately
        try:
            r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
            for k in ["api:events", "api:stats", "api:shelters", "api:geoint:zones"]:
                r.delete(k)
            logger.info("Daily Prune: Flushed stale API caches from Redis.")
        except Exception as re:
            logger.warning(f"Redis cache flush warning: {re}")
            
        return {"deleted_events": deleted, "retention_hours": retention_hours, "status": "success"}
    except Exception as e:
        db.rollback()
        logger.error(f"Cleanup Error: {e}")
        return {"error": str(e), "status": "failed"}
    finally:
        db.close()


@shared_task(name="worker.tasks.run_watchdog")
def run_watchdog():
    from worker.watchdog import run_health_check
    run_health_check()

@shared_task(name="worker.tasks.fetch_rss_news_task")
def fetch_rss_news_task():
    from worker.osint.rss_intel import rss_v2
    news = rss_v2.fetch_all(hours=1)
    
    for item in news:
        # Construct a payload that process_message can understand
        # We'll treat RSS news as just another text message but from 'rss_<source>'
        payload = {
            "text": f"{item['title']}\n\n{item['summary']}",
            "channel": item["source"],
            "message_id": int(item["time"].timestamp()), # Fake ID based on timestamp
            "date": item["time"].isoformat(),
            "views": 0,
            "forwards": 0
        }
        # Schedule the processing
        process_message.delay(json.dumps(payload))
        
    return f"Scheduled {len(news)} RSS items."

