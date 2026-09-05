"""
Bayesian Belief Network (BBN) Multi-Domain Sensor Fusion Engine.

Computes exact posterior threat probabilities P(Threat | Evidence) using
recursive log-odds updating across multi-domain sensors:
- Radar Doppler & Kinematics (Neptun / 3D surveillance)
- Acoustic triangulation (Sky Fortress / Zvook acoustic network)
- SIGINT/ELINT RF Intercepts (5.8 GHz VTX jamming, 1.4 GHz mesh)
- ADS-B transponder presence / dark-aircraft state
- NASA FIRMS thermal anomaly correlation
- OSINT Tactical Telegram & Official Air Force reports
- Terrain LoS consideration (prevents false penalties when masked)
"""
import math
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Base Prior Probability of Threat in Active Air Defense Sector
PRIOR_THREAT_PROB = 0.20  # P(Threat) = 20% prior in operational theater

# Sensor Likelihood Ratios: LR = P(Evidence | Threat) / P(Evidence | ~Threat)
LIKELIHOOD_RATIOS = {
    'radar_doppler_match': 18.0,       # Speed 140-220 km/h, low RCS
    'radar_intermittent': 3.5,         # Intermittent radar blip
    'radar_masked_no_penalty': 1.05,   # Missing radar return caused by terrain masking (neutral)
    'radar_los_no_blip': 0.10,         # Clear LoS but completely absent radar return
    
    'acoustic_multi_sensor': 45.0,     # 2+ acoustic microphones confirm MD-550 142 Hz signature
    'acoustic_single_sensor': 8.5,     # 1 acoustic microphone confirmation
    'acoustic_none': 0.70,             # Acoustic grid coverage gap (slight penalty)
    
    'sigint_vtx_or_mesh': 25.0,        # 5.8 GHz VTX jammer or 1.4 GHz mesh RF intercept
    'sigint_none': 0.85,               # Radio silence mode (neutral/slight penalty)
    
    'adsb_civilian_squawk': 0.04,      # Active civilian ADS-B transponder (almost certainly not Shahed)
    'adsb_dark_aircraft': 6.5,         # Radar target without ADS-B transponder in restricted airspace
    
    'firms_thermal_hit': 7.5,          # VIIRS thermal hotspot along vector
    'firms_none': 0.95,                # No thermal anomaly (neutral)
    
    'osint_air_force_official': 50.0,  # Official Air Force AFU statement
    'osint_monitors_corrob': 12.0,     # 2+ tactical Telegram monitors
    'osint_single_mention': 2.5,       # 1 aggregator mention
    'osint_none': 0.75,                # No public OSINT yet
}


def prob_to_log_odds(p: float) -> float:
    p_safe = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p_safe / (1.0 - p_safe))


def log_odds_to_prob(log_odds: float) -> float:
    # Cap to prevent numerical overflow
    capped_lo = min(max(log_odds, -20.0), 20.0)
    odds = math.exp(capped_lo)
    return odds / (1.0 + odds)


