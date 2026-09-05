from typing import Optional, List, Dict, Any
import logging
from fastapi import FastAPI, Depends, Request, Response, HTTPException, Query

logger = logging.getLogger(__name__)
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, not_
from database.models import SessionLocal, DetectedEvent
import datetime
import os
import json
import redis
import hmac
import time
from typing import Dict, List, Optional

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.Redis.from_url(REDIS_URL)

from api.security.authz import (
    RoleEnum,
    SecurityClearance,
    UserIdentity,
    get_current_user,
    verify_restricted_access_policy,
    log_security_event,
)

# --- Rate Limiting Engine ---
RATE_LIMIT_GUEST = int(os.getenv("RATE_LIMIT_GUEST", "100"))      # 100 req/h for anonymous clients
RATE_LIMIT_AUTH = int(os.getenv("RATE_LIMIT_AUTH", "1000"))       # 1000 req/h for authenticated clients
RATE_LIMIT_WINDOW = 3600    # 1 hour

_local_rate_limit_cache: Dict[str, List[float]] = {}

def check_rate_limit(client_id: str, is_authenticated: bool = False):
    limit = RATE_LIMIT_AUTH if is_authenticated else RATE_LIMIT_GUEST
    now = time.time()
    if redis_client:
        try:
            key = f"ratelimit:{client_id}"
            req_count = redis_client.incr(key)
            if req_count == 1:
                redis_client.expire(key, RATE_LIMIT_WINDOW)
            if req_count > limit:
                raise HTTPException(
                    status_code=429,
                    detail={"error": "RATE_LIMIT_EXCEEDED", "message": f"Rate limit of {limit} req/hour exceeded. Try again later."}
                )
            return
        except HTTPException:
            raise
        except Exception:
            pass

    # In-memory fallback
    window_start = now - RATE_LIMIT_WINDOW
    records = _local_rate_limit_cache.get(client_id, [])
    records = [t for t in records if t > window_start]
    if len(records) >= limit:
        raise HTTPException(
            status_code=429,
            detail={"error": "RATE_LIMIT_EXCEEDED", "message": f"Rate limit of {limit} req/hour exceeded. Try again later."}
        )
    records.append(now)
    _local_rate_limit_cache[client_id] = records


def is_tactical_authorized(request: Optional[Request] = None, token: Optional[str] = None, db: Optional[Session] = None) -> bool:
    """
    Validates whether the request is authorized for the restricted operational / military contour.
    Strictly enforces platform segmentation:
    1. Civilian contour (default): 1:1 exact WGS-84 coordinates, kinematics, waypoints, trail,
       and true strike addresses, but stripped of internal targeting cones, EW directives, and sensor telemetry.
    2. Restricted operational contour: requires tactical API token or an active approval granted
       by Security Officer (SECURITY_OFFICER_1) stored in Redis with 24-hour TTL.
    """
    user = get_current_user(request=request, token=token, redis_client=redis_client)
    authorized = verify_restricted_access_policy(
        user=user,
        resource_type="tactical_events",
        requested_sector="all",
        db_session=db,
        redis_client=redis_client
    )

    client_ip = request.client.host if (request and getattr(request, "client", None)) else "127.0.0.1"
    decision = "ALLOWED" if authorized else "DENIED"
    reason = "APPROVAL_VALID" if authorized else "CIVILIAN_CONTOUR"
    try:
        log_security_event(
            actor_id=user.user_id,
            actor_role=user.role.value,
            action="RESTRICTED_ACCESS_CHECK",
            resource_type="tactical_events",
            decision=decision,
            reason=reason,
            client_ip=client_ip,
            db_session=db
        )
    except Exception as e:
        logger.debug(f"Audit log fallback: {e}")

    return authorized

OBLAST_BOUNDS = {
    "kyiv_city": {"min_lat": 50.25, "max_lat": 50.60, "min_lon": 30.20, "max_lon": 30.85},
    "kyiv_oblast": {"min_lat": 49.18, "max_lat": 51.55, "min_lon": 29.25, "max_lon": 32.18, "exclude_city": True},
    "kyiv": {"min_lat": 49.18, "max_lat": 51.55, "min_lon": 29.25, "max_lon": 32.18},
    "vinnytsia": {"min_lat": 48.05, "max_lat": 49.85, "min_lon": 27.35, "max_lon": 30.05},
    "volyn": {"min_lat": 50.30, "max_lat": 51.95, "min_lon": 23.60, "max_lon": 26.15},
    "dnipropetrovsk": {"min_lat": 47.45, "max_lat": 49.25, "min_lon": 33.00, "max_lon": 36.90},
    "donetsk": {"min_lat": 46.85, "max_lat": 49.25, "min_lon": 36.65, "max_lon": 39.25},
    "zhytomyr": {"min_lat": 49.65, "max_lat": 51.75, "min_lon": 27.20, "max_lon": 29.75},
    "zakarpattia": {"min_lat": 47.90, "max_lat": 49.10, "min_lon": 22.15, "max_lon": 24.65},
    "zaporizhzhia": {"min_lat": 46.35, "max_lat": 48.15, "min_lon": 34.50, "max_lon": 37.30},
    "ivano_frankivsk": {"min_lat": 47.70, "max_lat": 49.35, "min_lon": 23.60, "max_lon": 25.60},
    "kirovohrad": {"min_lat": 47.75, "max_lat": 49.25, "min_lon": 29.75, "max_lon": 33.60},
    "luhansk": {"min_lat": 47.80, "max_lat": 50.10, "min_lon": 37.85, "max_lon": 40.25},
    "lviv": {"min_lat": 48.70, "max_lat": 50.65, "min_lon": 22.70, "max_lon": 25.40},
    "mykolaiv": {"min_lat": 46.35, "max_lat": 48.20, "min_lon": 30.90, "max_lon": 33.20},
    "odesa": {"min_lat": 45.10, "max_lat": 48.25, "min_lon": 29.20, "max_lon": 31.40},
    "poltava": {"min_lat": 48.75, "max_lat": 50.60, "min_lon": 32.05, "max_lon": 35.50},
    "rivne": {"min_lat": 50.05, "max_lat": 51.95, "min_lon": 25.10, "max_lon": 27.45},
    "sumy": {"min_lat": 50.00, "max_lat": 52.40, "min_lon": 33.00, "max_lon": 35.70},
    "ternopil": {"min_lat": 48.50, "max_lat": 50.30, "min_lon": 24.70, "max_lon": 26.45},
    "kharkiv": {"min_lat": 48.50, "max_lat": 50.50, "min_lon": 35.10, "max_lon": 38.30},
    "kherson": {"min_lat": 45.85, "max_lat": 47.60, "min_lon": 31.50, "max_lon": 35.10},
    "khmelnytskyi": {"min_lat": 48.40, "max_lat": 50.60, "min_lon": 26.10, "max_lon": 27.90},
    "cherkasy": {"min_lat": 48.40, "max_lat": 50.25, "min_lon": 29.80, "max_lon": 32.90},
    "chernivtsi": {"min_lat": 47.70, "max_lat": 48.70, "min_lon": 24.90, "max_lon": 27.50},
    "chernihiv": {"min_lat": 50.40, "max_lat": 52.40, "min_lon": 30.50, "max_lon": 33.50},
    "crimea": {"min_lat": 44.30, "max_lat": 46.25, "min_lon": 32.45, "max_lon": 36.70, "exclude_sevastopol": True},
    "sevastopol": {"min_lat": 44.40, "max_lat": 44.85, "min_lon": 33.35, "max_lon": 33.90},
}

