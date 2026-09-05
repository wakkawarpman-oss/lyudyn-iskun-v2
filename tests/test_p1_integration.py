"""
Test Suite for P1: Kalman q_eff(v) + BBN Temporal Decay + MNAR.
Інтегровані реальні OSINT-дані зі звітів Shahed-136/Герань-2.
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from worker.track_fusion import (
    AERO_DB,
    AerodynamicEnvelope,
    ETACone,
    KalmanTrackFilter,
    estimate_eta_cone,
    get_aero_profile,
)
from worker.scoring_bayesian import (
    Evidence,
    ThreatAssessment,
    decay_likelihood_ratio,
    fuse_multi_domain_evidence,
    mnar_adjustment,
    format_threat_summary,
    SENSOR_TAU,
    BASE_LIKELIHOOD_RATIOS,
)


# ════════════════════════════════════════════════════════════════════════════
# Task 1: Aerodynamic Profiles & Kalman
# ════════════════════════════════════════════════════════════════════════════

class TestAerodynamicProfilesFromOSINT:
    """Перевірка профілів на основі реальних OSINT-даних."""

    def test_shahed136_params(self):
        aero = get_aero_profile("SHAHED_136")
        assert aero.v_stall_ms == 33.0
        assert aero.v_dive_ms == 75.0
        assert aero.threat_category == "UAV"
        assert aero.deployment_time_min == 25.0

    def test_geran2_has_higher_qmax_than_shahed(self):
        """Російська збірка на Алабузі має більшу варіативність (AlabugaLeaks)."""
        geran = get_aero_profile("GERAN_2")
        shahed = get_aero_profile("SHAHED_136")
        assert geran.q_max > shahed.q_max
        assert geran.q_base > shahed.q_base
        assert geran.deployment_time_min <= 30.0  # 20-30 хв за звітом

    def test_orlan10_recon_params(self):
        """Орлан-10: розвідувальний, повільний, низький шум (дані бортів 10253, 10258)."""
        aero = get_aero_profile("ORLAN_10")
        assert aero.v_cruise_ms == 28.0  # ~100 км/год
        assert aero.v_dive_ms == 45.0
        assert aero.q_max == 20.0
        assert aero.threat_category == "UAV"

    def test_iskander_ballistic_reference(self):
        """Іскандер-М — балістична ракета, надвисокі швидкості (для порівняння ETA)."""
        aero = get_aero_profile("ISKANDER_M")
        assert aero.threat_category == "BALLISTIC"
        assert aero.v_cruise_ms == 1800.0
        assert aero.q_max == 500.0

    def test_qeff_quadratic_shahed(self):
        aero = get_aero_profile("SHAHED_136")
        # q = 0.5 * (1 + 0.8 * (50/50)^2) = 0.9
        assert aero.effective_q(50.0) == pytest.approx(0.9, abs=0.001)
        # q = 0.5 * (1 + 0.8 * (75/50)^2) = 0.5 * (1 + 1.8) = 1.4
        assert aero.effective_q(75.0) == pytest.approx(1.4, abs=0.001)

    def test_qeff_saturates(self):
        aero = get_aero_profile("GERAN_2")
        assert aero.effective_q(10_000.0) == aero.q_max


class TestKalmanWithAeroClamping:
    """Інтеграція Kalman + аеродинамічні межі."""

    def test_geran2_clamp_at_dive_speed(self):
        kf = KalmanTrackFilter(dt=1.0, threat_type="GERAN_2")
        kf.kf.x = np.array([[0.0], [0.0], [200.0], [0.0]])  # 200 м/с — абсурд
        kf.predict()
        assert kf.kf.x[2, 0] == pytest.approx(75.0, abs=0.1)
        assert kf.state["aero_clamped"] is True

    def test_orlan10_clamp_low_speed(self):
        kf = KalmanTrackFilter(dt=1.0, threat_type="ORLAN_10")
        kf.kf.x = np.array([[0.0], [0.0], [5.0], [0.0]])  # нижче stall=15
        kf.predict()
        assert kf.kf.x[2, 0] == pytest.approx(15.0, abs=0.1)

    def test_q_matrix_scales_with_velocity(self):
        kf = KalmanTrackFilter(dt=1.0, threat_type="SHAHED_136")
        kf.kf.x = np.array([[0.0], [0.0], [0.0], [0.0]])
        kf.predict()
        q_low = float(kf.kf.Q[2, 2])

        kf.kf.x = np.array([[0.0], [0.0], [55.0], [0.0]])
        kf.predict()
        q_high = float(kf.kf.Q[2, 2])

        assert q_high > q_low

    def test_state_includes_category(self):
        kf = KalmanTrackFilter(dt=1.0, threat_type="KH_101")
        kf.kf.x = np.array([[1000.0], [2000.0], [200.0], [50.0]])
        kf.predict()
        assert kf.state["threat_category"] == "CRUISE_MISSILE"


class TestETACone:
    """Конус розсіювання для реальних сценаріїв."""

    def test_shahed_eta_to_power_station(self):
        """ETA Шахеда до підстанції 750 кВ на відстані 55 км."""
        state = {"v_ms": 55.0}
        cone = estimate_eta_cone(state, 55_000, "SHAHED_136")
        # 55 км / 55 м/с = 1000 с ≈ 16.7 хв
        assert cone.eta_nom_s == pytest.approx(1000.0, abs=1.0)
        assert cone.eta_min_s < cone.eta_nom_s < cone.eta_max_s
        assert 0 < cone.theta_cone_deg <= 45.0
        assert len(cone.polygons) == 3

    def test_iskander_very_fast_eta(self):
        """Іскандер-М: 100 км пролітає за ~55 секунд."""
        state = {"v_ms": 1800.0}
        cone = estimate_eta_cone(state, 100_000, "ISKANDER_M")
        assert cone.eta_nom_s == pytest.approx(55.6, abs=0.5)
        assert cone.eta_max_s < 70.0  # навіть при мінімальній швидкості

    def test_orlan_slow_eta(self):
        """Орлан-10: 20 км розвідки = ~11 хвилин."""
        state = {"v_ms": 28.0}
        cone = estimate_eta_cone(state, 20_000, "ORLAN_10")
        assert cone.eta_nom_s == pytest.approx(714.0, abs=1.0)


# ════════════════════════════════════════════════════════════════════════════
# Task 2: BBN Temporal Decay
# ════════════════════════════════════════════════════════════════════════════

class TestTemporalDecay:
    """Експоненціальне згасання свідчень."""

    def test_no_decay_at_t0(self):
        lr = decay_likelihood_ratio(8.0, 0.0, 90.0)
        assert lr == pytest.approx(8.0, abs=0.001)

    def test_full_decay_asymptote(self):
        """При dt → ∞: LR → 1.0 (нейтрально)."""
        lr = decay_likelihood_ratio(8.0, 1_000_000.0, 90.0)
        assert lr == pytest.approx(1.0, abs=0.001)

    def test_radar_decay_at_90s(self):
        """При dt = τ: LR = 1 + (LR_0 - 1) / e ≈ 1 + 7/2.718 ≈ 3.58"""
        lr = decay_likelihood_ratio(8.0, 90.0, 90.0)
        expected = 1.0 + 7.0 * math.exp(-1.0)
        assert lr == pytest.approx(expected, abs=0.01)

    def test_osint_slower_decay(self):
        """OSINT має τ=300с — повільніше згасає."""
        lr_radar = decay_likelihood_ratio(3.0, 120.0, 90.0)
        lr_osint = decay_likelihood_ratio(3.0, 120.0, 300.0)
        assert lr_osint > lr_radar  # OSINT свіжеше


class TestMNAR:
    """Missing Not At Random — маскування рельєфом та низька висота."""

    def test_radar_missing_below_80m_is_neutral(self):
        """Shahed-136 летить на 50 м — відсутність РЛС = neutral, не штраф."""
        lr = mnar_adjustment("RADAR", altitude_m=50.0, terrain_masked=False, target_type="GERAN_2")
        assert lr is None

    def test_radar_missing_in_canyon_is_neutral(self):
        """Каньйон Дніпра — РЛС не бачить, але це очікувано."""
        lr = mnar_adjustment("RADAR", altitude_m=150.0, terrain_masked=True, target_type="GERAN_2")
        assert lr is None

    def test_sigint_masked_for_geran(self):
        """Герань-2 з Комета-М + FHSS — SIGINT може пропускати в каньйоні."""
        lr = mnar_adjustment("SIGINT", altitude_m=30.0, terrain_masked=True, target_type="GERAN_2")
        assert lr is None

    def test_acoustic_always_works(self):
        """Акустика (142 Гц MD-550) не залежить від висоти/рельєфу."""
        lr = mnar_adjustment("ACOUSTIC", altitude_m=20.0, terrain_masked=True, target_type="GERAN_2")
        assert lr is not None
        assert lr == BASE_LIKELIHOOD_RATIOS["ACOUSTIC"]

    def test_radar_clear_sky_normal(self):
        """Якщо ціль високо і без маскування — РЛС мав би бачити."""
        lr = mnar_adjustment("RADAR", altitude_m=200.0, terrain_masked=False, target_type="GERAN_2")
        assert lr is not None
        assert lr == BASE_LIKELIHOOD_RATIOS["RADAR"]


class TestBBNFusion:
    """Інтеграційні тести повного пайплайну BBN."""

    def test_single_fresh_radar_high_confidence(self):
        now = datetime.utcnow()
        ev = Evidence("RADAR", now, 8.0, altitude_m=500.0, terrain_masked=False)
        result = fuse_multi_domain_evidence([ev], current_time=now)
        assert result.threat_probability > 0.85
        assert result.confidence_label == "HIGH"
        assert "RADAR" in result.contributing_sensors

    def test_radar_missing_due_to_mnar_not_penalized(self):
        """Shahed летить у каньйоні — РЛС мовчить, але confidence не падає до нуля."""
        now = datetime.utcnow()
        ev_radar = Evidence("RADAR", now, 8.0, altitude_m=30.0, terrain_masked=True, target_type="GERAN_2")
        ev_acoustic = Evidence("ACOUSTIC", now, 4.0, altitude_m=30.0, terrain_masked=True, target_type="GERAN_2")

        result = fuse_multi_domain_evidence([ev_radar, ev_acoustic], current_time=now)
        # РЛС виключено через MNAR, але акустика дає сигнал
        assert "RADAR" in result.mnar_sensors
        assert "ACOUSTIC" in result.contributing_sensors
        assert result.threat_probability > 0.7  # акустика достатньо сильна

    def test_decayed_osint_reduces_confidence(self):
        """OSINT за 10 хвилин тому суттєво втрачає вагу (τ=300с)."""
        now = datetime.utcnow()
        ev = Evidence("OSINT", now - timedelta(seconds=600), 3.0)
        result = fuse_multi_domain_evidence([ev], current_time=now)
        # LR_decayed = 1 + 2 * exp(-2) ≈ 1.27
        assert result.threat_probability < 0.6
        assert "OSINT" in result.decayed_sensors

    def test_multi_sensor_fusion(self):
        """РЛС + Акустика + SIGINT = висока впевненість."""
        now = datetime.utcnow()
        evidence = [
            Evidence("RADAR", now, 8.0, altitude_m=300.0, terrain_masked=False),
            Evidence("ACOUSTIC", now - timedelta(seconds=10), 4.0),
            Evidence("SIGINT", now - timedelta(seconds=30), 6.0),
        ]
        result = fuse_multi_domain_evidence(evidence, current_time=now)
        assert result.threat_probability > 0.9
        assert result.confidence_label == "HIGH"
        assert len(result.contributing_sensors) >= 2

    def test_format_summary(self):
        now = datetime.utcnow()
        evidence = [
            Evidence("RADAR", now, 8.0),
            Evidence("ACOUSTIC", now - timedelta(seconds=100), 4.0),
        ]
        result = fuse_multi_domain_evidence(evidence, current_time=now)
        summary = format_threat_summary(result)
        assert "%" in summary
        assert "RADAR" in summary
        assert "ACOUSTIC(decayed)" in summary

    def test_no_evidence_is_stale(self):
        result = fuse_multi_domain_evidence([])
        assert result.confidence_label == "STALE"
        assert result.threat_probability == pytest.approx(0.5, abs=0.01)
