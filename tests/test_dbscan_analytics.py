from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from worker.tasks import pipeline_cluster_and_save


def _make_event_data(channel="test_chan", message_id=1001, text="Повідомлення", event_type="radar_track",
                      location="Вишгород", geom_wkt="POINT(30.4900 50.5830)", is_fallback_geo=False,
                      msg_date_str=None):
    if not msg_date_str:
        msg_date_str = datetime.utcnow().isoformat()
    return {
        "payload": {
            "channel": channel,
            "message_id": message_id,
            "text": text,
            "date": msg_date_str,
            "has_media": False
        },
        "llm_data": {
            "event_type": event_type,
            "location": location,
            "short_summary": text
        },
        "geom_wkt": geom_wkt,
        "is_fallback_geo": is_fallback_geo,
        "osint_location": None,
        "payload_str": "{}"
    }


class FakeSpatialSession:
    """Mock DB Session supporting spatial matching and fallback logic."""
    def __init__(self):
        self.rows = []
        self.committed = False

    def query(self, model):
        return FakeSpatialQuery(self)

    def add(self, obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = len(self.rows) + 1
        self.rows.append(obj)

    def execute(self, *args, **kwargs):
        return MagicMock()

    def commit(self):
        self.committed = True

    def close(self):
        pass


class FakeSpatialQuery:
    def __init__(self, session, should_match_cluster=True):
        self.session = session
        self._wants_cluster_match = False
        self._should_match_cluster = should_match_cluster

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        self._wants_cluster_match = True
        return self

    def first(self):
        if self._wants_cluster_match and self._should_match_cluster:
            return self.session.rows[-1] if self.session.rows else None
        return None


def test_dbscan_spatial_clustering_adjacent_sector_within_008():
    """A.4 Contract: Adjacent locations within 0.08° and 30m window merge into one incident."""
    session = FakeSpatialSession()
    
    with patch("worker.tasks.SessionLocal", return_value=session):
        now = datetime.utcnow()
        # First event: Vyshhorod (50.5830, 30.4900)
        data1 = _make_event_data(
            channel="monitor1",
            message_id=1,
            location="Вишгород",
            geom_wkt="POINT(30.4900 50.5830)",
            msg_date_str=now.isoformat()
        )
        pipeline_cluster_and_save(data1)
        assert len(session.rows) == 1
        first_event = session.rows[0]
        assert first_event.sources_count == 1

        # Second event: Obolon (50.5050, 30.4980) ~0.078° diff, 5 min later
        data2 = _make_event_data(
            channel="monitor2",
            message_id=2,
            location="Оболонський район, Київ",
            geom_wkt="POINT(30.4980 50.5050)",
            msg_date_str=(now + timedelta(minutes=5)).isoformat()
        )
        pipeline_cluster_and_save(data2)
        
        # Should merge into the same incident, incrementing sources
        assert len(session.rows) == 1
        assert first_event.sources_count == 2
        assert "monitor1" in first_event.sources_list
        assert "monitor2" in first_event.sources_list


def test_dbscan_spatial_clustering_distant_locations_do_not_cluster():
    """A.4 Contract: Distant locations (> 0.08°) create separate incidents."""
    class DistantSession(FakeSpatialSession):
        def query(self, model):
            return FakeSpatialQuery(self, should_match_cluster=False)

    distant_session = DistantSession()
    with patch("worker.tasks.SessionLocal", return_value=distant_session):
        now = datetime.utcnow()
        # Event 1: Boryspil
        data1 = _make_event_data(
            channel="monitor1",
            message_id=10,
            location="Бориспіль",
            geom_wkt="POINT(30.9500 50.3500)",
            msg_date_str=now.isoformat()
        )
        pipeline_cluster_and_save(data1)
        assert len(distant_session.rows) == 1

        # Event 2: Brovary (> 18km away)
        data2 = _make_event_data(
            channel="monitor2",
            message_id=20,
            location="Бровари",
            geom_wkt="POINT(30.7900 50.5100)",
            msg_date_str=(now + timedelta(minutes=10)).isoformat()
        )
        pipeline_cluster_and_save(data2)
        assert len(distant_session.rows) == 2


def test_dbscan_fallback_to_text_match_when_no_geom():
    """A.4 Contract: Fallback to location_text match when geom is None."""
    session = FakeSpatialSession()
    with patch("worker.tasks.SessionLocal", return_value=session):
        now = datetime.utcnow()
        # Event 1 without geom
        data1 = _make_event_data(
            channel="monitor1",
            message_id=100,
            location="Шевченківський район",
            geom_wkt=None,
            msg_date_str=now.isoformat()
        )
        pipeline_cluster_and_save(data1)
        assert len(session.rows) == 1

        # Event 2 with same location_text and no geom (10 min later)
        data2 = _make_event_data(
            channel="monitor2",
            message_id=200,
            location="Шевченківський район",
            geom_wkt=None,
            msg_date_str=(now + timedelta(minutes=10)).isoformat()
        )
        pipeline_cluster_and_save(data2)
        assert len(session.rows) == 1
        assert session.rows[0].sources_count == 2
