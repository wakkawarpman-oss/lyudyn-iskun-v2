from worker.llm_engine import process_with_llm
import os
import json
import logging
from typing import Optional, List, Dict, Tuple, Any
import redis
from celery import shared_task
from geoalchemy2.elements import WKTElement
from database.models import SessionLocal, DetectedEvent
from sqlalchemy import func, or_, text as sql_text
from geopy.geocoders import Nominatim
from datetime import datetime, timedelta

from worker.osint.exif_extractor import EXIFExtractor
from worker.osint.ai_geolocation import ai_geo
from worker.osint.sentiment import sentiment_analyzer
from worker.osint.image_dedup import compute_phash, find_similar_event
from worker.osint.video_frame_extractor import is_video_file, extract_representative_frame


geolocator = Nominatim(user_agent="lyudyn_iskun_v2_prod", timeout=10)


def flush_api_caches():
    """Deletes cached API and analytics responses using non-blocking SCAN + DELETE
    so the single-threaded Redis event loop is never blocked during high RPS ingestion."""
    try:
        base_keys = ["api:events", "api:stats", "api:shelters", "api:geoint:zones", "osint:deep_analysis"]
        for k in base_keys:
            redis_client.delete(k)
        
        # Non-blocking scan_iter instead of blocking keys()
        for pattern in ["api:events:*", "api:v3:events:*", "api:zones:*", "api:v3:stats*"]:
            batch = []
            for k in redis_client.scan_iter(match=pattern, count=500):
                batch.append(k)
                if len(batch) >= 500:
                    redis_client.delete(*batch)
                    batch = []
            if batch:
                redis_client.delete(*batch)
    except Exception as re:
        logger.warning(f"Redis non-blocking cache flush warning: {re}")
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


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL)

import hashlib
import threading

_geocode_lock = threading.Lock()

def _geocode_cache_key(query: str) -> str:
    h = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"geo:{h}"

def _internal_geocode(query: str):
    """Geocodes via Nominatim, cached in Redis (24h TTL). Returns WKT 'POINT(lon lat)' string."""
    if not query:
        return None
    cache_key = _geocode_cache_key(query)
    # 1. Try Redis cache (shared across all gevent workers and containers)
    try:
        val = redis_client.get(cache_key)
        if val:
            if isinstance(val, bytes):
                val = val.decode("utf-8")
            logger.debug(f"[CACHE_HIT] Geocoding cache hit for '{query}': {val}")
            return val
    except Exception as e:
        logger.warning(f"Redis geocode cache get error: {e}")

    # 2. External geocoding (only on cache miss)
    try:
        geo = geolocator.geocode(query)
        if geo:
            res = f"POINT({geo.longitude} {geo.latitude})"
            # Store in Redis (24-hour TTL)
            try:
                redis_client.setex(cache_key, 86400, res)
            except Exception as ex:
                logger.warning(f"Redis geocode cache set error: {ex}")
            return res
    except Exception as e:
        logger.error(f"Geocoding Error for '{query}': {e}")
    return None

