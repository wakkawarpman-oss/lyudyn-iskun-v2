import io
import datetime
from database.models import SessionLocal, DetectedEvent
from sqlalchemy import func
from staticmap.staticmap import StaticMap, Marker

def generate_static_map(hours: int = 24) -> io.BytesIO:
    """Generates a static map image of recent events."""
    db = SessionLocal()
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        events = db.query(
            DetectedEvent.event_type,
            DetectedEvent.resonance_score,
            func.ST_Y(DetectedEvent.geom).label('lat'),
            func.ST_X(DetectedEvent.geom).label('lon')
        ).filter(
            DetectedEvent.geom.isnot(None),
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ).all()

        m = StaticMap(800, 600)
        
        # Color mapping based on event_type
        colors = {
            "explosion": "#FF0000",        # Red
            "direct_strike": "#8B0000",    # Dark Red
            "fire": "#FF4500",             # Orange Red
            "radar_track": "#FFA500",      # Orange
            "general_alert": "#FFD700",    # Gold
            "armed_conflict": "#800080"    # Purple
        }

        has_points = False
        for e in events:
            if e.lat and e.lon:
                # Exclude generic Kyiv fallback
                if abs(e.lat - 50.4500336) < 0.005 and abs(e.lon - 30.5241361) < 0.005:
                    continue
                    
                color = colors.get(e.event_type, "#0000FF") # Default blue
                size = 12 if (e.resonance_score or 0) > 80 else 8
                
                marker = Marker((e.lon, e.lat), color, size)
                m.add_marker(marker)
                has_points = True

        if not has_points:
            # If no points, just center on Kyiv
            m.add_marker(Marker((30.5241, 50.4500), "#000000", 2))

        # Render image
        img = m.render()
        
        bytes_io = io.BytesIO()
        img.save(bytes_io, format='PNG')
        bytes_io.name = "tactical_map.png"
        bytes_io.seek(0)
        
        return bytes_io
        
    finally:
        db.close()