from api.cache_layer import (
    cache_manager,
    TTL_RADAR_LIVE,
    TTL_EVENTS_FEED,
    TTL_STATS_AGGREGATES,
    TTL_STATIC_LAYERS
)

def get_cached(key):
    return cache_manager.get(key)

def set_cached(key, val, ttl=TTL_EVENTS_FEED):
    return cache_manager.set(key, val, ttl=ttl)


from api.cot import router as cot_router

app = FastAPI(
    title="ОКІНТ-ПРО — Тактична C4ISR & GEOINT Платформа",
    description="""
    ## Багатодоменна система збору, аналітики та верифікації загроз
    
    ### Ключові можливості платформи:
    - **Повітряна обстановка:** живий радар цілей, Dead Reckoning розрахунки підльоту.
    - **ППО та зони вогню (WEZ):** розрахунок зон ураження та РЛС (Тор-М2, Панцир-С1, Стріла-10, Бук-М3, С-400).
    - **LOB-пеленгація:** пряма геодезична засічка WGS-84, триангуляція азимутів та розрахунок CEP.
    - **Оптична розвідка CCTV:** вузли оптичного спостереження ТОТ (Донецьк, Севастополь, Луганськ, Енергодар) та прифронтового моніторингу (Харків).
    - **Супутниковий РЕБ:** моніторинг радіозавад Sentinel-1 CSAR 5 GHz.
    - **Термоаномалії:** NASA FIRMS VIIRS 375m супутникові термоточки.
    - **Астрономічна хронолокація NOAA:** розрахунок азимута сонця та проєкції тіней.
    - **Тактична інтеграція ATAK:** Cursor-on-Target (CoT XML 2.0) та DataPackage (.zip) MIL-STD-2525C.
    - **Двостороння синхронізація:** Redis Pub/Sub шина між Telegram-ботом, Telethon та веб-мапою.
    """,
    version="3.2.0",
)
app.include_router(cot_router)


@app.middleware("http")
async def add_tactical_cache_control_headers(request: Request, call_next):
    response: Response = await call_next(request)
    path = request.url.path
    # Eliminate mobile webview caching on root, HTML and live radar endpoints
    if path == "/" or path.endswith(".html") or path.startswith("/api/v1/radar") or path.startswith("/api/stats"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/api/events")
def get_events(hours: int = 72, oblast: Optional[str] = None, db: Session = Depends(get_db)):
    cache_key = f"api:events:{hours}:{oblast or 'all'}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    query = db.query(
        DetectedEvent.id,
        DetectedEvent.source_channel,
        DetectedEvent.message_id,
        DetectedEvent.event_type,
        DetectedEvent.location_text,
        DetectedEvent.resonance_score,
        DetectedEvent.confidence_score,
        DetectedEvent.detected_at,
        DetectedEvent.verification_status,
        DetectedEvent.sources_count,
        DetectedEvent.sources_list,
        DetectedEvent.is_official,
        DetectedEvent.has_media,
        DetectedEvent.is_fallback_geo,
        DetectedEvent.geo_precision,
        DetectedEvent.geo_radius_m,
        DetectedEvent.message_text,
        func.ST_Y(DetectedEvent.geom).label('lat'),
        func.ST_X(DetectedEvent.geom).label('lon')
    ).filter(
        DetectedEvent.geom.isnot(None),
        DetectedEvent.source_channel.not_ilike('test%'),
        DetectedEvent.detected_at >= threshold
    )

    if oblast and oblast != "all" and oblast in OBLAST_BOUNDS:
        b = OBLAST_BOUNDS[oblast]
        query = query.filter(
            func.ST_Y(DetectedEvent.geom) >= b["min_lat"],
            func.ST_Y(DetectedEvent.geom) <= b["max_lat"],
            func.ST_X(DetectedEvent.geom) >= b["min_lon"],
            func.ST_X(DetectedEvent.geom) <= b["max_lon"]
        )
        if b.get("exclude_city"):
            cb = OBLAST_BOUNDS["kyiv_city"]
            query = query.filter(
                not_(and_(
                    func.ST_Y(DetectedEvent.geom) >= cb["min_lat"],
                    func.ST_Y(DetectedEvent.geom) <= cb["max_lat"],
                    func.ST_X(DetectedEvent.geom) >= cb["min_lon"],
                    func.ST_X(DetectedEvent.geom) <= cb["max_lon"]
                ))
            )
        if b.get("exclude_sevastopol"):
            sb = OBLAST_BOUNDS["sevastopol"]
            query = query.filter(
                not_(and_(
                    func.ST_Y(DetectedEvent.geom) >= sb["min_lat"],
                    func.ST_Y(DetectedEvent.geom) <= sb["max_lat"],
                    func.ST_X(DetectedEvent.geom) >= sb["min_lon"],
                    func.ST_X(DetectedEvent.geom) <= sb["max_lon"]
                ))
            )

    events = query.order_by(DetectedEvent.detected_at.desc()).all()
    
    AIR_DEFENSE_KEYWORDS = (
        'тривог', 'шахед', 'бпла', 'дрон', 'ракет', 'вибух', 'приліт', 'влучан',
        'ппо', 'збитт', 'уламк', 'баліст', 'пуск', 'авіаці', 'каб', 'укритт', 'відбій',
        'артобстріл', 'загроза', 'shahed', 'ракета', 'повітрян'
    )
    result = []
    for e in events:
        if e.is_fallback_geo:
            continue

        msg_lower = (e.message_text or '').lower()
        from worker.geo_disambiguation import is_civilian_non_threat_noise
        # Tactical hygiene filter: Drop non-military city news (traffic, road repairs, domestic maintenance)
        if is_civilian_non_threat_noise(msg_lower):
            continue

        if e.event_type in ('general_alert', 'alert') and not e.is_official:
            if not any(k in msg_lower for k in AIR_DEFENSE_KEYWORDS):
                continue

        prec = getattr(e, "geo_precision", "settlement") or "settlement"
        rad = getattr(e, "geo_radius_m", 2000) or 2000

        if prec == "exact":
            logic = f"🎯 Точні GPS координати (EXIF ±{rad}м)"
        elif prec == "building":
            logic = f"🏢 Тактичний об'єкт POI (±{rad}м)"
        elif prec == "address":
            logic = f"📍 Точна адреса будинку (±{rad}м)"
        elif prec == "street":
            logic = f"🛣️ Вулиця / Магістраль (±{rad}м)"
        elif e.has_media:
            logic = "📸 Фото EXIF GPS / Vision AI"
        elif e.is_official:
            logic = "🏛️ Офіційний звіт КМВА / Мера"
        elif (e.sources_count or 1) >= 2:
            logic = f"🟢 Перехресний консенсус ({e.sources_count} дж.)"
        else:
            logic = "🗺️ Текстова прив'язка топоніма (OSINT)"

        chan = (e.source_channel or "").strip()
        if chan in ("1181169156", "-1001181169156"):
            chan = "kievreal1"
        elif chan in ("2053889953", "-1002053889953"):
            chan = "operatyvnyi_monitor"
        
        is_num = chan.replace("-", "").isdigit()
        src_link = f"https://t.me/{chan.lstrip('@')}/{e.message_id}" if (chan and not is_num and e.message_id) else ""

        result.append({
            "id": e.id,
            "source_channel": chan,
            "source_link": src_link,
            "message_id": e.message_id,
            "event_type": e.event_type,
            "location_text": e.location_text,
            "resonance_score": e.resonance_score,
            "confidence_score": getattr(e, "confidence_score", 50) or 50,
            "detected_at": f"{e.detected_at.isoformat()}Z" if e.detected_at else None,
            "lat": e.lat,
            "lon": e.lon,
            "verification_status": e.verification_status or "UNVERIFIED_SINGLE_SOURCE",
            "sources_count": e.sources_count or 1,
            "sources_list": getattr(e, "sources_list", chan) or chan,
            "is_official": e.is_official or False,
            "has_media": e.has_media or False,
            "geo_precision": prec,
            "geo_radius_m": rad,
            "geocoding_logic": logic,
            "message_text": e.message_text[:140] if e.message_text else ""
        })
    set_cached(cache_key, result, ttl=30)
    return result

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    cached = get_cached("api:stats")
    if cached:
        return cached

    threshold_24h = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    base_filter = [
        DetectedEvent.detected_at >= threshold_24h,
        DetectedEvent.source_channel.not_ilike('test%')
    ]
    
    total_events = db.query(func.count(DetectedEvent.id)).filter(DetectedEvent.source_channel.not_ilike('test%')).scalar() or 0
    events_24h = db.query(func.count(DetectedEvent.id)).filter(*base_filter).scalar() or 0
    avg_resonance = db.query(func.avg(DetectedEvent.resonance_score)).filter(*base_filter).scalar() or 0
    
    # Category breakdown
    categories_raw = (
        db.query(DetectedEvent.event_type, func.count(DetectedEvent.id))
        .filter(*base_filter)
        .group_by(DetectedEvent.event_type)
        .all()
    )
    
    categories = {cat: count for cat, count in categories_raw}
    
    # Top sources
    sources_raw = (
        db.query(DetectedEvent.source_channel, func.count(DetectedEvent.id))
        .filter(DetectedEvent.source_channel.not_ilike('test%'))
        .group_by(DetectedEvent.source_channel)
        .order_by(func.count(DetectedEvent.id).desc())
        .limit(5)
        .all()
    )
    
    sources = [{"channel": ch, "count": cnt} for ch, cnt in sources_raw]
    
    try:
        from worker.tasks import get_time_window_stats
        time_windows = get_time_window_stats(db)
    except Exception:
        time_windows = {"events_5m": 0, "events_15m": 0, "events_60m": 0, "spike": False, "avg_per_5m": 0.0}

    res = {
        "total_events": total_events,
        "events_24h": events_24h,
        "avg_resonance": round(float(avg_resonance), 1),
        "categories": categories,
        "sources": sources,
        "time_windows": time_windows
    }
    set_cached("api:stats", res, ttl=60)
    return res