def cached_geocode(query: str):
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

    from worker.geo_disambiguation import (
        detect_external_oblast,
        is_explicitly_kyiv_context,
        detect_channel_oblast,
        is_civilian_non_threat_noise
    )

    # Fast-reject civilian municipal maintenance / road works / traffic delays BEFORE any DB/media/LLM processing
    if is_civilian_non_threat_noise(text):
        return {"skip": True, "reason": "civilian_noise"}

    channel_clean = payload.get("channel", "").lstrip("@").lower()
    ch_native_oblast = detect_channel_oblast(channel_clean)
    has_kyiv_context = is_explicitly_kyiv_context(text)

    # Channel origin guard: if channel is from Rivne, Lviv, Kherson etc., and text does not explicitly mention Kyiv, drop it!
    if ch_native_oblast and ch_native_oblast not in ["kyiv_city", "kyiv_oblast"]:
        if not has_kyiv_context:
            return {"skip": True, "reason": "not_kyiv", "non_kyiv_oblast": ch_native_oblast}

    # Record message forward relationship (Telerecon Forward Graph)
    fwd_from = payload.get("fwd_from")
    target_channel = payload.get("channel", "")
    if fwd_from and target_channel:
        try:
            from database.repository import NetworkGraphRepository
            with NetworkGraphRepository() as net_repo:
                net_repo.record_forward_edge(fwd_from, target_channel, sample_text=text[:300] if text else None)
        except Exception as e:
            logger.warning(f"Telerecon forward edge recording warning: {e}")

    channel = payload.get("channel", "")
    message_id = payload.get("message_id")
    if channel and message_id is not None:
        db = SessionLocal()
        try:
            if db.query(DetectedEvent.id).filter(
                DetectedEvent.source_channel == channel,
                DetectedEvent.message_id == message_id
            ).first():
                return {"skip": True, "reason": "already_processed"}
        finally:
            db.close()
        
    geom_wkt = None
    osint_location = None
    image_phash = None

    if media_path and is_video_file(media_path) and os.path.exists(media_path):
        frame_path = extract_representative_frame(media_path)
        if frame_path:
            media_path = frame_path
        else:
            media_path = None

    if media_path and os.path.exists(media_path):
        image_phash = compute_phash(media_path) or None
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
    ext_oblast = detect_external_oblast(text)

    # Fast-exit for explicit non-Kyiv regional news reposts before making expensive LLM calls
    if ext_oblast and not has_kyiv_context:
        return {"skip": True, "reason": "not_kyiv", "non_kyiv_oblast": ext_oblast}

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

    if llm_data.get("event_type") == "civilian_noise":
        return {"skip": True, "reason": "civilian_noise"}

    is_kyiv_region = llm_data.get("is_kyiv_region", False)
    
    # Pure Kyiv-only channels that primarily post about Kyiv / Kyiv region
    pure_kyiv_channels = [
        "1181169156", "kyivlive", "kyiv_novosti", "t_kyiv", "kyiv_alarm", "va_kyiv", "vakyiv",
        "kyivcityofficial", "los_solomas", "kyivoperat", "kyivoperativ", "kontur_map",
        "dsns_kyiv_region", "kyiv24", "kievinfo_kyiv", "kiev_info", "kievinfo"
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

    # Only score sentiment for confirmed incidents, not every radar_track/
    # general_alert — those are the bulk of traffic and this is an extra
    # Groq call per message.
    sentiment = None
    if is_confirmed:
        try:
            sentiment = sentiment_analyzer.analyze(text)
        except Exception as e:
            logger.warning(f"Sentiment analysis error: {e}")

    return {
        "skip": False,
        "payload": payload,
        "payload_str": payload_str,
        "llm_data": llm_data,
        "geom_wkt": geom_wkt,
        "osint_location": osint_location,
        "sentiment": sentiment,
        "image_phash": image_phash,
    }

from worker.canonical_geo import resolve_canonical_toponym
from worker.scoring import calculate_significance_score, calculate_confidence_score, compute_composite_resonance
from worker.source_registry import get_source_metadata
from worker.geo_extractors.address_parser import extract_addresses
from worker.geo_extractors.poi_matcher import match_poi

@shared_task(name="worker.tasks.pipeline_geocode", bind=True, time_limit=15, autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def pipeline_geocode(self, data):
    if data.get("skip"):
        return data

    payload = data["payload"]
    llm_data = data["llm_data"]
    text = payload.get("text", "")
    geom_wkt = data.get("geom_wkt")
    osint_location = data.get("osint_location")

    precision_tier = "settlement"
    precision_radius_m = 2000
    is_fallback_geo = False

    # Tier 1: EXIF GPS (Highest precision: ±10m)
    if geom_wkt and osint_location and "EXIF" in osint_location:
        precision_tier = "exact"
        precision_radius_m = 10
        is_fallback_geo = False
    elif not geom_wkt:
        # Tier 2: Tactical POI Match (Building-level: ±50m)
        poi = match_poi(text)
        if poi:
            geom_wkt = f"POINT({poi.lon} {poi.lat})"
            precision_tier = poi.precision  # "building"
            precision_radius_m = 50
            is_fallback_geo = False
            llm_data["location"] = poi.name
            osint_location = f"POI: {poi.name} ({poi.address})"
        else:
            # Tier 3 & 4: Deterministic Regex Address (Address ±100m, Street ±300m)
            parsed_addrs = extract_addresses(text)
            if parsed_addrs:
                best_addr = max(parsed_addrs, key=lambda a: (a.building is not None, len(a.street)))
                geo_pt = cached_geocode(best_addr.normalized_query)
                if geo_pt:
                    geom_wkt = geo_pt
                    precision_tier = best_addr.precision  # "address" or "street"
                    precision_radius_m = 100 if best_addr.building else 300
                    is_fallback_geo = False
                    loc_display = f"{best_addr.street}{', ' + best_addr.building if best_addr.building else ''}, {best_addr.city}"
                    llm_data["location"] = loc_display
                    osint_location = f"Address: {loc_display}"

    # Tier 5: Canonical Toponym Fallback (Settlement ±2000m, Region ±10000m)
    if not geom_wkt:
        raw_location = llm_data.get("location") or "Київ та область"
        canonical_name, lat, lon, is_fallback = resolve_canonical_toponym(
            raw_location,
            full_text=text,
            channel_oblast=payload.get("oblast")
        )
        llm_data["location"] = canonical_name
        is_fallback_geo = is_fallback
        if lat is not None and lon is not None:
            geom_wkt = f"POINT({lon} {lat})"
            precision_tier = "settlement" if not is_fallback_geo else "region"
            precision_radius_m = 2000 if not is_fallback_geo else 10000
        else:
            geom_wkt = cached_geocode(f"{canonical_name}, Київська область, Україна")
            precision_tier = "settlement" if geom_wkt else "region"
            precision_radius_m = 2000 if geom_wkt else 10000

    data["geom_wkt"] = geom_wkt
    data["is_fallback_geo"] = is_fallback_geo
    data["precision_tier"] = precision_tier
    data["precision_radius_m"] = precision_radius_m
    if osint_location:
        data["osint_location"] = osint_location

    return data

@shared_task(name="worker.tasks.pipeline_cluster_and_save", bind=True)
def pipeline_cluster_and_save(self, data):
    if data.get("skip"):
        return
        
    payload = data["payload"]
    llm_data = data["llm_data"]
    geom_wkt = data["geom_wkt"]
    is_fallback_geo = data.get("is_fallback_geo", False)
    image_phash = data.get("image_phash")
    sentiment = data.get("sentiment") or {}
    is_panic = sentiment_analyzer.should_boost_alert(sentiment)
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
    sig_score = calculate_significance_score(event_type, has_media, text, is_panic=is_panic)
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

        # Serialize clustering per location within this transaction: without
        # this, two workers processing messages for the same location_text
        # at nearly the same time can both miss each other's not-yet-committed
        # row and each INSERT a new incident instead of merging into one.
        db.execute(sql_text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": final_location_text})

        # Incident Clustering (A.4 PostGIS Spatial Proximity + Text Fallback):
        cluster_match = None
        has_real_geom = bool(geom_wkt) and not is_fallback_geo

        # Priority 1: Geographic clustering with PostGIS on real coordinates within 30m window
        if has_real_geom:
            threshold_30m = msg_date - timedelta(minutes=30)
            try:
                cluster_match = db.query(DetectedEvent).filter(
                    DetectedEvent.detected_at >= threshold_30m,
                    DetectedEvent.geom.isnot(None),
                    DetectedEvent.is_fallback_geo == False,
                    func.ST_DWithin(DetectedEvent.geom, func.ST_GeomFromText(geom_wkt, 4326), 0.08)
                ).order_by(DetectedEvent.detected_at.desc()).first()
            except Exception as e:
                logger.warning(f"Spatial clustering lookup fallback: {e}")
                cluster_match = None

        # Priority 2: Fallback to original text-based clustering (25 min window)
        if not cluster_match:
            threshold_25m = msg_date - timedelta(minutes=25)
            query = db.query(DetectedEvent).filter(
                DetectedEvent.detected_at >= threshold_25m,
                DetectedEvent.location_text == final_location_text
            )
            cluster_match = query.order_by(DetectedEvent.detected_at.desc()).first()

        # Guard: Prevent cross-district collision (e.g. Pechersk vs Dniprovsky)
        if cluster_match:
            def _get_district_token(s: str) -> Optional[str]:
                if not s:
                    return None
                s_low = s.lower()
                for token in [
                    "голосіїв", "дарниц", "деснян", "дніпров", "оболон",
                    "печерськ", "поділ", "святошин", "солом'ян", "соломян", "шевченків"
                ]:
                    if token in s_low:
                        return token
                return None

            dist_existing = _get_district_token(cluster_match.location_text)
            dist_new = _get_district_token(final_location_text)
            if dist_existing and dist_new and dist_existing != dist_new:
                logger.info(f"🚫 Prevented cross-district merger: '{cluster_match.location_text}' vs '{final_location_text}'")
                cluster_match = None

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
            flush_api_caches()
            return

        # NEW Incident
        import re
        loc_slug = re.sub(r'[^a-zA-Z0-9а-яА-ЯіїєґІЇЄҐ]', '', location)[:10].upper() or "KYIV"
        new_incident_id = f"INC-{msg_date.strftime('%Y%m%d%H%M')}-{loc_slug}"

        # Anti-IPSO: flag (not drop) a photo/video-frame that perceptually
        # matches one already seen — recycled/archival images passed off as
        # a fresh incident. POSSIBLE_IPSO already exists as a
        # verification_status value in this model, so reuse it rather than
        # add a new column.
        verification_status = "OFFICIAL" if is_official_src else ("VERIFIED" if conf_score >= 80 else "UNVERIFIED_SINGLE_SOURCE")
        if image_phash:
            duplicate_of = find_similar_event(db, image_phash)
            if duplicate_of:
                verification_status = "POSSIBLE_IPSO"
                logger.warning(
                    f"image_phash match: incident {new_incident_id} photo resembles "
                    f"existing incident {duplicate_of.incident_id} (id={duplicate_of.id})"
                )

        # NASA FIRMS Thermal Anomaly Cross-Verification
        lat = data.get("lat")
        lon = data.get("lon")
        if (lat is None or lon is None) and geom_wkt and "POINT" in geom_wkt:
            try:
                coords = geom_wkt.replace("POINT", "").replace("(", "").replace(")", "").strip().split()
                lon = float(coords[0])
                lat = float(coords[1])
            except Exception:
                pass

        if lat and lon and event_type in ['direct_strike', 'explosion', 'fire', 'destruction', 'shelling']:
            try:
                from worker.osint.firms_viirs import find_nearby_thermal_anomaly
                thermal_match = find_nearby_thermal_anomaly(lat, lon, msg_date, max_distance_km=7.0, max_hours_diff=8.0)
                if thermal_match:
                    conf_score = min(100, conf_score + 25)
                    if verification_status not in ["OFFICIAL", "POSSIBLE_IPSO"]:
                        verification_status = "VERIFIED"
                    logger.info(
                        f"NASA FIRMS thermal match for incident {new_incident_id} at ({lat}, {lon}): "
                        f"FRP {thermal_match.get('frp_mw')}MW, dist {thermal_match.get('distance_km')}km"
                    )
            except Exception as e:
                logger.warning(f"FIRMS cross-verification warning: {e}")

        # Sightline Critical Infrastructure Proximity Check
        nearby_infra_text = None
        if lat and lon and event_type in ['direct_strike', 'explosion', 'fire', 'destruction', 'shelling', 'radar_track']:
            try:
                from worker.geo_extractors.poi_matcher import find_nearby_critical_infrastructure
                infra_matches = find_nearby_critical_infrastructure(lat, lon, max_radius_m=1200.0)
                if infra_matches:
                    closest = infra_matches[0]
                    nearby_infra_text = f"{closest.category_label}: {closest.name} ({int(closest.distance_m)} м)"
                    logger.info(f"Sightline matched critical infrastructure for {new_incident_id}: {nearby_infra_text}")
            except Exception as e_infra:
                logger.warning(f"Sightline proximity warning: {e_infra}")

        event = DetectedEvent(
            incident_id=new_incident_id,
            source_channel=channel,
            message_id=message_id,
            message_text=final_message_text,
            event_type=event_type,
            location_text=final_location_text,
            geom=WKTElement(geom_wkt, srid=4326) if geom_wkt else None,
            is_fallback_geo=is_fallback_geo,
            image_phash=image_phash,
            geo_precision=data.get("precision_tier", "settlement"),
            geo_radius_m=data.get("precision_radius_m", 2000),
            significance_score=sig_score,
            confidence_score=conf_score,
            resonance_score=res_score,
            detected_at=msg_date,
            first_seen_at=msg_date,
            last_seen_at=msg_date,
            has_media=has_media,
            raw_message=payload_str,
            verification_status=verification_status,
            sources_count=1,
            sources_list=channel,
            is_official=is_official_src,
            source_tier=source_tier,
            source_weight=source_weight,
            nearby_infrastructure=nearby_infra_text
        )
        db.add(event)
        db.commit()
        flush_api_caches()
    except Exception as e:
        if hasattr(db, "rollback"):
            try:
                db.rollback()
            except Exception:
                pass
        logger.error(f"DB Error: {e}")
        raise
    finally:
        db.close()

def get_time_window_stats(db, hours_lookback: int = 6) -> dict:
    """
    Returns time-windowed incident counts (5m, 15m, 60m) and dynamic spike detection.

    Spike Rule (A.2 Contract):
    - is_spike = True if recent_5m >= 3 and recent_5m >= (recent_60m / 12.0) * 2.0
    - If recent_60m == 0 or recent_5m < 3: is_spike = False (fail-safe)
    """
    now_utc = datetime.utcnow()
    
    recent_5m = db.query(func.count(DetectedEvent.id)).filter(
        DetectedEvent.detected_at >= now_utc - timedelta(minutes=5),
        DetectedEvent.source_channel.not_ilike("test%")
    ).scalar() or 0

    recent_15m = db.query(func.count(DetectedEvent.id)).filter(
        DetectedEvent.detected_at >= now_utc - timedelta(minutes=15),
        DetectedEvent.source_channel.not_ilike("test%")
    ).scalar() or 0

    recent_60m = db.query(func.count(DetectedEvent.id)).filter(
        DetectedEvent.detected_at >= now_utc - timedelta(minutes=60),
        DetectedEvent.source_channel.not_ilike("test%")
    ).scalar() or 0

    avg_per_5m = recent_60m / 12.0
    is_spike = (recent_5m >= 3) and (recent_5m >= avg_per_5m * 2.0) if recent_60m > 0 else False

    return {
        "events_5m": recent_5m,
        "events_15m": recent_15m,
        "events_60m": recent_60m,
        "spike": is_spike,
        "avg_per_5m": round(avg_per_5m, 2),
    }


@shared_task(name="worker.tasks.cleanup_old_events")
def cleanup_old_events(retention_hours: int = 24):
    """
    Tiered Retention Task (A.4 / Retention Contract):
    - Tier 1: Delete low-significance noise (general_alert, significance < 40) older than 24h.
    - Tier 2: Archive confirmed physical strikes older than 90d (verification_status='ARCHIVED').
    """
    db = SessionLocal()
    deleted = 0
    try:
        threshold_24h = datetime.utcnow() - timedelta(hours=retention_hours)
        
        # Tier 1: Delete noise older than 24h
        garbage_deleted = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at < threshold_24h,
            or_(
                DetectedEvent.significance_score < 40,
                DetectedEvent.event_type == "general_alert"
            ),
            ~DetectedEvent.event_type.in_([
                "direct_strike",
                "explosion",
                "fire",
                "destruction",
                "casualties",
                "air_defense"
            ])
        ).delete(synchronize_session=False)
        db.commit()

        # Tier 2: Archive physical strikes older than 90d (never delete)
        threshold_90d = datetime.utcnow() - timedelta(days=90)
        archived_count = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at < threshold_90d,
            DetectedEvent.event_type.in_([
                "direct_strike",
                "explosion",
                "fire",
                "destruction",
                "casualties",
                "air_defense"
            ]),
            DetectedEvent.verification_status != "ARCHIVED"
        ).update({"verification_status": "ARCHIVED"}, synchronize_session=False)
        db.commit()

        deleted = garbage_deleted + archived_count
        logger.info(
            f"Daily Prune (Tiered): Deleted {garbage_deleted} noise records (>24h), "
            f"Archived {archived_count} physical strike records (>90d)."
        )

        flush_api_caches()
        logger.info("Daily Prune: Flushed stale API caches from Redis.")

        return {
            "tier1_deleted_24h_garbage": garbage_deleted,
            "tier2_archived_90d_strikes": archived_count,
            "total_operations": deleted,
            "status": "success"
        }
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

