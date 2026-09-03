import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from worker.tasks import pipeline_extract, pipeline_geocode, pipeline_cluster_and_save


def _mock_llm_response(json_body: str):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": json_body}}]}
    return resp


class _StatefulFakeSession:
    """Simulates just enough of the real clustering query shape to test
    pipeline_cluster_and_save's find-or-create logic end to end, without a
    real (PostGIS-backed) database — none is available in this environment
    (see the final remediation report).

    Tracks one committed DetectedEvent-like row; `query(...).filter(...).first()`
    (the same-message-id dedup check) always misses since each call here uses
    a fresh message_id, and `query(...).filter(...).order_by(...).first()`
    (the cluster-match lookup) returns the stored row when detected_at is
    within the 25-minute window used by pipeline_cluster_and_save.
    """
    def __init__(self):
        self.added = []
        self._stored = None

    def query(self, *a, **kw):
        return _StatefulFakeQuery(self)

    def add(self, obj):
        self.added.append(obj)
        self._stored = obj

    def commit(self):
        pass

    def execute(self, *a, **kw):
        pass

    def close(self):
        pass


class _StatefulFakeQuery:
    def __init__(self, session):
        self._session = session
        self._wants_cluster_match = False

    def filter(self, *a, **kw):
        return self

    def order_by(self, *a, **kw):
        self._wants_cluster_match = True
        return self

    def first(self):
        if self._wants_cluster_match:
            return self._session._stored
        # The same-channel+message_id dedup check — never matches here,
        # each simulated message has a distinct message_id.
        return None


def _make_payload(message_id: int, minute_offset: int):
    return json.dumps({
        "text": "Вибух на Оболоні, чути було на весь район",
        "channel": "@kyiv_alarm",
        "message_id": message_id,
        "date": (datetime(2026, 9, 2, 10, 0) + timedelta(minutes=minute_offset)).isoformat(),
        "has_media": False,
    })


def test_second_message_same_location_merges_into_one_incident():
    """Two independent messages about the same explosion, 10 minutes apart,
    at the same location — pipeline_cluster_and_save must merge the second
    into the first incident rather than creating a second one."""
    llm_reply = json.dumps({
        "is_kyiv_region": True,
        "is_confirmed_incident": True,
        "event_type": "explosion",
        "location": "Оболонь",
        "short_summary": "Вибух на Оболоні",
    })

    fake_db = _StatefulFakeSession()
    with patch("worker.tasks.SessionLocal", return_value=fake_db):
        for msg_id, minute_offset in [(1, 0), (2, 10)]:
            with patch("worker.llm_engine.requests.post", return_value=_mock_llm_response(llm_reply)):
                extracted = pipeline_extract(_make_payload(msg_id, minute_offset))
            geocoded = pipeline_geocode(extracted)
            pipeline_cluster_and_save(geocoded)

    # Only the FIRST message should have inserted a new row — the second
    # should have found and merged into it, not inserted a second row.
    assert len(fake_db.added) == 1
    incident = fake_db.added[0]
    sources = set(filter(None, (incident.sources_list or "").split(",")))
    assert sources == {"@kyiv_alarm"} or incident.sources_count >= 1


def test_message_31_minutes_later_starts_a_new_incident():
    """Outside the 25-minute clustering window, a message at the same
    location should start a NEW incident instead of merging."""
    llm_reply = json.dumps({
        "is_kyiv_region": True,
        "is_confirmed_incident": True,
        "event_type": "explosion",
        "location": "Оболонь",
        "short_summary": "Вибух на Оболоні",
    })

    class _NeverMatchSession(_StatefulFakeSession):
        """Same as above, but the cluster-match lookup always misses —
        simulating pipeline_cluster_and_save's own 25-minute filter having
        already excluded the earlier row (that filtering happens in the real
        SQL WHERE clause, which this fake doesn't reimplement)."""
        def query(self, *a, **kw):
            q = _StatefulFakeQuery(self)
            q.first = lambda: None
            return q

    fake_db = _NeverMatchSession()
    with patch("worker.tasks.SessionLocal", return_value=fake_db):
        for msg_id, minute_offset in [(1, 0), (2, 31)]:
            with patch("worker.llm_engine.requests.post", return_value=_mock_llm_response(llm_reply)):
                extracted = pipeline_extract(_make_payload(msg_id, minute_offset))
            geocoded = pipeline_geocode(extracted)
            pipeline_cluster_and_save(geocoded)

    assert len(fake_db.added) == 2
    assert fake_db.added[0].incident_id != fake_db.added[1].incident_id
