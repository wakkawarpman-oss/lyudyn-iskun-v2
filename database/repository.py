import datetime
from sqlalchemy import func
from database.models import SessionLocal, DetectedEvent, ChannelForwardEdge
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


class NetworkGraphRepository:
    def __init__(self, db_session: Session = None):
        self.db = db_session or SessionLocal()

    def close(self):
        self.db.close()

    def record_forward_edge(self, source_channel: str, target_channel: str, sample_text: str = None) -> ChannelForwardEdge:
        if not source_channel or not target_channel:
            return None
        s_chan = source_channel.strip().lstrip('@').lower()
        t_chan = target_channel.strip().lstrip('@').lower()
        if not s_chan or not t_chan or s_chan == t_chan:
            return None

        edge = self.db.query(ChannelForwardEdge).filter(
            ChannelForwardEdge.source_channel == s_chan,
            ChannelForwardEdge.target_channel == t_chan
        ).first()

        now = datetime.datetime.utcnow()
        if edge:
            edge.forward_count += 1
            edge.last_seen = now
            if sample_text:
                edge.sample_post_text = sample_text[:500]
        else:
            edge = ChannelForwardEdge(
                source_channel=s_chan,
                target_channel=t_chan,
                forward_count=1,
                first_seen=now,
                last_seen=now,
                sample_post_text=sample_text[:500] if sample_text else None
            )
            self.db.add(edge)

        try:
            self.db.commit()
            self.db.refresh(edge)
            return edge
        except Exception:
            self.db.rollback()
            return None

    def get_forward_graph(self, min_weight: int = 1, limit: int = 100, hours: int = 48) -> dict:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        edges_query = self.db.query(ChannelForwardEdge).filter(
            ChannelForwardEdge.last_seen >= threshold,
            ChannelForwardEdge.forward_count >= min_weight
        ).order_by(ChannelForwardEdge.forward_count.desc()).limit(limit).all()

        nodes_map = {}
        edges_list = []

        for e in edges_query:
            if e.source_channel not in nodes_map:
                nodes_map[e.source_channel] = {"id": e.source_channel, "label": f"@{e.source_channel}", "out_degree": 0, "in_degree": 0, "total_weight": 0}
            nodes_map[e.source_channel]["out_degree"] += 1
            nodes_map[e.source_channel]["total_weight"] += e.forward_count

            if e.target_channel not in nodes_map:
                nodes_map[e.target_channel] = {"id": e.target_channel, "label": f"@{e.target_channel}", "out_degree": 0, "in_degree": 0, "total_weight": 0}
            nodes_map[e.target_channel]["in_degree"] += 1
            nodes_map[e.target_channel]["total_weight"] += e.forward_count

            edges_list.append({
                "from": e.source_channel,
                "to": e.target_channel,
                "weight": e.forward_count,
                "last_seen": e.last_seen.isoformat() if e.last_seen else None
            })

        return {
            "nodes": list(nodes_map.values()),
            "edges": edges_list,
            "total_nodes": len(nodes_map),
            "total_edges": len(edges_list)
        }

    def get_top_forward_sources(self, limit: int = 10, hours: int = 48) -> list:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        results = self.db.query(
            ChannelForwardEdge.source_channel,
            func.sum(ChannelForwardEdge.forward_count).label("total_forwards"),
            func.count(ChannelForwardEdge.target_channel).label("amplifiers_count")
        ).filter(
            ChannelForwardEdge.last_seen >= threshold
        ).group_by(
            ChannelForwardEdge.source_channel
        ).order_by(
            func.sum(ChannelForwardEdge.forward_count).desc()
        ).limit(limit).all()

        return [
            {
                "source_channel": r[0],
                "total_forwards": int(r[1]) if r[1] is not None else 0,
                "amplifiers_count": int(r[2]) if r[2] is not None else 0
            }
            for r in results
        ]

    def get_channel_lineage(self, channel_name: str) -> dict:
        chan = channel_name.strip().lstrip('@').lower()
        out_edges = self.db.query(ChannelForwardEdge).filter(
            ChannelForwardEdge.source_channel == chan
        ).order_by(ChannelForwardEdge.forward_count.desc()).all()

        in_edges = self.db.query(ChannelForwardEdge).filter(
            ChannelForwardEdge.target_channel == chan
        ).order_by(ChannelForwardEdge.forward_count.desc()).all()

        return {
            "channel": chan,
            "amplifiers": [{"target": e.target_channel, "count": e.forward_count, "last_seen": e.last_seen.isoformat() if e.last_seen else None} for e in out_edges],
            "sources": [{"source": e.source_channel, "count": e.forward_count, "last_seen": e.last_seen.isoformat() if e.last_seen else None} for e in in_edges]
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
