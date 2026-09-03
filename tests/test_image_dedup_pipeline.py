"""Confirms image_phash actually flows end-to-end through the pipeline
(pipeline_extract -> pipeline_geocode -> pipeline_cluster_and_save), on top
of tests/test_image_dedup.py's isolated unit coverage of the hashing/matching
logic itself."""
import json
from unittest.mock import patch, MagicMock

from PIL import Image

from worker.tasks import pipeline_extract, pipeline_geocode, pipeline_cluster_and_save


def _mock_llm_response(json_body: str):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": json_body}}]}
    return resp


class _FakeQuery:
    """Empty-DB stand-in: the cluster-match lookup (.filter().first()/
    .filter().order_by().first()) and the phash lookup
    (.filter().order_by().limit().all()) both see nothing, so no cluster
    match and no duplicate photo are ever found."""
    def filter(self, *a, **kw):
        return self

    def order_by(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def first(self):
        return None

    def all(self):
        return []


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


def test_image_phash_is_computed_and_saved_on_the_event(tmp_path):
    media_path = str(tmp_path / "photo.jpg")
    Image.new("RGB", (100, 100), color=(50, 100, 150)).save(media_path)

    payload = {
        "text": "Вибух на Оболоні, є фото",
        "channel": "@kyiv_alarm",
        "message_id": 1,
        "date": "2026-09-03T10:00:00",
        "has_media": True,
        "media_path": media_path,
    }
    llm_reply = json.dumps({
        "is_kyiv_region": True,
        "is_confirmed_incident": True,
        "event_type": "explosion",
        "location": "Оболонь",
        "short_summary": "Вибух на Оболоні",
    })

    fake_db = _FakeSession()
    with patch("worker.tasks.SessionLocal", return_value=fake_db), \
         patch("worker.osint.exif_extractor.EXIFExtractor.extract", return_value={"has_gps": False}), \
         patch("worker.osint.ai_geolocation.ai_geo.analyze_image", return_value=None), \
         patch("worker.llm_engine.requests.post", return_value=_mock_llm_response(llm_reply)):
        extracted = pipeline_extract(json.dumps(payload))

    assert extracted["image_phash"]  # a real 16-char hex phash was computed

    geocoded = pipeline_geocode(extracted)

    with patch("worker.tasks.SessionLocal", return_value=fake_db):
        pipeline_cluster_and_save(geocoded)

    assert len(fake_db.added) == 1
    event = fake_db.added[0]
    assert event.image_phash == extracted["image_phash"]
    assert event.verification_status != "POSSIBLE_IPSO"  # no duplicate in an empty DB