def evaluate_bayesian_threat_confidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """
    Performs rigorous Bayesian update given observed multi-domain evidence.

    Expected evidence fields:
    - has_radar: bool
    - doppler_match: bool
    - is_terrain_masked: bool
    - acoustic_count: int (0, 1, 2+)
    - sigint_intercept: bool
    - adsb_mode: 'civilian' | 'dark' | 'none'
    - firms_thermal: bool
    - osint_level: 'official' | 'monitors' | 'single' | 'none'
    """
    current_log_odds = prob_to_log_odds(PRIOR_THREAT_PROB)
    breakdown = []
    active_sources = 0

    # 1. Radar Analysis
    has_radar = evidence.get('has_radar', False)
    doppler_match = evidence.get('doppler_match', False)
    is_masked = evidence.get('is_terrain_masked', False)

    if has_radar:
        active_sources += 1
        lr = LIKELIHOOD_RATIOS['radar_doppler_match'] if doppler_match else LIKELIHOOD_RATIOS['radar_intermittent']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'РЛС Нептун / Радар',
            'state': 'Доплер-сигнатура БПЛА' if doppler_match else 'Радарний контакт',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })
    else:
        if is_masked:
            # When masked in river canyon, absence of radar blip is EXPECTED and NOT penalizing!
            lr = LIKELIHOOD_RATIOS['radar_masked_no_penalty']
            current_log_odds += math.log(lr)
            breakdown.append({
                'sensor': 'РЛС Нептун / Радар',
                'state': 'В тіні рельєфу / Радіогоризонту (без штрафу)',
                'weight': round(lr, 2),
                'impact': 'NEUTRAL'
            })
        else:
            lr = LIKELIHOOD_RATIOS['radar_los_no_blip']
            current_log_odds += math.log(lr)
            breakdown.append({
                'sensor': 'РЛС Нептун / Радар',
                'state': 'Відсутність сигналу в зоні прямої видимості',
                'weight': round(lr, 2),
                'impact': 'NEGATIVE'
            })

    # 2. Acoustic Analysis
    ac_count = evidence.get('acoustic_count', 0)
    if ac_count >= 2:
        active_sources += 1
        lr = LIKELIHOOD_RATIOS['acoustic_multi_sensor']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'Акустична мережа (Zvook/Фортеця)',
            'state': f'{ac_count} мікрофонів підтвердили сигнатуру MD-550',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })
    elif ac_count == 1:
        active_sources += 1
        lr = LIKELIHOOD_RATIOS['acoustic_single_sensor']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'Акустична мережа (Zvook/Фортеця)',
            'state': '1 датчик зафіксував акустичний трек',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })
    else:
        lr = LIKELIHOOD_RATIOS['acoustic_none']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'Акустична мережа',
            'state': 'Поза зоною акустичних сенсорів',
            'weight': round(lr, 2),
            'impact': 'NEUTRAL'
        })

    # 3. SIGINT / RF Intercept
    sigint = evidence.get('sigint_intercept', False)
    if sigint:
        active_sources += 1
        lr = LIKELIHOOD_RATIOS['sigint_vtx_or_mesh']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'SIGINT / РЕР Пеленгація',
            'state': 'Зафіксовано 5.8 GHz VTX / 1.4 GHz телеметрію',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })
    else:
        lr = LIKELIHOOD_RATIOS['sigint_none']
        current_log_odds += math.log(lr)

    # 4. ADS-B
    adsb = evidence.get('adsb_mode', 'none')
    if adsb == 'civilian':
        lr = LIKELIHOOD_RATIOS['adsb_civilian_squawk']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'ADS-B Приймач',
            'state': 'Цивільний транспондер (висока ймовірність помилки класифікації)',
            'weight': round(lr, 2),
            'impact': 'NEGATIVE'
        })
    elif adsb == 'dark':
        active_sources += 1
        lr = LIKELIHOOD_RATIOS['adsb_dark_aircraft']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'ADS-B Приймач',
            'state': 'Dark Aircraft (відсутність транспондера в закритому просторі)',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })

    # 5. NASA FIRMS Thermal Hotspot
    firms = evidence.get('firms_thermal', False)
    if firms:
        active_sources += 1
        lr = LIKELIHOOD_RATIOS['firms_thermal_hit']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'NASA FIRMS VIIRS 375m',
            'state': 'Супутникова термоаномалія по курсу цілі',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })

    # 6. OSINT / Air Force reports
    osint_lvl = evidence.get('osint_level', 'none')
    if osint_lvl == 'official':
        active_sources += 1
        lr = LIKELIHOOD_RATIOS['osint_air_force_official']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'Повітряні Сили ЗСУ (Офіційно)',
            'state': 'Офіційне сповіщення про ворожий дрон',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })
    elif osint_lvl == 'monitors':
        active_sources += 1
        lr = LIKELIHOOD_RATIOS['osint_monitors_corrob']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'Моніторингові канали (Військові)',
            'state': 'Підтверджено 2+ військовими моніторами',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })
    elif osint_lvl == 'single':
        lr = LIKELIHOOD_RATIOS['osint_single_mention']
        current_log_odds += math.log(lr)
        breakdown.append({
            'sensor': 'OSINT Канал',
            'state': 'Поодиноке повідомлення в Telegram',
            'weight': round(lr, 1),
            'impact': 'POSITIVE'
        })

    posterior_p = log_odds_to_prob(current_log_odds)
    confidence_pct = int(round(posterior_p * 100))

    if posterior_p >= 0.90:
        category = 'VERIFIED_THREAT'
        cat_label = '🔴 ВЕРИФІКОВАНА ЗАГРОЗА (Multi-INT BBN)'
        fpr = round((1.0 - posterior_p) * 100.0, 2)
    elif posterior_p >= 0.75:
        category = 'HIGH_PROBABILITY'
        cat_label = '🟠 ВИСОКА ЙМОВІРНІСТЬ'
        fpr = round((1.0 - posterior_p) * 100.0, 2)
    elif posterior_p >= 0.40:
        category = 'UNCERTAIN'
        cat_label = '🟡 ПОТРЕБУЄ ДОРОЗВІДКИ'
        fpr = round((1.0 - posterior_p) * 100.0, 2)
    else:
        category = 'BENIGN_OR_NOISE'
        cat_label = '🟢 ХИБНЕ СПРАЦЮВАННЯ / ШУМ'
        fpr = 99.0

    return {
        'posterior_probability': round(posterior_p, 4),
        'confidence_score': confidence_pct,
        'category': category,
        'category_label': cat_label,
        'false_positive_rate_pct': fpr,
        'log_odds': round(current_log_odds, 2),
        'active_corroborating_sources_count': active_sources,
        'evidence_breakdown': breakdown
    }
