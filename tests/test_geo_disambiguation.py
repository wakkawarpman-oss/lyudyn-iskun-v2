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


def test_civilian_noise_road_repairs_rivne():
    """Verifies that the Rivne municipal road maintenance post is flagged as civilian noise."""
    from worker.geo_disambiguation import is_civilian_non_threat_noise, detect_channel_oblast
    from worker.tasks import pipeline_extract

    rivne_text = (
        "вул. Олекси Новака; вул. Коцюбинського; вул. Дворецький; вул. Дубенська; вул. Соборна; "
        "вул. Молодіжна та Богдана Хмельницького (Квасилів).\n"
        "Про це повідомили у Telegram в.о. міського голови Рівного Віктора Шакирзяна.\n"
        "На вулицях Кулика і Гудачека проводитимуть струменевий ремонт. Також на вулицях Соборній, "
        "Богдана Хмельницького, Базарній та Пересопницькій у Рівному ремонтуватимуть і прочищатимуть зливові каналізації.\n"
        "Механізоване прибирання листя заплановано на вул. Княгині Ольги, Олекси Новака.\n"
        "Врахуйте цю інформацію при плануванні маршруту поїздок."
    )

    assert is_civilian_non_threat_noise(rivne_text) is True
    assert detect_channel_oblast("suspilnerivne") == "rivne"

    payload = {
        "channel": "suspilnerivne",
        "message_id": 43726,
        "text": rivne_text,
        "media_path": None
    }
    from unittest.mock import patch
    import json
    with patch("worker.tasks.SessionLocal"):
        res = pipeline_extract(json.dumps(payload))
    assert res["skip"] is True
    assert res["reason"] in ["civilian_noise", "not_kyiv"]


def test_civilian_traffic_accident_not_radar_track():
    """Verifies that transport delay 'рух тролейбусів' does not trigger radar_track."""
    from worker.geo_disambiguation import is_civilian_non_threat_noise
    from worker.llm_engine import rule_based_fallback_parser

    traffic_text = "Через оце міні-ДТП на Рейгана-Червоної Калини зупинився рух тролейбусів та значне ускладнення руху."
    assert is_civilian_non_threat_noise(traffic_text) is True

    parsed = rule_based_fallback_parser(traffic_text)
    assert parsed.get("is_radar_track") is False
    assert parsed.get("event_type") == "civilian_noise"


def test_channel_oblast_resolver():
    """Verifies channel handle resolution to native administrative oblast."""
    from worker.geo_disambiguation import detect_channel_oblast

    assert detect_channel_oblast("suspilnerivne") == "rivne"
    assert detect_channel_oblast("suspilnelviv") == "lviv"
    assert detect_channel_oblast("dnepr_operativ") == "dnipropetrovsk"
    assert detect_channel_oblast("suspilnezaporizhzhya") == "zaporizhzhia"
    assert detect_channel_oblast("suspilnekherson") == "kherson"
    assert detect_channel_oblast("kievinfo_kyiv") is None  # Kyiv channel


def test_street_name_guard_does_not_trigger_kotsyubynske():
    """Verifies that 'вул. Коцюбинського' does not match the village of Kotsiubynske."""
    from worker.llm_engine import rule_based_fallback_parser

    text = "Проведення робіт на вул. Коцюбинського та вул. Соборна."
    parsed = rule_based_fallback_parser(text)
    # Must NOT be resolved as Kotsiubynske, Kyiv oblast
    assert parsed.get("location") != "Коцюбинське"


def test_real_military_air_defense_retains_priority():
    """Verifies that authentic air defense target tracking is NOT filtered out."""
    from worker.geo_disambiguation import is_civilian_non_threat_noise
    from worker.llm_engine import rule_based_fallback_parser

    threat_text = "Увага! Рух ударних БПЛА через Бровари курсом на Київ! Працює ППО!"
    assert is_civilian_non_threat_noise(threat_text) is False

    parsed = rule_based_fallback_parser(threat_text)
    assert parsed.get("is_kyiv_region") is True
    assert parsed.get("is_radar_track") is True or parsed.get("event_type") in ["radar_track", "air_defense"]

