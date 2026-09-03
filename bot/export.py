import csv
import io
import datetime
from database.models import SessionLocal, DetectedEvent
from sqlalchemy import func

def generate_csv_export(hours: int = 24) -> io.BytesIO:
    """Generates a CSV file containing all events from the last N hours."""
    db = SessionLocal()
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        events = db.query(
            DetectedEvent.id,
            DetectedEvent.detected_at,
            DetectedEvent.event_type,
            DetectedEvent.location_text,
            DetectedEvent.resonance_score,
            DetectedEvent.source_channel,
            DetectedEvent.verification_status,
            DetectedEvent.sources_count,
            func.ST_Y(DetectedEvent.geom).label('lat'),
            func.ST_X(DetectedEvent.geom).label('lon')
        ).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ).order_by(DetectedEvent.detected_at.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            "ID", "Detected At (UTC)", "Event Type", "Location", 
            "Resonance Score", "Primary Source", "Verification Status", 
            "Sources Count", "Latitude", "Longitude"
        ])
        
        for e in events:
            writer.writerow([
                e.id,
                e.detected_at.isoformat() if e.detected_at else "",
                e.event_type,
                e.location_text,
                e.resonance_score,
                e.source_channel,
                e.verification_status,
                e.sources_count,
                round(e.lat, 6) if e.lat else "",
                round(e.lon, 6) if e.lon else ""
            ])
            
        # Convert StringIO to BytesIO for Telegram
        bytes_io = io.BytesIO(output.getvalue().encode('utf-8'))
        bytes_io.name = f"Iskun_Events_{hours}h_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
        return bytes_io
        
    finally:
        db.close()
