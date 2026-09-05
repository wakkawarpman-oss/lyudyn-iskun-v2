"""
Test Suite for C4ISR V3.5 Multi-Domain Intelligence Subsystems.
- Maritime AIS Kalibr Salvo Reconnaissance
- 4/3 Effective Earth Radius & Terrain Canyon Masking
- Bayesian Belief Network (BBN) Probabilistic Threat Fusion
- SIGINT/ELINT Emitter Bus & Corroboration
- Neptun Radar Multi-INT Drone Integration
"""
import pytest
from unittest.mock import MagicMock, patch
import sys

# Ensure redis mock for local environment
sys.modules['redis'] = MagicMock()


def test_maritime_ais_salvo_intel():
    from worker.osint.maritime_ais import get_maritime_intel, BLACK_SEA_CARRIER_CATALOG, LAUNCH_SECTORS
    assert len(BLACK_SEA_CARRIER_CATALOG) >= 5
    assert len(LAUNCH_SECTORS) >= 4

    intel = get_maritime_intel(force_refresh=True)
    assert 'carriers' in intel
    assert 'total_salvo_potential' in intel
    assert 'carriers_at_sea_count' in intel
    assert intel['carriers_at_sea_count'] >= 1
    assert intel['total_salvo_potential'] >= 8
    assert intel['status'] in ('CRITICAL', 'ELEVATED', 'NORMAL')

    # Check carrier fields
    c0 = intel['carriers'][0]
    assert 'name' in c0
    assert 'vls_cells' in c0
    assert 'missile_type' in c0
    assert 'distance_to_odesa_km' in c0


def test_terrain_los_radio_horizon():
    from worker.osint.terrain_los import compute_radio_horizon_km, evaluate_terrain_masking

    # Horizon for 185m radar and 60m drone
    # 4.122 * (sqrt(185) + sqrt(60)) = 4.122 * (13.60 + 7.75) = 88.0 km
    h = compute_radio_horizon_km(185.0, 60.0)
    assert 85.0 <= h <= 91.0

    # 1. Point in Dnipro riverbed near Kaniv (49.75, 31.46) at low altitude (50m AGL)
    res_canyon = evaluate_terrain_masking(49.75, 31.46, target_alt_agl_m=50.0)
    assert res_canyon['is_terrain_masked'] is True
    assert res_canyon['masking_type'] == 'RIVER_CANYON'
    assert 'Дніпро' in res_canyon['directive']

    # 2. Point in open plains at 300m AGL
    res_clear = evaluate_terrain_masking(49.50, 31.00, target_alt_agl_m=300.0)
    assert res_clear['is_terrain_masked'] is False
    assert res_clear['masking_type'] == 'NONE'


def test_bayesian_confidence_fusion():
    from worker.scoring_bayesian import evaluate_bayesian_threat_confidence

    # Multi-sensor verified threat
    high_threat = evaluate_bayesian_threat_confidence({
        'has_radar': True,
        'doppler_match': True,
        'acoustic_count': 2,
        'adsb_mode': 'dark',
        'sigint_intercept': True,
        'osint_level': 'monitors'
    })
    assert high_threat['confidence_score'] >= 95
    assert high_threat['category'] == 'VERIFIED_THREAT'
    assert high_threat['false_positive_rate_pct'] < 2.0
    assert high_threat['active_corroborating_sources_count'] >= 4

    # Terrain masked target (lack of radar return MUST NOT severely penalize)
    masked_threat = evaluate_bayesian_threat_confidence({
        'has_radar': False,
        'is_terrain_masked': True,
        'acoustic_count': 2,
        'osint_level': 'monitors'
    })
    assert masked_threat['confidence_score'] >= 90
    assert masked_threat['category'] == 'VERIFIED_THREAT'

    # Civilian flight with active ADS-B transponder
    civilian = evaluate_bayesian_threat_confidence({
        'has_radar': True,
        'doppler_match': False,
        'adsb_mode': 'civilian'
    })
    assert civilian['confidence_score'] < 15
    assert civilian['category'] == 'BENIGN_OR_NOISE'


def test_sigint_bus_and_corroboration():
    from worker.osint.sigint_bus import get_active_sigint_emitters, record_sigint_hit, corroborate_sigint_near_target

    emitters = get_active_sigint_emitters()
    assert len(emitters) >= 3

    # Record a test hit
    hit = record_sigint_hit(
        frequency_mhz=5840.0,
        emitter_type='JAMMER_5_8',
        lat=48.25,
        lng=35.15,
        power_dbm=35.0,
        source='Test SDR Unit'
    )
    assert hit['type'] == 'JAMMER_5_8'
    assert hit['frequency_mhz'] == 5840.0

    # Corroborate target near this hit
    corrob = corroborate_sigint_near_target(48.26, 35.16, radius_km=15.0)
    assert corrob['sigint_active'] is True
    assert corrob['matching_emitters_count'] >= 1


def test_neptun_radar_drone_enrichment():
    from worker.osint.neptun_radar import get_live_radar_threats
    res = get_live_radar_threats()
    drones = res.get('drones', [])
    assert len(drones) > 0

    d0 = drones[0]
    assert 'terrain_masking' in d0
    assert 'sigint_corroboration' in d0
    assert 'bayesian_confidence' in d0
    assert d0['bayesian_confidence']['confidence_score'] > 0
    assert 'posterior_probability' in d0['bayesian_confidence']