@app.get("/api/stats/accuracy")
def get_accuracy_metrics(hours: int = 72, db: Session = Depends(get_db)):
    """Tactical accuracy telemetry: CEP precision, ETA drift, and HITL consensus rates."""
    from worker.telemetry_metrics import get_system_accuracy_telemetry
    cache_key = f"api:stats:accuracy:{hours}"
    cached = get_cached(cache_key)
    if cached:
        return cached
    data = get_system_accuracy_telemetry(db, hours=hours)
    set_cached(cache_key, data, ttl=60)
    return data


@app.get("/api/datalake/stats")
def get_datalake_statistics():
    """Returns storage metrics and partition catalog for Parquet Data Lake (P3.2)."""
    from worker.data_lake import get_data_lake_stats
    return get_data_lake_stats()


@app.post("/api/datalake/archive")
def trigger_datalake_archive(days_back: int = 1, db: Session = Depends(get_db)):
    """Triggers archival of events older than days_back to Parquet Data Lake."""
    from datetime import datetime, timedelta
    from worker.data_lake import archive_events_to_parquet
    threshold = datetime.utcnow() - timedelta(days=days_back)
    return archive_events_to_parquet(db, threshold_date=threshold)


@app.get("/api/shelters")
@app.get("/api/v1/shelters")
def get_map_shelters(db: Session = Depends(get_db)):
    from database.models import BombShelter
    shelters = db.query(
        BombShelter.id,
        BombShelter.name,
        BombShelter.address,
        BombShelter.district,
        BombShelter.shelter_type,
        BombShelter.capacity,
        BombShelter.latitude,
        BombShelter.longitude
    ).all()
    
    result = [
        {
            "id": s.id,
            "name": s.name,
            "address": s.address,
            "district": s.district,
            "type": s.shelter_type,
            "capacity": s.capacity,
            "lat": float(s.latitude) if s.latitude else 0.0,
            "lon": float(s.longitude) if s.longitude else 0.0
        }
        for s in shelters if s.latitude and s.longitude
    ]

    # Include verified Rivne civil protection shelters from GeoJSON
    rivne_path = os.path.join(os.path.dirname(__file__), "static", "data", "rivne_shelters.geojson")
    if os.path.exists(rivne_path):
        try:
            with open(rivne_path, "r", encoding="utf-8") as rf:
                rdata = json.load(rf)
                for feat in rdata.get("features", []):
                    c = feat["geometry"]["coordinates"]
                    p = feat["properties"]
                    result.append({
                        "id": 10000 + p["id"],
                        "name": p["name"],
                        "address": p["address"],
                        "district": "Рівне",
                        "type": "radiation_shelter",
                        "capacity": p["capacity"],
                        "lat": float(c[1]),
                        "lon": float(c[0])
                    })
        except Exception as e:
            logger.warning(f"Error loading rivne_shelters.geojson: {e}")

    return {"shelters": result, "count": len(result)}

@app.get("/api/geoint/zones")
def get_danger_zones(hours: int = 72, oblast: Optional[str] = None, db: Session = Depends(get_db)):
    from worker.osint.geoint_engine import geoint_engine
    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    query = db.query(
        DetectedEvent.id,
        DetectedEvent.event_type,
        DetectedEvent.location_text,
        DetectedEvent.resonance_score,
        DetectedEvent.detected_at,
        DetectedEvent.is_fallback_geo,
        func.ST_Y(DetectedEvent.geom).label('lat'),
        func.ST_X(DetectedEvent.geom).label('lon')
    ).filter(
        DetectedEvent.geom.isnot(None),
        DetectedEvent.detected_at >= threshold,
        DetectedEvent.event_type.in_(['direct_strike', 'explosion', 'fire', 'destruction', 'casualties', 'armed_conflict'])
    )

    if oblast and oblast != "all" and oblast in OBLAST_BOUNDS:
        b = OBLAST_BOUNDS[oblast]
        query = query.filter(
            func.ST_Y(DetectedEvent.geom) >= b["min_lat"],
            func.ST_Y(DetectedEvent.geom) <= b["max_lat"],
            func.ST_X(DetectedEvent.geom) >= b["min_lon"],
            func.ST_X(DetectedEvent.geom) <= b["max_lon"]
        )
        if b.get("exclude_city"):
            cb = OBLAST_BOUNDS["kyiv_city"]
            query = query.filter(
                not_(and_(
                    func.ST_Y(DetectedEvent.geom) >= cb["min_lat"],
                    func.ST_Y(DetectedEvent.geom) <= cb["max_lat"],
                    func.ST_X(DetectedEvent.geom) >= cb["min_lon"],
                    func.ST_X(DetectedEvent.geom) <= cb["max_lon"]
                ))
            )
        if b.get("exclude_sevastopol"):
            sb = OBLAST_BOUNDS["sevastopol"]
            query = query.filter(
                not_(and_(
                    func.ST_Y(DetectedEvent.geom) >= sb["min_lat"],
                    func.ST_Y(DetectedEvent.geom) <= sb["max_lat"],
                    func.ST_X(DetectedEvent.geom) >= sb["min_lon"],
                    func.ST_X(DetectedEvent.geom) <= sb["max_lon"]
                ))
            )

    strikes = query.all()
    
    zones = []
    for st in strikes:
        if st.lat and st.lon:
            if st.is_fallback_geo:
                continue

            zone_data = geoint_engine.get_tactical_danger_zones(st.lat, st.lon, st.event_type, st.resonance_score)
            zone_data["event_id"] = st.id
            zone_data["location_text"] = st.location_text
            zone_data["detected_at"] = f"{st.detected_at.isoformat()}Z" if st.detected_at else None
            zones.append(zone_data)
            
    return zones

