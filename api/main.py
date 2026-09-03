from typing import Optional, List, Dict
from fastapi import FastAPI, Depends
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, not_
from database.models import SessionLocal, DetectedEvent
import datetime
import os
import json
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.Redis.from_url(REDIS_URL)

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

def get_cached(key):
    try:
        val = redis_client.get(key)
        if val:
            return json.loads(val)
    except Exception:
        pass
    return None

def set_cached(key, val, ttl=60):
    try:
        redis_client.setex(key, ttl, json.dumps(val))
    except Exception:
        pass


from api.cot import router as cot_router

app = FastAPI(title="ОКІНТ-ПРО Dashboard")
app.include_router(cot_router)

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
        DetectedEvent.detected_at,
        DetectedEvent.verification_status,
        DetectedEvent.sources_count,
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

        # Tactical hygiene filter: Drop non-military city news (drugs, petty crime, traffic)
        if e.event_type in ('general_alert', 'alert') and not e.is_official:
            msg_lower = (e.message_text or '').lower()
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

        result.append({
            "id": e.id,
            "source_channel": e.source_channel,
            "message_id": e.message_id,
            "event_type": e.event_type,
            "location_text": e.location_text,
            "resonance_score": e.resonance_score,
            "detected_at": f"{e.detected_at.isoformat()}Z" if e.detected_at else None,
            "lat": e.lat,
            "lon": e.lon,
            "verification_status": e.verification_status or "UNVERIFIED_SINGLE_SOURCE",
            "sources_count": e.sources_count or 1,
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

@app.get("/api/shelters")
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
    
    return [
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
def get_radar_drones(oblast: Optional[str] = None):
    from worker.osint.neptun_radar import get_live_radar_threats
    return get_live_radar_threats(oblast=oblast)

@app.get("/api/v1/radar/thermal")
def get_radar_thermal():
    from worker.osint.firms_viirs import fetch_ukraine_thermal_anomalies
    return fetch_ukraine_thermal_anomalies()

@app.get("/api/v1/radar/ew-interference")
def get_radar_ew_interference():
    from worker.sensors.sentinel_rfi import get_live_ew_interference
    return get_live_ew_interference()

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

# Serve the static HTML frontend with explicit no-cache headers to prevent stale mobile webview caches
from fastapi.responses import FileResponse

@app.get("/", include_in_schema=False)
async def serve_index():
    response = FileResponse("api/static/index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

app.mount("/", StaticFiles(directory="api/static", html=True), name="static")
