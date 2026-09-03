from fastapi import FastAPI, Depends
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import SessionLocal, DetectedEvent
import datetime
import os
import json
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.Redis.from_url(REDIS_URL)

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
def get_events(hours: int = 72, db: Session = Depends(get_db)):
    cache_key = f"api:events:{hours}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    events = db.query(
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
    ).order_by(DetectedEvent.detected_at.desc()).all()
    
    result = []
    for e in events:
        if e.is_fallback_geo:
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
def get_danger_zones(hours: int = 72, db: Session = Depends(get_db)):
    from worker.osint.geoint_engine import geoint_engine
    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    strikes = db.query(
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
    ).all()
    
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
def get_radar_drones():
    from worker.osint.neptun_radar import get_live_radar_threats
    return get_live_radar_threats()

@app.get("/api/v1/radar/thermal")
def get_radar_thermal():
    from worker.osint.firms_viirs import fetch_ukraine_thermal_anomalies
    return fetch_ukraine_thermal_anomalies()

@app.get("/api/v1/radar/ew-interference")
def get_radar_ew_interference():
    from worker.sensors.sentinel_rfi import get_live_ew_interference
    return get_live_ew_interference()

@app.get("/api/v1/alert/status")
def get_live_alert_status():
    from bot.alert_monitor import get_current_kyiv_alert_status
    status = get_current_kyiv_alert_status()
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
def get_critical_infrastructure():
    from worker.geo_extractors.poi_matcher import KYIV_POI_DATABASE, INFRASTRUCTURE_CATEGORY_LABELS
    features = []
    critical_categories = {
        "substation", "energy", "fuel_depot", "telecom", "defense_industry",
        "railway", "airport", "bridge"
    }
    for name, data in KYIV_POI_DATABASE.items():
        cat = data.get("category", "")
        if cat in critical_categories and "lat" in data and "lon" in data:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [data["lon"], data["lat"]]
                },
                "properties": {
                    "name": name,
                    "category": cat,
                    "category_label": INFRASTRUCTURE_CATEGORY_LABELS.get(cat, "Стратегічний об'єкт"),
                    "address": data.get("address", name)
                }
            })
    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features)
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

# Serve the static HTML frontend
app.mount("/", StaticFiles(directory="api/static", html=True), name="static")
