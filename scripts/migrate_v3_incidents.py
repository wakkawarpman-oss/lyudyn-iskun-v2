"""
Migration & Retroactive Incident Normalization Script (V3)
1. Ensures columns 'incident_id', 'significance_score', 'confidence_score', 'first_seen_at', 'last_seen_at' exist in PostgreSQL.
2. Retroactively resolves canonical toponyms, computes 2D scores, and assigns Incident IDs to all records.
"""
import os
import re
from datetime import datetime, timedelta
from sqlalchemy import text
from database.models import SessionLocal, DetectedEvent, engine
from worker.canonical_geo import resolve_canonical_toponym
from worker.scoring import calculate_significance_score, calculate_confidence_score, compute_composite_resonance
from geoalchemy2.elements import WKTElement

def migrate_and_normalize():
    print("🚀 Starting Database Schema Migration & Retroactive Normalization...")
    db = SessionLocal()
    
    # 1. Add columns if not exist
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        columns_to_add = [
            ("significance_score", "INTEGER DEFAULT 50"),
            ("confidence_score", "INTEGER DEFAULT 50"),
            ("incident_id", "VARCHAR(64)"),
            ("lifecycle_stage", "VARCHAR(32) DEFAULT 'DETECTED'"),
            ("first_seen_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("last_seen_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ]
        for col_name, col_def in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE detected_events ADD COLUMN IF NOT EXISTS {col_name} {col_def};")
                raw_conn.commit()
            except Exception as e:
                print(f"Column notice ({col_name}): {e}")
                raw_conn.rollback()
        cursor.close()
    finally:
        raw_conn.close()

    # 2. Fetch and normalize existing records
    events = db.query(DetectedEvent).order_by(DetectedEvent.detected_at.asc()).all()
    print(f"📊 Normalizing {len(events)} existing records...")

    for e in events:
        # Canonicalize location
        canon_loc, lat, lon = resolve_canonical_toponym(e.location_text)
        e.location_text = canon_loc
        if lat is not None and lon is not None and e.geom is None:
            e.geom = WKTElement(f"POINT({lon} {lat})", srid=4326)

        # 2D Scores
        sig = calculate_significance_score(e.event_type, e.has_media, e.message_text)
        conf = calculate_confidence_score(e.sources_list or e.source_channel, e.is_official, e.has_media)
        res = compute_composite_resonance(sig, conf)

        e.significance_score = sig
        e.confidence_score = conf
        e.resonance_score = res

        # Incident ID
        if not e.incident_id:
            loc_slug = re.sub(r'[^a-zA-Z0-9а-яА-ЯіїєґІЇЄҐ]', '', canon_loc)[:10].upper() or "KYIV"
            e.incident_id = f"INC-{(e.detected_at or datetime.utcnow()).strftime('%Y%m%d%H%M')}-{loc_slug}"

        if not e.first_seen_at:
            e.first_seen_at = e.detected_at or datetime.utcnow()
        if not e.last_seen_at:
            e.last_seen_at = e.detected_at or datetime.utcnow()

    db.commit()
    db.close()
    print("✅ Migration and retroactive incident normalization completed successfully!")

if __name__ == "__main__":
    migrate_and_normalize()
