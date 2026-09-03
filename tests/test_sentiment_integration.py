import json
from unittest.mock import patch, MagicMock

from worker.tasks import pipeline_extract, pipeline_geocode, pipeline_cluster_and_save


def _groq_response(content: dict):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": json.dumps(content)}}]}
    return resp


def _make_dual_mock(llm_reply: dict, sentiment_reply: dict):
    """The main LLM extraction call and the sentiment call both go through
    worker.llm_engine.requests.post — differentiate them by the system
    prompt, which sentiment.py builds with "Оціни тональність"."""
    def _side_effect(url, headers=None, json=None, timeout=None):
        prompt = json["messages"][0]["content"] if json else ""
        if "Оціни тональність" in prompt:
            return _groq_response(sentiment_reply)
        return _groq_response(llm_reply)
    return _side_effect


class _FakeQuery:
    def filter(self, *a, **kw):
        return self

    def order_by(self, *a, **kw):
        return self

    def first(self):
        return None


class _FakeSession:
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


def _run_pipeline(text: str, sentiment_reply: dict):
    payload = {
        "text": text,
        "channel": "@kyiv_alarm",
        "message_id": 1,
        "date": "2026-09-03T10:00:00",
        "has_media": False,
    }
    llm_reply = {
        "is_kyiv_region": True,
        "is_confirmed_incident": True,
        "event_type": "explosion",
        "location": "Оболонь",
        "short_summary": text[:80],
    }
    side_effect = _make_dual_mock(llm_reply, sentiment_reply)
    with patch("worker.llm_engine.requests.post", side_effect=side_effect):
        extracted = pipeline_extract(json.dumps(payload))
    geocoded = pipeline_geocode(extracted)
    fake_db = _FakeSession()
    with patch("worker.tasks.SessionLocal", return_value=fake_db):
        with patch("worker.llm_engine.requests.post", side_effect=side_effect):
            pipeline_cluster_and_save(geocoded)
    return extracted, fake_db.added[0]


def test_sentiment_is_computed_for_confirmed_incidents():
    extracted, _ = _run_pipeline(
        "Вибух на Оболоні, все палає!",
        {"score": 1, "label": "паніка"},
    )
    assert extracted["sentiment"] is not None
    assert extracted["sentiment"]["is_panic"] is True


def test_panic_boosts_significance_score():
    _, calm_event = _run_pipeline("Вибух на Оболоні", {"score": 4, "label": "спокійно"})
    _, panicked_event = _run_pipeline("Вибух на Оболоні", {"score": 1, "label": "паніка"})
    assert panicked_event.significance_score > calm_event.significance_score


def test_sentiment_not_computed_for_unconfirmed_alerts():
    """A radar_track (not is_confirmed_incident) shouldn't cost an extra
    Groq call — cost control per the plan."""
    payload = {
        "text": "Шахед курсом на Київ",
        "channel": "@kyiv_alarm",
        "message_id": 2,
        "date": "2026-09-03T10:00:00",
        "has_media": False,
    }
    llm_reply = {
        "is_kyiv_region": True,
        "is_confirmed_incident": False,
        "is_radar_track": True,
        "event_type": "radar_track",
        "location": "Київ",
    }
    calls = []

    def _side_effect(url, headers=None, json=None, timeout=None):
        calls.append(json["messages"][0]["content"])
        return _groq_response(llm_reply)

    with patch("worker.llm_engine.requests.post", side_effect=_side_effect):
        extracted = pipeline_extract(json.dumps(payload))

    assert extracted["skip"] is False
    assert extracted["sentiment"] is None
    assert len(calls) == 1  # only the main extraction call, no sentiment call
