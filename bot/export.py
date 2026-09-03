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
            DetectedEvent.incident_id,
            DetectedEvent.detected_at,
            DetectedEvent.first_seen_at,
            DetectedEvent.last_seen_at,
            DetectedEvent.event_type,
            DetectedEvent.location_text,
            DetectedEvent.significance_score,
            DetectedEvent.confidence_score,
            DetectedEvent.resonance_score,
            DetectedEvent.source_channel,
            DetectedEvent.sources_list,
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
        
        # Write header with 2D verification & incident metrics
        writer.writerow([
            "ID", "Incident ID", "Detected At (UTC)", "First Seen", "Last Seen",
            "Event Type", "Location (Canonical)", "Significance Score (0-100)",
            "Confidence Score (0-100)", "Resonance Score (0-100)",
            "Primary Source", "Sources List", "Verification Status", 
            "Sources Count", "Latitude", "Longitude"
        ])
        
        for e in events:
            writer.writerow([
                e.id,
                e.incident_id or f"INC-{e.id}",
                e.detected_at.isoformat() if e.detected_at else "",
                e.first_seen_at.isoformat() if e.first_seen_at else (e.detected_at.isoformat() if e.detected_at else ""),
                e.last_seen_at.isoformat() if e.last_seen_at else (e.detected_at.isoformat() if e.detected_at else ""),
                e.event_type,
                e.location_text,
                e.significance_score or 50,
                e.confidence_score or 50,
                e.resonance_score or 50,
                e.source_channel,
                e.sources_list or e.source_channel,
                e.verification_status,
                e.sources_count,
                round(e.lat, 6) if e.lat else "",
                round(e.lon, 6) if e.lon else ""
            ])
            
        # Convert StringIO to BytesIO for Telegram
        bytes_io = io.BytesIO(output.getvalue().encode('utf-8'))
        bytes_io.name = f"Iskun_Incidents_{hours}h_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
        return bytes_io
        
    finally:
        db.close()
