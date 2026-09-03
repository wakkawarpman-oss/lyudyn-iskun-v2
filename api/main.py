from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models import SessionLocal, DetectedEvent
import datetime
import os
import json
import redis
import os

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


app = FastAPI(title="Людин Іскун V2 Dashboard")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/api/events")
def get_events(db: Session = Depends(get_db)):
    cached = get_cached("api:events")
    if cached:
        return cached

    threshold_24h = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
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
        DetectedEvent.sources_list,
        DetectedEvent.is_official,
        DetectedEvent.has_media,
        DetectedEvent.is_fallback_geo,
        DetectedEvent.message_text,
        func.ST_Y(DetectedEvent.geom).label('lat'),
        func.ST_X(DetectedEvent.geom).label('lon')
    ).filter(
        DetectedEvent.geom.isnot(None),
        DetectedEvent.source_channel.not_ilike('test%'),
        DetectedEvent.detected_at >= threshold_24h
    ).all()
    
    result = []
    for e in events:
        # is_fallback_geo (set by the worker's canonical-toponym resolver) is
        # the real signal for "we don't know where this is, defaulting to the
        # city center" — the old distance-to-Maidan-centroid heuristic hid
        # every genuine Maidan-area incident that didn't literally say
        # "майдан"/"хрещатик" in the text.
        if e.is_fallback_geo:
            continue

        if e.has_media:
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
            "detected_at": e.detected_at.isoformat(),
            "lat": e.lat,
            "lon": e.lon,
            "verification_status": e.verification_status or "UNVERIFIED_SINGLE_SOURCE",
            "sources_count": e.sources_count or 1,
            "sources_list": e.sources_list or e.source_channel,
            "is_official": e.is_official or False,
            "has_media": e.has_media or False,
            "geocoding_logic": logic
        })
    set_cached("api:events", result, ttl=30)
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
    
    res = {
        "total_events": total_events,
        "events_24h": events_24h,
        "avg_resonance": round(float(avg_resonance), 1),
        "categories": categories,
        "sources": sources
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
def get_danger_zones(db: Session = Depends(get_db)):
    from worker.osint.geoint_engine import geoint_engine
    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    strikes = db.query(
        DetectedEvent.id,
        DetectedEvent.event_type,
        DetectedEvent.location_text,
        DetectedEvent.resonance_score,
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
            # Exclude generic "Київ" fallback centroid from localized blast
            # circles — see the same is_fallback_geo check in /api/events.
            if st.is_fallback_geo:
                continue

            zone_data = geoint_engine.get_tactical_danger_zones(st.lat, st.lon, st.event_type, st.resonance_score)
            zone_data["event_id"] = st.id
            zone_data["location_text"] = st.location_text
            zones.append(zone_data)
            
    return zones

# Serve the static HTML frontend
app.mount("/", StaticFiles(directory="api/static", html=True), name="static")
