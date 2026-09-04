"""
Sanitizes misclassified non-Kyiv events from Kyiv geographic frame in PostGIS.
Fixes homonym issues (e.g. Kherson Dniprovsky district placed in Kyiv Pechersk).
"""
import os
import sys
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import SessionLocal, DetectedEvent
from worker.geo_disambiguation import detect_external_oblast, is_explicitly_kyiv_context, HOMONYM_RESOLUTIONS
from worker.tasks import flush_api_caches

def sanitize_database():
    db = SessionLocal()
    print("🧹 Starting Database Sanity Audit for Regional Disambiguation...")

    try:
        events = db.query(
            DetectedEvent.id,
            DetectedEvent.source_channel,
            DetectedEvent.message_text,
            DetectedEvent.location_text
        ).all()
        print(f"📊 Auditing {len(events)} events in database...")

        updated_count = 0
        is_postgres = db.bind and "postgresql" in str(db.bind.url)

        for ev in events:
            txt = (ev.message_text or "") + " " + (ev.location_text or "")
            ch = (ev.source_channel or "").lower()

            # Check if channel is specifically non-Kyiv (e.g. khersonskaoda)
            is_external_channel = "kherson" in ch or "odesa" in ch or "kharkiv" in ch or "dnipro" in ch
            ext_ob = detect_external_oblast(txt)
            has_kyiv = is_explicitly_kyiv_context(txt)

            should_reclassify = False
            target_oblast = None

            if is_external_channel and not has_kyiv:
                should_reclassify = True
                target_oblast = "kherson" if "kherson" in ch else ext_ob
            elif ext_ob and not has_kyiv:
                should_reclassify = True
                target_oblast = ext_ob

            if should_reclassify and target_oblast:
                loc_low = (ev.location_text or "").lower()
                res = None
                for (h_key, ob_key), r_data in HOMONYM_RESOLUTIONS.items():
                    if (h_key in loc_low or h_key in txt.lower()) and ob_key == target_oblast:
                        res = r_data
                        break

                if res and res.get("lat") and res.get("lon"):
                    new_loc = res["canonical"]
                    new_lat, new_lon = res["lat"], res["lon"]
                else:
                    # Default oblast centroid
                    new_loc = f"{ev.location_text or 'Інцидент'} ({target_oblast.capitalize()})"
                    coords_map = {
                        "kherson": (46.6354, 32.6169),
                        "kharkiv": (49.9935, 36.2304),
                        "odesa": (46.4825, 30.7233),
                        "dnipropetrovsk": (48.4647, 35.0407),
                        "zaporizhzhia": (47.8388, 35.1396),
                        "sumy": (50.9077, 34.7981)
                    }
                    new_lat, new_lon = coords_map.get(target_oblast, (48.3794, 31.1656))

                if is_postgres:
                    from sqlalchemy import text
                    db.execute(
                        text("UPDATE detected_events SET location_text = :loc, geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), is_fallback_geo = false WHERE id = :id"),
                        {"loc": new_loc, "lon": new_lon, "lat": new_lat, "id": ev.id}
                    )
                else:
                    from database.models import DetectedEvent as DE
                    db.query(DE).filter(DE.id == ev.id).update({"location_text": new_loc})

                print(f"  [RECLASSIFIED #{ev.id}] '{ev.location_text}' -> '{new_loc}' ({new_lat}, {new_lon})")
                updated_count += 1

        db.commit()
        print(f"✅ Sanity audit complete: {updated_count} events reclassified.")
        flush_api_caches()
        print("🔄 Flushed API Redis caches.")
    except Exception as e:
        db.rollback()
        print(f"❌ Error during sanity audit: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    sanitize_database()
