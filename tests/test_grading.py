import pytest
from datetime import datetime, timezone, timedelta
from worker.grading import (
    Reliability, Credibility, IntelFact, fact_confidence,
    SourceReputation, fuse_epicenter, map_channel_to_admiralty
)


def test_reliability_and_credibility_enums():
    assert Reliability.A == 6
    assert Reliability.F == 1
    assert Credibility.CONFIRMED == 1
    assert Credibility.CANNOT_JUDGE == 6


def test_fact_confidence():
    f_high = IntelFact(
        source_id="radar_01",
        reliability=Reliability.A,
        credibility=Credibility.CONFIRMED,
        lat=50.45,
        lon=30.52,
        cep_m=50.0,
        observed_at=datetime.now(timezone.utc)
    )
    # Norm A: (6-1)/5 = 1.0; Norm Confirmed: 1 - (1-1)/5 = 1.0
    # base = 0.40 * 1.0 + 0.35 * 1.0 + 0.25 * 0.8 = 0.95
    conf = fact_confidence(f_high, reputation=0.8)
    assert conf == 0.95

    f_low = IntelFact(
        source_id="anon_tg",
        reliability=Reliability.E,
        credibility=Credibility.CANNOT_JUDGE,
        lat=50.45,
        lon=30.52,
        cep_m=1000.0,
        observed_at=datetime.now(timezone.utc)
    )
    conf_low = fact_confidence(f_low, reputation=0.2)
    assert conf_low < 0.20


def test_source_reputation_decay_and_updates():
    rep = SourceReputation(alpha=2.0, beta=2.0, decay_halflife_days=21.0)
    assert rep.reputation() == 0.5

    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    rep.update(confirmed=True, when=now)
    # alpha = 3.0, beta = 2.0 -> 3 / 5 = 0.60
    assert rep.reputation() == 0.60

    # 21 days later: alpha and beta should decay towards prior (2.0)
    later = now + timedelta(days=21)
    rep.update(confirmed=True, when=later)
    # Before update: alpha was 2 + (3-2)*0.5 = 2.5, beta was 2.0
    # After update: alpha = 3.5, beta = 2.0 -> 3.5 / 5.5 = 0.636
    assert 0.63 < rep.reputation() < 0.64


def test_source_reputation_serialization():
    rep = SourceReputation(alpha=5.0, beta=1.0)
    d = rep.to_dict()
    assert d["alpha"] == 5.0
    assert d["beta"] == 1.0
    assert d["reputation"] == round(5.0 / 6.0, 4)

    restored = SourceReputation.from_dict(d)
    assert restored.reputation() == rep.reputation()


def test_fuse_epicenter_multisource_and_conflict():
    now = datetime.now(timezone.utc)
    reps = {
        "radar": SourceReputation(5.0, 1.0),
        "tg_official": SourceReputation(4.0, 1.0),
        "tg_rumor": SourceReputation(2.0, 4.0),
    }

    f1 = IntelFact("radar", Reliability.A, Credibility.CONFIRMED, 50.4500, 30.5200, 50.0, now)
    f2 = IntelFact("tg_official", Reliability.B, Credibility.PROBABLY_TRUE, 50.4505, 30.5205, 100.0, now)

    fused = fuse_epicenter([f1, f2], reps)
    assert fused is not None
    assert 50.449 < fused["lat"] < 50.451
    assert 30.519 < fused["lon"] < 30.521
    assert fused["conflicts"] == 0
    assert "A" in fused["grade"]
    assert "⚠" not in fused["grade"]

    # Add conflicting high-confidence fact 5km away
    f_conflict = IntelFact("tg_official", Reliability.A, Credibility.CONFIRMED, 50.5000, 30.6000, 50.0, now)
    fused_conf = fuse_epicenter([f1, f2, f_conflict], reps)
    assert fused_conf is not None
    assert fused_conf["conflicts"] > 0
    assert "⚠" in fused_conf["grade"]


def test_map_channel_to_admiralty():
    rel_kmda, cred_kmda = map_channel_to_admiralty("KyivCityOfficial", is_official=True)
    assert rel_kmda == Reliability.A
    assert cred_kmda == Credibility.CONFIRMED

    rel_wm, cred_wm = map_channel_to_admiralty("war_monitor")
    assert rel_wm == Reliability.B
    assert cred_wm == Credibility.PROBABLY_TRUE

    rel_tg, cred_tg = map_channel_to_admiralty("kievreal1", has_media=True)
    assert rel_tg == Reliability.C
    assert cred_tg == Credibility.CONFIRMED


def test_pipeline_cluster_and_save_integrates_grading(monkeypatch):
    from worker.tasks import pipeline_cluster_and_save
    import json

    class FakeSession:
        def __init__(self):
            self.added = []
        def query(self, *a, **kw):
            return self
        def filter(self, *a, **kw):
            return self
        def order_by(self, *a, **kw):
            return self
        def first(self):
            return None
        def add(self, obj):
            self.added.append(obj)
        def commit(self):
            pass
        def execute(self, *a, **kw):
            pass
        def close(self):
            pass

    fake_session = FakeSession()
    monkeypatch.setattr("worker.tasks.SessionLocal", lambda: fake_session)

    test_data = {
        "payload": {
            "channel": "test_grading_ch",
            "message_id": 999901,
            "text": "Вибух у Дарницькому районі Києва",
            "has_media": True,
            "date": "2026-09-04T12:00:00"
        },
        "payload_str": json.dumps({"channel": "test_grading_ch", "message_id": 999901}),
        "llm_data": {
            "event_type": "explosion",
            "location": "Київ, Дарницький район",
            "short_summary": "Вибух у Дарницькому районі Києва"
        },
        "geom_wkt": "POINT(30.6500 50.4100)",
        "precision_tier": "district",
        "precision_radius_m": 1500
    }

    pipeline_cluster_and_save(test_data)
    assert len(fake_session.added) == 1
    ev = fake_session.added[0]
    assert ev.confidence_score >= 50
    assert ev.source_weight is not None