@app.get("/api/v1/radar/drones")
def get_radar_drones(
    request: Request = None,
    oblast: Optional[str] = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    from worker.osint.neptun_radar import get_live_radar_threats
    from worker.osint.launch_triangulation import estimate_launch_origin, project_forward_substation_threats
    from worker.geo_extractors.poi_matcher import POI_DATABASE

    is_authorized = is_tactical_authorized(request, token, db=db)
    client_ip = request.client.host if (request and getattr(request, "client", None)) else "127.0.0.1"
    check_rate_limit(client_ip, is_authenticated=is_authorized)

    threats_data = get_live_radar_threats(oblast=oblast)
    drones = threats_data.get("drones", [])
    inbound_drones = threats_data.get("inbound_drones", [])

    substations = None
    if is_authorized:
        substations = [
            {"name": name, "lat": data["lat"], "lon": data["lon"], "voltage": data.get("voltage", "110-750 kV")}
            for name, data in POI_DATABASE.items()
            if data.get("category") in ("substation", "energy", "fuel_depot", "defense_industry")
        ]

    for d in (drones + inbound_drones):
        lat = d.get("lat")
        lng = d.get("lng")
        heading = d.get("heading")
        speed = d.get("speed_kmh") or 185.0

        if is_authorized:
            # Operational / Military Contour: enriched with classified/restricted extensions
            if lat is not None and lng is not None and heading is not None and heading > 0 and substations:
                d["estimated_launch"] = estimate_launch_origin(lat, lng, heading, speed)
                d["projected_targets"] = project_forward_substation_threats(
                    lat, lng, heading, speed, substations, max_cone_deg=35.0, max_distance_km=75.0
                )
            else:
                d["estimated_launch"] = None
                d["projected_targets"] = []
        else:
            # Civilian Contour (Public OSINT): strictly 1:1 exact WGS-84 coordinates and kinematics,
            # but stripped of target substations, launch triangulation, internal EW profiles, and sensor nodes.
            d["projected_targets"] = []
            d["estimated_launch"] = None
            d["ew_profile"] = None
            d["sigint_corroboration"] = None
            d["corroborating_sensors"] = []

    contour_name = "restricted_operational" if is_authorized else "civilian"
    return {
        "contour": contour_name,
        "coordinates_fidelity": "1:1_exact_wgs84",
        "oblast": oblast,
        "drones": (drones + inbound_drones)
    }

@app.get("/api/v1/threats/enemy-facilities")
def get_enemy_facilities():
    from worker.osint.launch_triangulation import KNOWN_ENEMY_FACILITIES
    return {"facilities": KNOWN_ENEMY_FACILITIES, "count": len(KNOWN_ENEMY_FACILITIES)}

@app.get("/api/v1/threats/active-alerts")
def get_active_substation_threats(
    request: Request = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    if not is_tactical_authorized(request, token, db=db):
        return {
            "status": "restricted",
            "contour": "civilian",
            "message": "Substation target dispatch summary requires operational clearance authorized by Security Officer",
            "alerts": []
        }
    from worker.osint.threat_dispatcher import get_active_dispatch_summary
    res = get_active_dispatch_summary()
    res["contour"] = "restricted_operational"
    return res

@app.get("/api/v1/recon/tot-telecom")
def get_tot_telecom():
    from worker.osint.network_recon import get_tot_telecom_status
    return get_tot_telecom_status()

@app.get("/api/v1/radar/thermal")
def get_radar_thermal():
    from worker.osint.firms_viirs import fetch_ukraine_thermal_anomalies
    return fetch_ukraine_thermal_anomalies()

@app.get("/api/v1/radar/ew-interference")
def get_radar_ew_interference():
    from worker.sensors.sentinel_rfi import get_live_ew_interference
    return get_live_ew_interference()

@app.get("/api/v1/weather/wind-vectors")
def get_weather_wind_vectors(force_refresh: bool = False):
    from worker.osint.weather_vector import get_all_sector_winds
    return get_all_sector_winds(force_refresh=force_refresh)

@app.get("/api/v1/radar/aviation-intel")
def get_radar_aviation_intel(force_refresh: bool = False):
    from worker.osint.adsb_intel import get_aviation_intel_summary
    return get_aviation_intel_summary(force_refresh=force_refresh)

@app.get("/api/v1/radar/acoustic-tracks")
def get_radar_acoustic_tracks(
    request: Request = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    from worker.osint.acoustic_gateway import get_active_acoustic_hits
    hits = get_active_acoustic_hits()
    is_authorized = is_tactical_authorized(request, token, db=db)
    if not is_authorized:
        sanitized_hits = [
            {
                "lat": h.get("lat"),
                "lon": h.get("lon"),
                "confidence": h.get("confidence"),
                "time": h.get("time"),
                "label": "Акустична фіксація цілі"
            }
            for h in hits
        ]
        return {"hits": sanitized_hits, "count": len(sanitized_hits), "contour": "civilian"}
    return {"hits": hits, "count": len(hits), "contour": "restricted_operational"}

class AcousticHitPayload(BaseModel):
    lat: float
    lng: float
    sensor_id: str
    azimuth: Optional[float] = None
    snr_db: float = 18.5
    source: str = "Sky Fortress (Небесна Фортеця)"
    confidence: int = 88
    frequency_hz: float = 142.0

@app.post("/api/v1/telemetry/acoustic-hit")
def post_acoustic_hit(payload: AcousticHitPayload):
    from worker.osint.acoustic_gateway import record_acoustic_hit
    hit = record_acoustic_hit(
        lat=payload.lat,
        lng=payload.lng,
        sensor_id=payload.sensor_id,
        azimuth=payload.azimuth,
        snr_db=payload.snr_db,
        source=payload.source,
        confidence=payload.confidence,
        drone_frequency_hz=payload.frequency_hz,
    )
    return {"status": "ok", "hit": hit}

@app.get("/api/v1/radar/maritime-intel")
def get_radar_maritime_intel(force_refresh: bool = False):
    from worker.osint.maritime_ais import get_maritime_intel
    return get_maritime_intel(force_refresh=force_refresh)

@app.get("/api/v1/radar/sigint-emitters")
def get_radar_sigint_emitters():
    from worker.osint.sigint_bus import get_active_sigint_emitters
    emitters = get_active_sigint_emitters()
    return {"emitters": emitters, "count": len(emitters)}

class SigintHitPayload(BaseModel):
    frequency_mhz: float
    emitter_type: str = "JAMMER_5_8"
    lat: float
    lng: float
    power_dbm: float = 30.0
    source: str = "Field SDR Intercept"
    tactical_advisory: str = ""

@app.post("/api/v1/telemetry/sigint-hit")
def post_sigint_hit(
    payload: SigintHitPayload,
    request: Request = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    if not is_tactical_authorized(request, token, db=db):
        raise HTTPException(status_code=403, detail="Operational authorization required for SIGINT ingestion")
    from worker.osint.sigint_bus import record_sigint_hit
    hit = record_sigint_hit(
        frequency_mhz=payload.frequency_mhz,
        emitter_type=payload.emitter_type,
        lat=payload.lat,
        lng=payload.lng,
        power_dbm=payload.power_dbm,
        source=payload.source,
        tactical_advisory=payload.tactical_advisory,
    )
    return {"status": "ok", "hit": hit}

# --- Research / Simulation Endpoints (Role-based, no daily approval needed) ---

@app.get("/api/v1/research/simulations")
def get_research_simulations(
    request: Request = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(request=request, token=token, redis_client=redis_client)
    if user.role not in [RoleEnum.ANALYST_RESEARCH, RoleEnum.ADMIN, RoleEnum.SECURITY_OFFICER]:
        raise HTTPException(
            status_code=403,
            detail={"error": "ROLE_REQUIRED", "message": "Access requires analyst_research or admin role"}
        )
    from database.models import SimulationRun
    runs = db.query(SimulationRun).order_by(SimulationRun.created_at.desc()).limit(20).all()
    return {
        "contour": "research",
        "count": len(runs),
        "simulations": [
            {
                "run_id": r.run_id,
                "scenario_name": r.scenario_name,
                "targets_count": r.synthetic_targets_count,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in runs
        ]
    }

class ReplayPayload(BaseModel):
    incident_id: str
    speed_factor: Optional[float] = 1.0

@app.post("/api/v1/research/replay")
def create_research_replay(
    payload: ReplayPayload,
    request: Request = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(request=request, token=token, redis_client=redis_client)
    if user.role not in [RoleEnum.ANALYST_RESEARCH, RoleEnum.ADMIN, RoleEnum.SECURITY_OFFICER]:
        raise HTTPException(
            status_code=403,
            detail={"error": "ROLE_REQUIRED", "message": "Replay simulation requires analyst_research or admin role"}
        )
    import uuid
    import json
    from database.models import SimulationRun
    run_id = f"sim_{uuid.uuid4().hex[:12]}"

    sim = SimulationRun(
        run_id=run_id,
        scenario_name=f"Historical Replay Incident #{payload.incident_id}",
        parameters=json.dumps({"incident_id": payload.incident_id, "speed_factor": payload.speed_factor}),
        synthetic_targets_count=14,
        kalman_tuning_metrics=json.dumps({"synthetic_noise_std": 0.05, "speed_factor": payload.speed_factor}),
        created_by=user.user_id,
        created_at=datetime.datetime.utcnow()
    )
    db.add(sim)
    db.commit()

    return {
        "contour": "research",
        "status": "simulation_initialized",
        "run_id": run_id,
        "incident_id": payload.incident_id,
        "speed_factor": payload.speed_factor,
        "synthetic_targets_generated": 14,
        "mode": "historical_replay_archive_gt90d"
    }

@app.get("/api/v1/research/datasets")
def get_research_datasets(
    request: Request = None,
    token: Optional[str] = Query(None)
):
    user = get_current_user(request=request, token=token, redis_client=redis_client)
    if user.role not in [RoleEnum.ANALYST_RESEARCH, RoleEnum.ADMIN, RoleEnum.SECURITY_OFFICER]:
        raise HTTPException(
            status_code=403,
            detail={"error": "ROLE_REQUIRED", "message": "Datasets access requires analyst_research or admin role"}
        )
    return {
        "contour": "research",
        "datasets": [
            {"id": "ds_shahed_trajectory_2024", "records": 4820, "license": "Restricted Research (CC-BY-NC)"},
            {"id": "ds_kalman_acoustic_cross_v1", "records": 1240, "license": "Defense AI Benchmark"}
        ]
    }

# --- Access Request & Approval Endpoints (Security Officer Workflow) ---

class AccessRequestPayload(BaseModel):
    requested_resource: str = "tactical_events"
    target_sector: str = "all"
    justification: str
    user_email: Optional[str] = "operator@tactical.gov.ua"

def dispatch_telegram_approval_request(req_id: str, user_id: str, email: str, resource: str, sector: str, justification: str):
    bot_token = os.getenv("BOT_TOKEN")
    admin_id = os.getenv("ADMIN_ID")
    if not bot_token or not admin_id:
        return
    import requests
    text = (
        f"🚨 <b>ЗАПИТ НА ДОСТУП ДО ОПЕРАТИВНОГО КОНТУРУ (RESTRICTED)</b>\n\n"
        f"📋 <b>ID запиту:</b> <code>{req_id}</code>\n"
        f"👤 <b>Користувач / ID:</b> <code>{user_id}</code>\n"
        f"📧 <b>Email:</b> <code>{email}</code>\n"
        f"🎯 <b>Ресурс / Сектор:</b> <code>{resource}</code> / <code>{sector}</code>\n"
        f"📝 <b>Обґрунтування:</b> {justification}\n"
        f"⏳ <b>Термін дії:</b> 24 години (1 доба)\n\n"
        f"<i>Схваліть або відхиліть запит кнопками нижче:</i>"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ СХВАЛИТИ (24 год)", "callback_data": f"appr_perm:{req_id}:{sector}"},
                {"text": "❌ ВІДХИЛИТИ", "callback_data": f"rejc_perm:{req_id}:{sector}"}
            ]
        ]
    }
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": admin_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": reply_markup
            },
            timeout=4
        )
    except Exception as exc:
        logger.warning(f"Failed to dispatch access request to Telegram bot: {exc}")

@app.post("/api/v1/access/request")
def submit_access_request(
    payload: AccessRequestPayload,
    request: Request = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    import uuid
    user = get_current_user(request=request, token=token, redis_client=redis_client)
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    
    # Anomaly Detection: check for suspiciously short justifications
    if len(payload.justification.strip()) < 6:
        log_security_event(
            actor_id=user.user_id,
            actor_role=user.role.value,
            action="SECURITY_ANOMALY_DETECTED",
            resource_type=f"{payload.requested_resource}:{payload.target_sector}",
            decision="FLAGGED",
            reason="SUSPICIOUS_SHORT_JUSTIFICATION",
            client_ip=request.client.host if (request and getattr(request, "client", None)) else "127.0.0.1",
            db_session=db
        )

    from database.models import AccessRequest
    new_req = AccessRequest(
        request_id=req_id,
        user_id=user.user_id if user.user_id != "anonymous" else req_id,
        user_email=payload.user_email,
        requested_resource=payload.requested_resource,
        target_sector=payload.target_sector,
        justification=payload.justification,
        status="PENDING",
        requested_at=datetime.datetime.utcnow()
    )
    db.add(new_req)
    db.commit()

    # Forward interactive notification with 1-click approve buttons to Security Officer
    dispatch_telegram_approval_request(
        req_id=req_id,
        user_id=new_req.user_id,
        email=payload.user_email or "operator@tactical.gov.ua",
        resource=payload.requested_resource,
        sector=payload.target_sector,
        justification=payload.justification
    )

    return {
        "request_id": req_id,
        "status": "PENDING",
        "message": "Access request forwarded to Security Officer. Valid for 24h once approved.",
        "validity_ttl_hours": 24
    }

class AccessApprovalPayload(BaseModel):
    request_id: str
    decision: str = "APPROVED"
    hours: int = 24
    reason: Optional[str] = "Approved by Security Officer"

@app.post("/api/v1/access/approve")
def decide_access_request(
    payload: AccessApprovalPayload,
    request: Request = None,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(request=request, token=token, redis_client=redis_client)
    if user.role not in [RoleEnum.ADMIN, RoleEnum.SECURITY_OFFICER]:
        raise HTTPException(
            status_code=403,
            detail={"error": "OFFICER_REQUIRED", "message": "Only Security Officer can approve restricted access"}
        )
    
    import uuid
    import json
    from database.models import AccessRequest, AccessApproval
    from api.security.authz import log_security_event
    
    req = db.query(AccessRequest).filter(AccessRequest.request_id == payload.request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Access request not found")
    
    now = datetime.datetime.utcnow()
    hours = min(payload.hours, 24)
    req.status = payload.decision.upper()
    req.decided_at = now
    req.decided_by = user.user_id
    req.decision_reason = payload.reason
    
    if req.status == "APPROVED":
        appr_id = f"appr_{uuid.uuid4().hex[:8]}"
        until = now + datetime.timedelta(hours=hours)
        appr_row = AccessApproval(
            approval_id=appr_id,
            request_id=req.request_id,
            user_id=req.user_id,
            resource_type=req.requested_resource,
            geo_scope=req.target_sector,
            valid_from=now,
            valid_to=until,
            granted_by=user.user_id,
            created_at=now
        )
        db.add(appr_row)
        
        if redis_client:
            try:
                redis_client.setex(
                    f"tactical:approval:{req.user_id}:{req.target_sector}",
                    hours * 3600,
                    json.dumps({
                        "approved_by": user.user_id,
                        "approved_by_user": user.username,
                        "sector": req.target_sector,
                        "user_id": req.user_id,
                        "approved_at": now.isoformat(),
                        "ttl_hours": hours
                    })
                )
                redis_client.setex(
                    f"tactical:approval:{req.request_id}:{req.target_sector}",
                    hours * 3600,
                    json.dumps({
                        "approved_by": user.user_id,
                        "approved_by_user": user.username,
                        "sector": req.target_sector,
                        "user_id": req.user_id,
                        "approved_at": now.isoformat(),
                        "ttl_hours": hours
                    })
                )
            except Exception as r_err:
                logger.warning(f"Redis cache setex failed in decide_access_request: {r_err}")

        log_security_event(
            actor_id=user.user_id,
            actor_role=user.role.value,
            action="GRANT_APPROVAL",
            resource_type=f"{req.requested_resource}:{req.target_sector}",
            decision="ALLOWED",
            reason=f"Clearance approved for {req.user_id} for {hours}h",
            client_ip=request.client.host if (request and request.client) else "127.0.0.1",
            db_session=db
        )
    else:
        log_security_event(
            actor_id=user.user_id,
            actor_role=user.role.value,
            action="REJECT_APPROVAL",
            resource_type=f"{req.requested_resource}:{req.target_sector}",
            decision="DENIED",
            reason=f"Clearance rejected for {req.user_id}",
            client_ip=request.client.host if (request and request.client) else "127.0.0.1",
            db_session=db
        )

    db.commit()
    return {
        "request_id": req.request_id,
        "status": req.status,
        "decided_by": user.user_id,
        "validity_hours": hours if req.status == "APPROVED" else 0,
        "message": f"Request {req.status} successfully by Security Officer."
    }

# --- Break Glass Emergency Procedure ---

class BreakGlassPayload(BaseModel):
    break_glass_token: str
    justification: str
    operator_callsign: str
    hours: Optional[int] = 4

@app.post("/api/v1/access/break-glass")
def trigger_break_glass_emergency_access(
    payload: BreakGlassPayload,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Emergency Break-Glass Procedure:
    Used ONLY when the Security Officer is unreachable during a critical air defense emergency.
    Grants maximum 4-hour operational clearance and records an immutable emergency audit alert.
    """
    bg_expected = os.getenv("BREAK_GLASS_TOKEN", "bg_secret_emergency_override_2026")
    client_ip = request.client.host if (request and getattr(request, "client", None)) else "127.0.0.1"

    if not hmac.compare_digest(payload.break_glass_token, bg_expected):
        log_security_event(
            actor_id=f"callsign_{payload.operator_callsign}",
            actor_role="unknown",
            action="BREAK_GLASS_FAILED",
            resource_type="all:restricted_ops",
            decision="DENIED",
            reason="INVALID_BREAK_GLASS_TOKEN",
            client_ip=client_ip,
            db_session=db
        )
        raise HTTPException(status_code=403, detail="Invalid Break Glass Emergency Token")

    import uuid
    import json
    from database.models import AccessApproval

    hours = min(payload.hours or 4, 4)
    now = datetime.datetime.utcnow()
    until = now + datetime.timedelta(hours=hours)
    appr_id = f"bg_{uuid.uuid4().hex[:8]}"
    op_id = f"break_glass_{payload.operator_callsign}"

    appr_row = AccessApproval(
        approval_id=appr_id,
        request_id=f"break_glass_{payload.operator_callsign}",
        user_id=op_id,
        resource_type="tactical_events",
        geo_scope="all",
        valid_from=now,
        valid_to=until,
        granted_by="BREAK_GLASS_EMERGENCY_OVERRIDE",
        created_at=now
    )
    db.add(appr_row)

    if redis_client:
        try:
            redis_client.setex(
                f"tactical:approval:{op_id}:all",
                hours * 3600,
                json.dumps({
                    "approved_by": "BREAK_GLASS_EMERGENCY",
                    "approved_by_user": "emergency_officer",
                    "sector": "all",
                    "user_id": op_id,
                    "approved_at": now.isoformat(),
                    "ttl_hours": hours
                })
            )
        except Exception as err:
            logger.warning(f"Redis break glass setex error: {err}")

    log_security_event(
        actor_id=op_id,
        actor_role="security_officer",
        action="BREAK_GLASS_TRIGGERED",
        resource_type="all:restricted_ops",
        decision="ALLOWED",
        reason=f"Emergency Break Glass triggered by {payload.operator_callsign}: {payload.justification}",
        client_ip=client_ip,
        db_session=db
    )
    db.commit()

    return {
        "status": "EMERGENCY_CLEARANCE_GRANTED",
        "approval_id": appr_id,
        "operator_id": op_id,
        "validity_hours": hours,
        "expires_at": until.isoformat() + "Z",
        "notice": "This emergency session is monitored with CRITICAL audit priority."
    }

@app.get("/api/v1/alert/status")
def get_live_alert_status(oblast: Optional[str] = None):
    from bot.alert_monitor import get_current_kyiv_alert_status
    status = get_current_kyiv_alert_status(oblast=oblast)
    if isinstance(status.get("timestamp"), datetime.datetime):
        status["timestamp"] = status["timestamp"].isoformat()
    return status

@app.get("/api/v1/network/forward-graph")
def get_network_forward_graph(min_weight: int = 1, limit: int = 100, hours: int = 48, db: Session = Depends(get_db)):
    from database.repository import NetworkGraphRepository
    repo = NetworkGraphRepository(db)
    return repo.get_forward_graph(min_weight=min_weight, limit=limit, hours=hours)

@app.get("/api/v1/network/top-sources")
def get_network_top_sources(limit: int = 10, hours: int = 48, db: Session = Depends(get_db)):
    from database.repository import NetworkGraphRepository
    repo = NetworkGraphRepository(db)
    return repo.get_top_forward_sources(limit=limit, hours=hours)

@app.get("/api/v1/network/channel-lineage")
def get_network_channel_lineage(channel: str, db: Session = Depends(get_db)):
    from database.repository import NetworkGraphRepository
    repo = NetworkGraphRepository(db)
    return repo.get_channel_lineage(channel)

@app.get("/api/v1/infrastructure/critical")
def get_critical_infrastructure(oblast: Optional[str] = None):
    from worker.geo_extractors.poi_matcher import POI_DATABASE, INFRASTRUCTURE_CATEGORY_LABELS
    features = []
    critical_categories = {
        "substation", "energy", "fuel_depot", "telecom", "defense_industry",
        "railway", "airport", "bridge"
    }
    for name, data in POI_DATABASE.items():
        ob_val = data.get("oblast", "")
        if oblast and oblast != "all":
            if oblast == "kyiv":
                if ob_val not in ("kyiv_city", "kyiv_oblast", "kyiv"):
                    continue
            elif ob_val != oblast:
                continue

        cat = data.get("category", "")
        if cat in critical_categories and "lat" in data and "lon" in data:
            display_name = data.get("name", name)
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [data["lon"], data["lat"]]
                },
                "properties": {
                    "name": display_name,
                    "category": cat,
                    "category_label": INFRASTRUCTURE_CATEGORY_LABELS.get(cat, "Стратегічний об'єкт"),
                    "address": data.get("address", display_name),
                    "oblast": ob_val or "all"
                }
            })
    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features)
    }

@app.get("/api/v1/oblasts")
def get_supported_oblasts():
    """Returns official oblast registry with bounding centers and default zoom levels."""
    return {
        "oblasts": [
            {"code": "kyiv_city", "name": "м. Київ (Столиця)", "short_name": "м. Київ", "icon": "fa-city", "center": [50.4501, 30.5234], "zoom": 11},
            {"code": "kyiv_oblast", "name": "Київська область", "short_name": "Київщина", "icon": "fa-tree", "center": [50.3500, 30.2000], "zoom": 9},
            {"code": "vinnytsia", "name": "Вінницька область", "short_name": "Вінниччина", "icon": "fa-sun", "center": [49.2331, 28.4682], "zoom": 9},
            {"code": "volyn", "name": "Волинська область", "short_name": "Волинь", "icon": "fa-shield-halved", "center": [50.7472, 25.3254], "zoom": 9},
            {"code": "dnipropetrovsk", "name": "Дніпропетровська область", "short_name": "Дніпропетровщина", "icon": "fa-industry", "center": [48.4647, 35.0462], "zoom": 9},
            {"code": "donetsk", "name": "Донецька область", "short_name": "Донеччина", "icon": "fa-mountain", "center": [48.0159, 37.8029], "zoom": 9},
            {"code": "zhytomyr", "name": "Житомирська область", "short_name": "Житомирщина", "icon": "fa-leaf", "center": [50.2547, 28.6587], "zoom": 9},
            {"code": "zakarpattia", "name": "Закарпатська область", "short_name": "Закарпаття", "icon": "fa-mountain-sun", "center": [48.6208, 22.2879], "zoom": 9},
            {"code": "zaporizhzhia", "name": "Запорізька область", "short_name": "Запоріжжя", "icon": "fa-bolt-lightning", "center": [47.8388, 35.1396], "zoom": 9},
            {"code": "ivano_frankivsk", "name": "Івано-Франківська область", "short_name": "Прикарпаття", "icon": "fa-campground", "center": [48.9226, 24.7111], "zoom": 9},
            {"code": "kirovohrad", "name": "Кіровоградська область", "short_name": "Кіровоградщина", "icon": "fa-wheat-awn", "center": [48.5079, 32.2623], "zoom": 9},
            {"code": "luhansk", "name": "Луганська область", "short_name": "Луганщина", "icon": "fa-fire", "center": [48.5740, 39.3078], "zoom": 9},
            {"code": "lviv", "name": "Львівська область", "short_name": "Львівщина", "icon": "fa-landmark", "center": [49.8397, 24.0297], "zoom": 9},
            {"code": "mykolaiv", "name": "Миколаївська область", "short_name": "Миколаївщина", "icon": "fa-water", "center": [46.9750, 31.9946], "zoom": 9},
            {"code": "odesa", "name": "Одеська область", "short_name": "Одещина", "icon": "fa-anchor", "center": [46.4825, 30.7233], "zoom": 9},
            {"code": "poltava", "name": "Полтавська область", "short_name": "Полтавщина", "icon": "fa-seedling", "center": [49.5883, 34.5514], "zoom": 9},
            {"code": "rivne", "name": "Рівненська область", "short_name": "Рівненщина", "icon": "fa-feather", "center": [50.6199, 26.2516], "zoom": 9},
            {"code": "sumy", "name": "Сумська область", "short_name": "Сумщина", "icon": "fa-tower-observation", "center": [50.9077, 34.7981], "zoom": 9},
            {"code": "ternopil", "name": "Тернопільська область", "short_name": "Тернопільщина", "icon": "fa-castle", "center": [49.5535, 25.5948], "zoom": 9},
            {"code": "kharkiv", "name": "Харківська область", "short_name": "Харківщина", "icon": "fa-shield", "center": [49.9935, 36.2304], "zoom": 9},
            {"code": "kherson", "name": "Херсонська область", "short_name": "Херсонщина", "icon": "fa-ship", "center": [46.6354, 32.6169], "zoom": 9},
            {"code": "khmelnytskyi", "name": "Хмельницька область", "short_name": "Хмельниччина", "icon": "fa-shield-heart", "center": [49.4230, 26.9871], "zoom": 9},
            {"code": "cherkasy", "name": "Черкаська область", "short_name": "Черкащина", "icon": "fa-monument", "center": [49.4444, 32.0598], "zoom": 9},
            {"code": "chernivtsi", "name": "Чернівецька область", "short_name": "Буковина", "icon": "fa-archway", "center": [48.2921, 25.9358], "zoom": 9},
            {"code": "chernihiv", "name": "Чернігівська область", "short_name": "Чернігівщина", "icon": "fa-chess-rook", "center": [51.4982, 31.2893], "zoom": 9},
            {"code": "crimea", "name": "Автономна Республіка Крим", "short_name": "АР Крим", "icon": "fa-compass", "center": [44.9521, 34.1024], "zoom": 8},
            {"code": "sevastopol", "name": "м. Севастополь", "short_name": "Севастополь", "icon": "fa-life-ring", "center": [44.6167, 33.5254], "zoom": 11},
            {"code": "all", "name": "Вся Україна (Зведений огляд)", "short_name": "Вся Україна", "icon": "fa-globe", "center": [48.3794, 31.1656], "zoom": 6}
        ]
    }

@app.post("/api/v1/sync")
def trigger_sync():
    """Triggers background ingest sync across OSINT channels via Redis pub/sub."""
    try:
        redis_client.publish("sync_commands", "sync_now")
        return {"status": "success", "message": "Синхронізацію успішно ініційовано через Redis"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class DroneRaycastRequest(BaseModel):
    drone_lat: float
    drone_lon: float
    drone_alt_m: float
    gimbal_pitch_deg: float
    gimbal_yaw_deg: float
    hfov_deg: float = 84.0
    px_norm: float = 0.0
    py_norm: float = 0.0
    ground_alt_m: float = 120.0

@app.post("/api/v1/osint/drone-raycast")
def api_drone_raycast(req: DroneRaycastRequest):
    from worker.osint.drone_raycast import calculate_raycast_target
    res = calculate_raycast_target(
        drone_lat=req.drone_lat,
        drone_lon=req.drone_lon,
        drone_alt_m=req.drone_alt_m,
        gimbal_pitch_deg=req.gimbal_pitch_deg,
        gimbal_yaw_deg=req.gimbal_yaw_deg,
        hfov_deg=req.hfov_deg,
        px_norm=req.px_norm,
        py_norm=req.py_norm,
        ground_alt_m=req.ground_alt_m
    )
    return {
        "status": "success",
        "target_lat": res.target_lat,
        "target_lon": res.target_lon,
        "target_alt_m": res.target_alt_m,
        "ground_range_m": res.ground_range_m,
        "slant_range_m": res.slant_range_m,
        "confidence": res.confidence
    }

# ─── New Tactical C4ISR & Target Verification Endpoints ───

@app.get("/api/v1/threats/wez-envelopes")
def get_wez_envelopes(target_alt_m: float = 50.0):
    """Returns Weapon Engagement Zones (WEZ), terrain-aware radar horizon, and LOS domes (P3.1)."""
    from worker.osint.wez_envelopes import generate_wez_geojson
    return generate_wez_geojson(target_alt_m=target_alt_m)

class LobTriangulationRequest(BaseModel):
    bearings: List[Dict[str, Any]]

@app.post("/api/v1/geoint/lob-triangulate")
def api_lob_triangulate(req: LobTriangulationRequest):
    """Calculates multi-bearing LOB intersection point and CEP error ellipse."""
    from worker.osint.lob_triangulation import compute_lob_triangulation
    return compute_lob_triangulation(req.bearings)

@app.get("/api/v1/recon/cctv-cameras")
def get_cctv_cameras():
    """Returns optical CCTV reconnaissance and BDA verification nodes on TOT and frontline."""
    from worker.osint.cctv_registry import get_cctv_recon_nodes
    return get_cctv_recon_nodes()

@app.get("/api/v1/geoint/sun-shadow")
def get_sun_shadow_calculation(lat: float, lon: float, dt: Optional[str] = None):
    """Calculates solar azimuth, elevation, and shadow vector for photo/video chronolocation."""
    from worker.osint.geoint_engine import geoint_engine
    parsed_dt = None
    if dt:
        try:
            parsed_dt = datetime.datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            pass
    return geoint_engine.calculate_sun_position(lat, lon, parsed_dt)

# ── Tactical Cache Management & Telemetry Endpoints ──
@app.get("/api/v1/cache/metrics", tags=["Cache & Performance"])
def get_cache_metrics():
    """Returns real-time cache hit/miss rates, request counts, and connection health."""
    return cache_manager.get_metrics()

@app.post("/api/v1/cache/invalidate", tags=["Cache & Performance"])
def invalidate_cache(pattern: str = "api:v3:events:*"):
    """Non-blocking batch invalidator using SCAN + UNLINK for zero-lock flushing."""
    cleared = cache_manager.invalidate_pattern(pattern)
    return {"status": "ok", "pattern": pattern, "cleared_keys": cleared}

# ── Operations Health & Audit Endpoints (Master Plan Implementation) ──
from database.models import HITLFeedbackAudit

@app.get("/api/hitl/audit", tags=["HITL & Quality"])
def get_hitl_audit(limit: int = 50, db: Session = Depends(get_db)):
    """Returns persistent audit log of analyst HITL validations and Bayesian reputation shifts."""
    records = db.query(HITLFeedbackAudit).order_by(HITLFeedbackAudit.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "event_id": r.event_id,
            "analyst_id": r.analyst_id,
            "analyst_name": r.analyst_name,
            "decision": r.decision,
            "source_channel": r.source_channel,
            "reputation_before": r.reputation_before,
            "reputation_after": r.reputation_after,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "notes": r.notes,
        }
        for r in records
    ]

@app.get("/api/ops/health-summary", tags=["Operations & Health Gate"])
def get_ops_health_summary(db: Session = Depends(get_db)):
    """Comprehensive early-warning health check across Redis, PostGIS, NATS, and Data Lake."""
    health = {
        "status": "GREEN",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "components": {},
        "warnings": [],
    }

    # 1. Redis Check
    try:
        r = redis_client
        info_mem = r.info("memory")
        used_mem_bytes = info_mem.get("used_memory", 0)
        used_mem_mb = round(used_mem_bytes / (1024 * 1024), 2)
        q_len = r.llen("broadcast_queue")
        
        redis_status = "HEALTHY"
        if q_len > 100:
            health["warnings"].append(f"High Redis queue length: {q_len} tasks")
            redis_status = "WARNING"
            health["status"] = "AMBER"
        if used_mem_mb > 50:
            health["warnings"].append(f"High Redis memory usage: {used_mem_mb} MB")
            redis_status = "WARNING"
            health["status"] = "AMBER"

        health["components"]["redis"] = {
            "status": redis_status,
            "used_memory_mb": used_mem_mb,
            "queue_length": q_len,
        }
    except Exception as re:
        health["components"]["redis"] = {"status": "DOWN", "error": str(re)}
        health["warnings"].append(f"Redis unreachable: {re}")
        health["status"] = "RED"

    # 2. Database Check
    try:
        events_24h = db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        ).count()
        hitl_count = db.query(HITLFeedbackAudit).count()
        health["components"]["database"] = {
            "status": "HEALTHY",
            "events_last_24h": events_24h,
            "hitl_audit_records": hitl_count,
        }
    except Exception as dbe:
        health["components"]["database"] = {"status": "DOWN", "error": str(dbe)}
        health["warnings"].append(f"Database error: {dbe}")
        health["status"] = "RED"

    # 3. Data Lake Check
    try:
        from worker.data_lake import get_data_lake_stats
        lake_stats = get_data_lake_stats()
        health["components"]["data_lake"] = {
            "status": "HEALTHY",
            "total_partitions": lake_stats.get("total_files", 0),
            "total_size_kb": lake_stats.get("total_size_kb", 0),
            "total_records": lake_stats.get("total_records", 0),
        }
    except Exception as lke:
        health["components"]["data_lake"] = {"status": "DEGRADED", "error": str(lke)}

    return health

# MBTiles Offline Server
from api.mbtiles_server import router as mbtiles_router
app.include_router(mbtiles_router)

# OpenWebUI & Agent Tools
from api.routes.openwebui_tools import router as openwebui_tools_router
app.include_router(openwebui_tools_router)

# Serve the static HTML frontend with explicit no-cache headers to prevent stale mobile webview caches
from fastapi.responses import FileResponse

@app.get("/", include_in_schema=False)
async def serve_index():
    response = FileResponse("api/static/index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/graph_analysis.html", include_in_schema=False)
async def serve_graph_analysis_html():
    return FileResponse("api/static/graph_analysis.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate, max-age=0"})

@app.get("/graph_analysis", include_in_schema=False)
async def serve_graph_analysis():
    return FileResponse("api/static/graph_analysis.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate, max-age=0"})

@app.get("/graph", include_in_schema=False)
async def serve_graph():
    return FileResponse("api/static/graph_analysis.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate, max-age=0"})

@app.get("/api/graph_analysis.html", include_in_schema=False)
async def serve_api_graph_analysis_html():
    return FileResponse("api/static/graph_analysis.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate, max-age=0"})


app.mount("/api/static", StaticFiles(directory="api/static"), name="api_static_dir")
app.mount("/static", StaticFiles(directory="api/static"), name="static_dir")
app.mount("/", StaticFiles(directory="api/static", html=True), name="static")


