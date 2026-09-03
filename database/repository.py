import datetime
from sqlalchemy import func
from database.models import SessionLocal, DetectedEvent
from sqlalchemy.orm import Session

class EventRepository:
    def __init__(self, db_session: Session = None):
        self.db = db_session or SessionLocal()
        
    def close(self):
        self.db.close()

    def get_events_last_n_hours(self, hours: int = 24, exclude_tests: bool = True):
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        query = self.db.query(DetectedEvent).filter(DetectedEvent.detected_at >= threshold)
        if exclude_tests:
            query = query.filter(DetectedEvent.source_channel.not_ilike('test%'))
        return query.order_by(DetectedEvent.detected_at.desc()).all()
        
    def get_event_stats_by_type(self, hours: int = 24):
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        return self.db.query(
            DetectedEvent.event_type, 
            func.count(DetectedEvent.id)
        ).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ).group_by(DetectedEvent.event_type).all()

    def get_avg_resonance(self, hours: int = 24) -> float:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        val = self.db.query(func.avg(DetectedEvent.resonance_score)).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ).scalar()
        return float(val) if val else 0.0

    def get_top_events_by_resonance(self, hours: int = 24, limit: int = 5):
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        return self.db.query(DetectedEvent).filter(
            DetectedEvent.detected_at >= threshold,
            DetectedEvent.source_channel.not_ilike('test%')
        ).order_by(DetectedEvent.resonance_score.desc().nullslast()).limit(limit).all()
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
