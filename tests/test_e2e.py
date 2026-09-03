import json
from unittest.mock import patch, MagicMock

from worker.tasks import pipeline_extract, pipeline_geocode, pipeline_cluster_and_save


def _mock_llm_response(json_body: str):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": json_body}}]}
    return resp


class _FakeQuery:
    """Minimal stand-in for the one query shape pipeline_cluster_and_save
    needs: .filter(...).first() and .filter(...).order_by(...).first(), both
    returning None (an empty DB — no existing event, no cluster match)."""
    def filter(self, *a, **kw):
        return self

    def order_by(self, *a, **kw):
        return self

    def first(self):
        return None


class _FakeSession:
    """Records everything added instead of hitting a real (PostGIS-backed)
    database. There is no local Postgres/PostGIS available to run this
    against for real (see the final remediation report) — this verifies the
    pipeline's OWN extract -> geocode -> cluster decision logic produces a
    correctly-shaped DetectedEvent, not that it round-trips through real SQL.
    """
    def __init__(self):
        self.added = []

    def query(self, *a, **kw):
        return _FakeQuery()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def execute(self, *a, **kw):
        pass

    def close(self):
        pass


def test_full_pipeline_creates_one_incident():
    """A raw channel message flows through pipeline_extract -> pipeline_geocode
    -> pipeline_cluster_and_save and a single well-formed incident comes out,
    with a real (non-fallback) geocode for a message naming a specific
    district."""
    payload = {
        "text": "Вибух на Оболоні, чути було на весь район",
        "channel": "@kyiv_alarm",
        "message_id": 12345,
        "date": "2026-09-02T12:00:00",
        "has_media": False,
    }
    payload_str = json.dumps(payload)

    llm_reply = json.dumps({
        "is_kyiv_region": True,
        "is_confirmed_incident": True,
        "is_radar_track": False,
        "event_type": "explosion",
        "location": "Оболонь",
        "short_summary": "Вибух на Оболоні",
    })

    with patch("worker.llm_engine.requests.post", return_value=_mock_llm_response(llm_reply)):
        extracted = pipeline_extract(payload_str)

    assert extracted["skip"] is False

    geocoded = pipeline_geocode(extracted)
    assert geocoded["geom_wkt"] is not None
    assert geocoded["is_fallback_geo"] is False  # "Оболонь" is a real toponym match

    fake_db = _FakeSession()
    with patch("worker.tasks.SessionLocal", return_value=fake_db):
        pipeline_cluster_and_save(geocoded)

    assert len(fake_db.added) == 1
    event = fake_db.added[0]
    assert event.incident_id and event.incident_id.startswith("INC-")
    assert event.event_type == "explosion"
    assert event.is_fallback_geo is False


def test_pipeline_skips_non_kyiv_messages():
    """A message about a different city never reaches geocoding/clustering."""
    payload = {
        "text": "Вибух у Одесі, є постраждалі",
        "channel": "@some_random_channel",
        "message_id": 1,
        "date": "2026-09-02T12:00:00",
        "has_media": False,
    }
    llm_reply = json.dumps({
        "is_kyiv_region": False,
        "is_confirmed_incident": True,
        "event_type": "explosion",
        "location": "Одеса",
    })
    with patch("worker.llm_engine.requests.post", return_value=_mock_llm_response(llm_reply)):
        extracted = pipeline_extract(json.dumps(payload))

    assert extracted["skip"] is True
    assert extracted["reason"] == "not_kyiv"
