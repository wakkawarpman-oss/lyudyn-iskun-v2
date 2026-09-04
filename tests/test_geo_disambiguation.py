import pytest
from worker.geo_disambiguation import (
    disambiguate_toponym,
    detect_external_oblast,
    is_explicitly_kyiv_context
)
from worker.canonical_geo import resolve_canonical_toponym
from worker.llm_engine import rule_based_fallback_parser


def test_detect_external_oblast():
    assert detect_external_oblast("Обстріл Дніпровського району Херсона") == "kherson"
    assert detect_external_oblast("Вибухи у Харкові та передмісті") == "kharkiv"
    assert detect_external_oblast("Пуски ракет у бік Одеси та Чорноморська") == "odesa"
    assert detect_external_oblast("Атака на Синельникове та смт Васильківка") == "dnipropetrovsk"
    assert detect_external_oblast("Робота ППО у Києві поблизу Дарниці") is None


def test_is_explicitly_kyiv_context():
    assert is_explicitly_kyiv_context("Вибухи у Києві, мер повідомив про збиття") is True
    assert is_explicitly_kyiv_context("Тривога в столиці та області") is True
    assert is_explicitly_kyiv_context("Херсон під ударом артилерії") is False


def test_dniprovsky_district_kherson_vs_kyiv():
    t_kherson = "До лікарні звернулась жителька Дніпровського району Херсона, в будинок якої влучив снаряд."
    res_kh = disambiguate_toponym("Дніпровський район", full_text=t_kherson)
    assert res_kh["is_kyiv"] is False
    assert res_kh["oblast"] == "kherson"
    assert "Херсон" in res_kh["canonical"]
    assert res_kh["lat"] == 46.6611

    t_kyiv = "У Дніпровському районі столиці чутно вибухи, працює ППО."
    res_ky = disambiguate_toponym("Дніпровський район", full_text=t_kyiv)
    assert res_ky["is_kyiv"] is True
    assert res_ky["oblast"] == "kyiv_city"
    assert "Київ" in res_ky["canonical"]
    assert res_ky["lat"] == 50.4528


def test_vasylkiv_vs_vasylkivka():
    t_dnipro = "Ворог вдарив КАБом по селищу Васильківка Синельниківського району."
    res_dn = disambiguate_toponym("Васильків", full_text=t_dnipro)
    assert res_dn["is_kyiv"] is False
    assert res_dn["oblast"] == "dnipropetrovsk"
    assert "Дніпропетровська" in res_dn["canonical"]

    t_kyiv = "Збиття ворожого БпЛА поблизу міста Васильків на Київщині."
    res_ky = disambiguate_toponym("Васильків", full_text=t_kyiv)
    assert res_ky["is_kyiv"] is True
    assert res_ky["oblast"] == "kyiv_region"
    assert "Київська" in res_ky["canonical"]
    assert round(res_ky["lat"], 2) == 50.18


def test_shevchenkivsky_district_kharkiv_vs_kyiv():
    t_kharkiv = "Влучання у Шевченківському районі Харкова, горять авто."
    res_kh = disambiguate_toponym("Шевченківський район", full_text=t_kharkiv)
    assert res_kh["is_kyiv"] is False
    assert res_kh["oblast"] == "kharkiv"
    assert "Харків" in res_kh["canonical"]

    t_kyiv = "Падіння уламків у Шевченківському районі Києва, пошкоджено скління."
    res_ky = disambiguate_toponym("Шевченківський район", full_text=t_kyiv)
    assert res_ky["is_kyiv"] is True
    assert res_ky["oblast"] == "kyiv_city"
    assert "Київ" in res_ky["canonical"]


def test_canonical_geo_context_resolution():
    t_kherson = "Постраждала жінка у Дніпровському районі Херсона."
    canonical, lat, lon, is_fb = resolve_canonical_toponym("Дніпровський район", full_text=t_kherson)
    assert "Херсон" in canonical
    assert lat == 46.6611
    assert lon == 32.6582

    t_kyiv = "Тривога на лівому березі Києва, Дніпровський район."
    canonical_k, lat_k, lon_k, is_fb_k = resolve_canonical_toponym("Дніпровський район", full_text=t_kyiv)
    assert "Київ" in canonical_k
    assert round(lat_k, 2) == 50.45


def test_rule_based_fallback_parser_kherson():
    raw_text = "❗️До лікарні звернулась жителька Дніпровського району Херсона, в будинок якої цієї ночі влучив російський снаряд."
    res = rule_based_fallback_parser(raw_text)
    assert res["is_kyiv_region"] is False
    assert "Херсон" in res["location"]


def test_pipeline_extract_kherson_in_kyiv_channel(monkeypatch):
    """Verify that a message about Kherson sent via a Kyiv channel (@kyivoperat) is rejected."""
    from worker.tasks import pipeline_extract
    import json

    payload = {
        "channel": "kyivoperat",
        "text": "❗️До лікарні звернулась жителька Дніпровського району Херсона, в будинок якої цієї ночі влучив російський снаряд.",
        "media_path": None,
        "message_id": 999999
    }
    res = pipeline_extract(json.dumps(payload))
    assert res["skip"] is True
    assert res["reason"] == "not_kyiv"
    assert res["non_kyiv_oblast"] == "kherson"


def test_district_clash_clustering_guard():
    """Verify that events in Pechersk and Dniprovsky district never merge even within 0.08 deg."""
    from unittest.mock import patch, MagicMock
    from worker.tasks import pipeline_cluster_and_save
    from datetime import datetime
    import json

    class FakeStoredEvent:
        def __init__(self):
            self.id = 100
            self.location_text = "Печерський район, Київ"
            self.sources_list = "channel_pechersk"
            self.sources_count = 1
            self.source_channel = "channel_pechersk"
            self.is_official = False
            self.has_media = False
            self.last_seen_at = datetime.utcnow()
            self.event_type = "explosion"
            self.significance_score = 80
            self.confidence_score = 70
            self.resonance_score = 75

    fake_stored = FakeStoredEvent()

    class FakeClashSession:
        def __init__(self):
            self.added = []
            self._wants_cluster = False
        def query(self, *a, **kw):
            self._wants_cluster = False
            return self
        def filter(self, *a, **kw):
            return self
        def order_by(self, *a, **kw):
            self._wants_cluster = True
            return self
        def first(self):
            if self._wants_cluster:
                # Returns existing Pechersk event as a spatial candidate
                return fake_stored
            return None
        def execute(self, *a, **kw):
            pass
        def add(self, obj):
            self.added.append(obj)
        def commit(self):
            pass
        def close(self):
            pass

    fake_db = FakeClashSession()

    # Incoming event in Dniprovsky district
    ev2_data = {
        "skip": False,
        "payload": {
            "channel": "channel_dnipro",
            "message_id": 2002,
            "text": "Вибух у Дніпровському районі Києва.",
            "date": datetime.utcnow().isoformat(),
            "has_media": False
        },
        "llm_data": {
            "event_type": "explosion",
            "location": "Дніпровський район, Київ",
            "short_summary": "Вибух у Дніпровському районі"
        },
        "geom_wkt": "POINT(30.5982 50.4528)",
        "is_fallback_geo": False,
        "payload_str": json.dumps({"channel": "channel_dnipro", "message_id": 2002})
    }

    with patch("worker.tasks.SessionLocal", return_value=fake_db):
        pipeline_cluster_and_save(ev2_data)

    # Because Pechersk and Dniprovsky district clash, merger was prevented!
    # A new distinct event must be added to the database.
    assert len(fake_db.added) == 1
    assert "Дніпровський" in fake_db.added[0].location_text
