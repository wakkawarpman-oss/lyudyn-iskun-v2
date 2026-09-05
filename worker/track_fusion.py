"""
OKINT-PRO · Kalman Track Fusion Engine (ENU, per-source R, OOSM Retrodiction, ETA Cone)
Local East-North-Up (ENU) coordinates tracking with Continuous White Noise Acceleration (CWNA)
process noise, aerodynamic envelope limits, out-of-sequence replay buffer, and sigma-dispersion ETA cones.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from filterpy.kalman import KalmanFilter
from worker.track_fusion_v2 import AeroLimits, KalmanTrackFilterV2

R_EARTH_M = 6371000.0

DEFAULT_SOURCE_SIGMA = {
    "adsb": 30.0,        # ADS-B transponder ~30m
    "radar": 50.0,       # Neptun radar track ~50m
    "cctv": 100.0,       # Municipal camera sightline ~100m
    "viirs": 375.0,      # VIIRS 375m thermal pixel
    "firms": 375.0,      # NASA FIRMS thermal anomaly
    "telegram": 500.0,   # Eye-witness channel report ~500m
    "osint": 500.0,      # General OSINT
    "default": 200.0     # Default fallback
}

THREAT_TYPE_Q_ACCEL = {
    "shahed_136": 8.0,
    "SHAHED_136": 8.0,
    "drone": 8.0,
    "DRONE": 8.0,
    "super_cam": 6.0,
    "SUPER_CAM": 6.0,
    "supercam": 6.0,
    "shahed_238": 18.0,
    "SHAHED_238": 18.0,
    "jet_drone": 18.0,
    "JET_DRONE": 18.0,
    "cruise_missile": 25.0,
    "CRUISE_MISSILE": 25.0,
    "kh_101": 25.0,
    "KH_101": 25.0,
    "kalibr": 25.0,
    "KALIBR": 25.0,
    "ballistic": 35.0,
    "BALLISTIC": 35.0,
    "iskander_m": 35.0,
    "ISKANDER_M": 35.0,
    "kab": 12.0,
    "kab_500": 12.0,
    "KAB_500": 12.0,
    "artillery": 4.0,
    "msta_s": 4.0,
    "MSTA_S": 4.0,
    "maritime": 2.0,
    "MARITIME": 2.0,
    "maritime_salvo": 2.0,
    "MARITIME_SALVO": 2.0,
    "default": 8.0
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Аеродинамічний профіль цілі (інтегровано з OSINT-даних)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AerodynamicEnvelope:
    """
    Фізичні межі планера та параметри процесного шуму.

    q_eff(v) = min(q_max, q_base * (1 + beta * (v / v_ref)^2))

    Джерела даних:
    - Shahed-136/Герань-2: витоки AlabugaLeaks, в/ч 20924, аеродром Кашан (Іран)
    - Орлан-10: перехоплені звіти 2КНМ ЛНР, бортові логи
    - Тахіон: дані 138-ї ОМСБр
    - КН-101: відкриті довідники тактико-технічних характеристик
    """
    v_stall_ms: float       # швидкість звалювання (мінімальна стійка), м/с
    v_dive_ms: float        # максимальна швидкість піке/набору, м/с
    v_cruise_ms: float      # типова крейсерська швидкість, м/с
    q_base: float = 0.5     # базовий рівень шуму при v=0
    q_max: float = 35.0     # насичення (ceil) шуму
    beta: float = 0.8       # коефіцієнт квадратичного члена
    v_ref_ms: float = 50.0  # референсна швидкість для нормалізації
    threat_category: str = "UAV"  # UAV, CRUISE_MISSILE, BALLISTIC
    deployment_time_min: float = 30.0  # хвилин на розгортання
    a_max_lateral_g: float = 2.5       # максимальне бічне перевантаження, g

    def effective_q(self, v_ms: float) -> float:
        """Квадратична модель q_eff з насиченням."""
        if v_ms <= 0:
            return self.q_base
        ratio = v_ms / self.v_ref_ms
        q = self.q_base * (1.0 + self.beta * ratio ** 2)
        return min(self.q_max, q)

    def clamp_velocity(self, v_ms: float) -> float:
        """Жорстке обмеження швидкості фізичними межами планера."""
        return max(self.v_stall_ms, min(self.v_dive_ms, v_ms))

    def clamp_kinematics(
        self,
        current_vx: float,
        current_vy: float,
        dt_sec: float = 1.0,
        target_vx: Optional[float] = None,
        target_vy: Optional[float] = None
    ) -> Tuple[float, float, bool]:
        """Обмежує вектор швидкості та кутову швидкість розвороту планера за a_max_lateral_g."""
        v_curr = math.hypot(current_vx, current_vy)
        h_curr = math.degrees(math.atan2(current_vy, current_vx)) % 360.0

        if target_vx is None or target_vy is None:
            v_clamped = self.clamp_velocity(v_curr) if v_curr > 0 else self.v_cruise_ms
            scale = v_clamped / v_curr if v_curr > 0 else 1.0
            return current_vx * scale, current_vy * scale, abs(v_clamped - v_curr) > 0.01

        v_targ = math.hypot(target_vx, target_vy)
        h_targ = math.degrees(math.atan2(target_vy, target_vx)) % 360.0

        v_targ_clamped = self.clamp_velocity(v_targ) if v_targ > 0 else self.v_cruise_ms
        eff_v = max(self.v_stall_ms, v_curr)
        a_max_ms2 = getattr(self, "a_max_lateral_g", 2.5) * 9.80665
        omega_max_rad = a_max_ms2 / eff_v
        max_d_heading = math.degrees(omega_max_rad * max(0.01, dt_sec))

        d_heading = ((h_targ - h_curr + 180.0) % 360.0) - 180.0
        clamped = False
        if abs(d_heading) > max_d_heading:
            clamped = True
            h_new = (h_curr + math.copysign(max_d_heading, d_heading)) % 360.0
        else:
            h_new = h_targ

        rad = math.radians(h_new)
        return v_targ_clamped * math.cos(rad), v_targ_clamped * math.sin(rad), (clamped or abs(v_targ_clamped - v_targ) > 0.01)


# Аеродинамічна база даних загроз — верифікована на OSINT-даних
AERO_DB: Dict[str, AerodynamicEnvelope] = {
    # Shahed-136 (іранський оригінал) — дані з навчальної бази Кашан, Іран
    "SHAHED_136": AerodynamicEnvelope(
        v_stall_ms=33.0,      # 120 км/год — мінімальна стійка
        v_dive_ms=75.0,       # 270 км/год — максимальне піке
        v_cruise_ms=55.0,     # ~198 км/год — крейсерська
        q_base=0.5,
        q_max=35.0,
        beta=0.8,
        v_ref_ms=50.0,
        threat_category="UAV",
        deployment_time_min=25.0,
    ),
    # Герань-2 (російська локалізація Shahed-136) — ОЕЗ Алабуга, ТОВ Альбатрос
    "GERAN_2": AerodynamicEnvelope(
        v_stall_ms=33.0,
        v_dive_ms=75.0,
        v_cruise_ms=55.0,
        q_base=0.6,          # вищий базовий шум через варіативність збірки
        q_max=40.0,
        beta=0.9,
        v_ref_ms=50.0,
        threat_category="UAV",
        deployment_time_min=20.0,
    ),
    # Shahed-238 — апгрейд з турбореактивним двигуном
    "SHAHED_238": AerodynamicEnvelope(
        v_stall_ms=70.0,      # 252 км/год
        v_dive_ms=190.0,      # 684 км/год
        v_cruise_ms=130.0,    # ~468 км/год
        q_base=1.0,
        q_max=50.0,
        beta=0.6,
        v_ref_ms=100.0,
        threat_category="UAV",
        deployment_time_min=30.0,
    ),
    # КН-101 — крилата ракета
    "KH_101": AerodynamicEnvelope(
        v_stall_ms=180.0,     # 648 км/год
        v_dive_ms=270.0,      # 972 км/год
        v_cruise_ms=220.0,    # ~792 км/год
        q_base=2.0,
        q_max=80.0,
        beta=0.4,
        v_ref_ms=200.0,
        threat_category="CRUISE_MISSILE",
        deployment_time_min=15.0,
    ),
    # Орлан-10 — розвідувальний БпЛА (дані бортів 10253, 10258)
    "ORLAN_10": AerodynamicEnvelope(
        v_stall_ms=15.0,      # ~54 км/год
        v_dive_ms=45.0,       # ~162 км/год
        v_cruise_ms=28.0,     # ~100 км/год
        q_base=0.3,
        q_max=20.0,
        beta=1.0,
        v_ref_ms=30.0,
        threat_category="UAV",
        deployment_time_min=10.0,
    ),
    # Тахіон — тактичний розвідувальний комплекс (138-я ОМСБр)
    "TACHION": AerodynamicEnvelope(
        v_stall_ms=12.0,
        v_dive_ms=35.0,
        v_cruise_ms=22.0,     # ~80 км/год
        q_base=0.25,
        q_max=15.0,
        beta=1.2,
        v_ref_ms=25.0,
        threat_category="UAV",
        deployment_time_min=8.0,
    ),
    # Іскандер-М — ОТРК
    "ISKANDER_M": AerodynamicEnvelope(
        v_stall_ms=1500.0,    # ~5400 км/год
        v_dive_ms=2100.0,     # ~7560 км/год
        v_cruise_ms=1800.0,   # ~6480 км/год
        q_base=10.0,
        q_max=500.0,
        beta=0.1,
        v_ref_ms=1800.0,
        threat_category="BALLISTIC",
        deployment_time_min=12.0,
    ),
    # GENERIC_UAV — запасний профіль
    "GENERIC_UAV": AerodynamicEnvelope(
        v_stall_ms=15.0,
        v_dive_ms=60.0,
        v_cruise_ms=30.0,
        q_base=0.5,
        q_max=35.0,
        beta=0.8,
        v_ref_ms=50.0,
        threat_category="UAV",
        deployment_time_min=30.0,
    ),
}

# Aliases
AERO_DB["DRONE"] = AERO_DB["GENERIC_UAV"]
AERO_DB["UAV"] = AERO_DB["GENERIC_UAV"]
AERO_DB["SUPERCAM"] = AERO_DB["ORLAN_10"]
AERO_DB["SUPER_CAM"] = AERO_DB["ORLAN_10"]
AERO_DB["CRUISE_MISSILE"] = AERO_DB["KH_101"]
AERO_DB["BALLISTIC"] = AERO_DB["ISKANDER_M"]


def get_aero_profile(threat_type: str) -> AerodynamicEnvelope:
    """Повертає аеродинамічний профіль за типом загрози."""
    if not threat_type:
        return AERO_DB["GENERIC_UAV"]
    key = threat_type.upper().replace("-", "_")
    return AERO_DB.get(key, AERO_DB["GENERIC_UAV"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. Геодезичні перетворення (WGS84 <-> Local ENU)
# ─────────────────────────────────────────────────────────────────────────────

def latlon_to_enu(lat: float, lon: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """Convert WGS84 (lat, lon) to local East-North-Up (meters) relative to (ref_lat, ref_lon)."""
    d_lat = math.radians(lat - ref_lat)
    d_lon = math.radians(lon - ref_lon)
    mean_lat = math.radians(ref_lat)
    north = d_lat * R_EARTH_M
    east = d_lon * R_EARTH_M * math.cos(mean_lat)
    return east, north


def enu_to_latlon(east: float, north: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """Convert local ENU (meters) back to WGS84 (lat, lon)."""
    mean_lat = math.radians(ref_lat)
    d_lat = north / R_EARTH_M
    d_lon = east / (R_EARTH_M * math.cos(mean_lat))
    lat = ref_lat + math.degrees(d_lat)
    lon = ref_lon + math.degrees(d_lon)
    return lat, lon


@dataclass
class MeasurementRecord:
    timestamp: float        # Unix epoch in seconds
    lat: float
    lon: float
    source_type: str        # radar | telegram | viirs | adsb | cctv
    source_id: str
    cep_m: float = 0.0


@dataclass
class TrackState:
    track_id: str
    ref_lat: float
    ref_lon: float
    t: float                 # Last updated epoch (seconds)
    # State: [e, n, ve, vn]
    x: List[float]
    # Covariance 4x4 flat list
    P: List[List[float]]
    n_updates: int = 0
    threat_type: str = "drone"

    @property
    def lat(self) -> float:
        lat, _ = enu_to_latlon(self.x[0], self.x[1], self.ref_lat, self.ref_lon)
        return round(lat, 6)

    @property
    def lon(self) -> float:
        _, lon = enu_to_latlon(self.x[0], self.x[1], self.ref_lat, self.ref_lon)
        return round(lon, 6)

    @property
    def speed_mps(self) -> float:
        return math.hypot(self.x[2], self.x[3])

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6

    @property
    def heading_deg(self) -> float:
        h = math.degrees(math.atan2(self.x[2], self.x[3]))
        return (h + 360.0) % 360.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. ETA Cone з аеродинамічними межами
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ETACone:
    eta_min_s: float
    eta_nom_s: float
    eta_max_s: float
    theta_cone_deg: float
    polygons: List[dict] = field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)


def estimate_eta_cone(
    state: dict,
    corridor_distance_m: float,
    threat_type: str = "GENERIC_UAV",
) -> ETACone:
    """
    Розрахунок конуса розсіювання та ETA до цілі на основі аеродинамічного профілю.

    - eta_nom:  відстань / поточна швидкість
    - eta_min:  відстань / v_dive (найшвидше можливе)
    - eta_max:  відстань / v_stall (найповільніше можливе)
    """
    if corridor_distance_m <= 0:
        return ETACone(0.0, 0.0, 0.0, 0.0, [])

    aero = get_aero_profile(threat_type)
    v_current = state.get("v_ms", 0.0)
    v_current = aero.clamp_velocity(v_current)

    q = aero.effective_q(v_current)
    theta_cone_deg = min(45.0, 5.0 + (q / aero.q_max) * 40.0)

    eta_nom = corridor_distance_m / v_current if v_current > 0 else float("inf")
    eta_min = corridor_distance_m / aero.v_dive_ms
    eta_max = corridor_distance_m / aero.v_stall_ms

    polygons = []
    for minutes in [5, 10, 15]:
        t = minutes * 60.0
        d_nom = v_current * t
        d_max = aero.v_dive_ms * t
        d_min = aero.v_stall_ms * t
        spread_m = math.tan(math.radians(theta_cone_deg)) * d_nom

        polygons.append({
            "time_min": minutes,
            "d_nom_m": round(d_nom, 0),
            "d_min_m": round(d_min, 0),
            "d_max_m": round(d_max, 0),
            "lateral_spread_m": round(spread_m, 0),
            "note": f"Reachable envelope at T+{minutes}min",
        })

    return ETACone(
        eta_min_s=round(eta_min, 1),
        eta_nom_s=round(eta_nom, 1),
        eta_max_s=round(eta_max, 1),
        theta_cone_deg=round(theta_cone_deg, 2),
        polygons=polygons,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Kalman CWNA з динамічним q_eff(v) та підтримкою обох інтерфейсів
# ─────────────────────────────────────────────────────────────────────────────

class KalmanTrackFilter:
    """
    Continuous-Discrete Kalman Filter in local ENU frame with
    Continuous White Noise Acceleration (CWNA), quadratic q_eff(v) process noise,
    aerodynamic limits clamping, and Out-Of-Sequence Measurement (OOSM) handling.
    """

    def __init__(
        self,
        q_accel: float = 8.0,
        max_history: int = 50,
        dt: float = 1.0,
        threat_type: str = "GENERIC_UAV",
        measure_noise_sd: float = 5.0,
        init_cov_sd: float = 100.0,
    ):
        self.q_accel = q_accel
        self.max_history = max_history
        self.dt = dt
        self.threat_type = threat_type
        self.aero = get_aero_profile(threat_type)

        # State: [x, y, vx, vy]^T via filterpy.kalman.KalmanFilter
        self.kf = KalmanFilter(dim_x=4, dim_z=2)
        self.kf.F = np.array([
            [1.0, 0.0,  dt,  0.0],
            [0.0, 1.0,  0.0,  dt ],
            [0.0, 0.0,  1.0, 0.0],
            [0.0, 0.0,  0.0, 1.0],
        ])
        self.kf.H = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ])
        self.kf.P *= init_cov_sd
        self.kf.R *= measure_noise_sd ** 2
        self.kf.Q = np.eye(4) * self.aero.q_base
        self._last_aero_clamped = False

    def _update_q_matrix(self, v_ms: float) -> np.ndarray:
        """Формує матрицю процесного шуму CWNA для заданого q_eff."""
        dt = self.dt
        q = self.aero.effective_q(v_ms)
        q_mat = np.array([
            [dt**4 / 4, 0.0,       dt**3 / 2, 0.0      ],
            [0.0,       dt**4 / 4, 0.0,       dt**3 / 2],
            [dt**3 / 2, 0.0,       dt**2,     0.0      ],
            [0.0,       dt**3 / 2, 0.0,       dt**2    ],
        ]) * q
        return q_mat

    def predict(self):
        """
        Крок передбачення з аеродинамічним клампінгом швидкості
        та оновленням Q відповідно до q_eff(v).
        """
        vx = float(self.kf.x[2, 0])
        vy = float(self.kf.x[3, 0])
        v_ms = math.hypot(vx, vy)

        v_clamped = self.aero.clamp_velocity(v_ms)
        if v_ms > 0 and abs(v_clamped - v_ms) > 0.01:
            scale = v_clamped / v_ms
            self.kf.x[2, 0] = vx * scale
            self.kf.x[3, 0] = vy * scale
            v_ms = v_clamped
            self._last_aero_clamped = True
        else:
            self._last_aero_clamped = False

        self.kf.Q = self._update_q_matrix(v_ms)
        self.kf.predict()

    def update(self, z: np.ndarray):
        """Крок оновлення по вимірюванню z = [x, y] із кінематичним клампінгом."""
        x_prev = float(self.kf.x[0, 0])
        y_prev = float(self.kf.x[1, 0])
        vx_prev = float(self.kf.x[2, 0])
        vy_prev = float(self.kf.x[3, 0])

        self.kf.update(z)

        vx_post = float(self.kf.x[2, 0])
        vy_post = float(self.kf.x[3, 0])

        dt = max(0.1, self.dt)
        meas_vx = (float(z[0, 0]) - x_prev) / dt
        meas_vy = (float(z[1, 0]) - y_prev) / dt

        if abs(vx_post - vx_prev) < 1e-4 and abs(vy_post - vy_prev) < 1e-4:
            alpha = 0.5
            target_vx = vx_prev + alpha * (meas_vx - vx_prev)
            target_vy = vy_prev + alpha * (meas_vy - vy_prev)
        else:
            target_vx = vx_post
            target_vy = vy_post

        vx_clamped, vy_clamped, was_clamped = self.aero.clamp_kinematics(
            current_vx=vx_prev,
            current_vy=vy_prev,
            dt_sec=dt,
            target_vx=target_vx,
            target_vy=target_vy
        )
        self.kf.x[2, 0] = vx_clamped
        self.kf.x[3, 0] = vy_clamped
        if was_clamped:
            self._last_aero_clamped = True

    @property
    def state(self) -> dict:
        """Фільтрований стан у зручному для downstream форматі."""
        x, y, vx, vy = self.kf.x.flatten()
        v_ms = math.hypot(vx, vy)
        heading = math.degrees(math.atan2(vy, vx)) % 360.0
        return {
            "x_m": float(x),
            "y_m": float(y),
            "vx_ms": float(vx),
            "vy_ms": float(vy),
            "v_ms": float(v_ms),
            "v_kmh": round(float(v_ms * 3.6), 1),
            "heading_deg": round(heading, 1),
            "q_eff": round(float(self.aero.effective_q(v_ms)), 3),
            "aero_clamped": getattr(self, "_last_aero_clamped", False) or bool(abs(v_ms - self.aero.clamp_velocity(v_ms)) > 0.01),
            "cov_trace": float(np.trace(self.kf.P)),
            "threat_category": self.aero.threat_category,
        }

    # ── Legacy / TrackState-based methods for radar fusion & downstream pipelines ──

    def init_track(self, track_id: str, lat: float, lon: float, t: float,
                   source_type: str = "radar", initial_heading_deg: Optional[float] = None,
                   initial_speed_mps: float = 45.0) -> Tuple[TrackState, List[MeasurementRecord]]:
        ref_lat, ref_lon = lat, lon
        e, n = 0.0, 0.0

        if initial_heading_deg is not None:
            rad = math.radians(initial_heading_deg)
            ve = initial_speed_mps * math.sin(rad)
            vn = initial_speed_mps * math.cos(rad)
        else:
            ve = 0.0
            vn = 0.0

        sigma_pos = DEFAULT_SOURCE_SIGMA.get(source_type, DEFAULT_SOURCE_SIGMA["default"])
        r_pos = sigma_pos ** 2
        r_vel = (20.0) ** 2

        P = [
            [r_pos, 0.0,   0.0,   0.0],
            [0.0,   r_pos, 0.0,   0.0],
            [0.0,   0.0,   r_vel, 0.0],
            [0.0,   0.0,   0.0,   r_vel]
        ]
        state = TrackState(
            track_id=track_id,
            ref_lat=ref_lat,
            ref_lon=ref_lon,
            t=t,
            x=[e, n, ve, vn],
            P=P,
            n_updates=1
        )
        meas_hist = [MeasurementRecord(timestamp=t, lat=lat, lon=lon, source_type=source_type, source_id="init")]
        return state, meas_hist

    def _predict(self, x: List[float], P: List[List[float]], dt: float, q_val: Optional[float] = None) -> Tuple[List[float], List[List[float]]]:
        if dt <= 0:
            return [v for v in x], [[c for c in row] for row in P]

        x_pred = [
            x[0] + dt * x[2],
            x[1] + dt * x[3],
            x[2],
            x[3]
        ]

        q_eff = q_val if q_val is not None else self.q_accel
        dt2 = dt * dt
        dt3 = dt2 * dt
        q11 = q_eff * dt3 / 3.0
        q12 = q_eff * dt2 / 2.0
        q22 = q_eff * dt

        Q = [
            [q11, 0.0, q12, 0.0],
            [0.0, q11, 0.0, q12],
            [q12, 0.0, q22, 0.0],
            [0.0, q12, 0.0, q22]
        ]

        FP = [
            [P[0][c] + dt * P[2][c] for c in range(4)],
            [P[1][c] + dt * P[3][c] for c in range(4)],
            [P[2][c] for c in range(4)],
            [P[3][c] for c in range(4)]
        ]
        P_pred = [
            [FP[r][0] + dt * FP[r][2] for r in range(4)],
            [FP[r][1] + dt * FP[r][3] for r in range(4)],
            [FP[r][2] for r in range(4)],
            [FP[r][3] for r in range(4)]
        ]
        P_final = [[0.0]*4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                P_final[r][c] = P_pred[c][r] + Q[r][c]

        return x_pred, P_final

    def _update_measurement(self, x_pred: List[float], P_pred: List[List[float]],
                            z: Tuple[float, float], sigma_m: float) -> Tuple[List[float], List[List[float]]]:
        y0 = z[0] - x_pred[0]
        y1 = z[1] - x_pred[1]

        r_val = sigma_m ** 2
        s00 = P_pred[0][0] + r_val
        s01 = P_pred[0][1]
        s10 = P_pred[1][0]
        s11 = P_pred[1][1] + r_val

        det_s = s00 * s11 - s01 * s10
        if abs(det_s) < 1e-9:
            return x_pred, P_pred

        inv_s00 = s11 / det_s
        inv_s01 = -s01 / det_s
        inv_s10 = -s10 / det_s
        inv_s11 = s00 / det_s

        K = [[0.0, 0.0] for _ in range(4)]
        for i in range(4):
            p0 = P_pred[i][0]
            p1 = P_pred[i][1]
            K[i][0] = p0 * inv_s00 + p1 * inv_s10
            K[i][1] = p0 * inv_s01 + p1 * inv_s11

        x_up = [x_pred[i] + K[i][0] * y0 + K[i][1] * y1 for i in range(4)]

        P_up = [[0.0]*4 for _ in range(4)]
        for i in range(4):
            for j in range(4):
                val = P_pred[i][j] - (K[i][0] * P_pred[0][j] + K[i][1] * P_pred[1][j])
                P_up[i][j] = val

        for i in range(4):
            for j in range(i + 1, 4):
                avg = (P_up[i][j] + P_up[j][i]) / 2.0
                P_up[i][j] = avg
                P_up[j][i] = avg

        return x_up, P_up

    def add_measurement(self, state: TrackState, meas_history: List[MeasurementRecord],
                        lat: float, lon: float, t: float, source_type: str,
                        source_id: str, custom_sigma: Optional[float] = None,
                        threat_type: Optional[str] = None) -> TrackState:
        sigma_m = custom_sigma or DEFAULT_SOURCE_SIGMA.get(source_type, DEFAULT_SOURCE_SIGMA["default"])
        if threat_type:
            state.threat_type = threat_type

        # Compute adaptive q_accel based on aerodynamic envelope & speed
        current_speed = math.hypot(state.x[2], state.x[3])
        aero = get_aero_profile(state.threat_type)
        q_eff = aero.effective_q(current_speed)

        new_meas = MeasurementRecord(timestamp=t, lat=lat, lon=lon, source_type=source_type,
                                     source_id=source_id, cep_m=sigma_m)

        # Check if measurement is out of sequence (OOSM: t < state.t)
        if t < state.t:
            meas_history.append(new_meas)
            meas_history.sort(key=lambda m: m.timestamp)
            if len(meas_history) > self.max_history:
                meas_history = meas_history[-self.max_history:]

            m0 = meas_history[0]
            curr_state, _ = self.init_track(
                track_id=state.track_id, lat=m0.lat, lon=m0.lon, t=m0.timestamp,
                source_type=m0.source_type
            )
            curr_state.threat_type = state.threat_type
            for m in meas_history[1:]:
                dt = m.timestamp - curr_state.t
                if dt > 0:
                    spd = math.hypot(curr_state.x[2], curr_state.x[3])
                    q_step = aero.effective_q(spd)
                    x_pred, P_pred = self._predict(curr_state.x, curr_state.P, dt, q_val=q_step)
                    ez, nz = latlon_to_enu(m.lat, m.lon, curr_state.ref_lat, curr_state.ref_lon)
                    x_up, P_up = self._update_measurement(x_pred, P_pred, (ez, nz), m.cep_m)
                    curr_state.x = x_up
                    curr_state.P = P_up
                    curr_state.t = m.timestamp
                    curr_state.n_updates += 1

            return curr_state
        else:
            # Sequential update
            dt = t - state.t
            x_pred, P_pred = self._predict(state.x, state.P, dt, q_val=q_eff)
            ez, nz = latlon_to_enu(lat, lon, state.ref_lat, state.ref_lon)
            x_up, P_up = self._update_measurement(x_pred, P_pred, (ez, nz), sigma_m)

            state.x = x_up
            state.P = P_up
            state.t = t
            state.n_updates += 1
            meas_history.append(new_meas)
            if len(meas_history) > self.max_history:
                meas_history.pop(0)
            return state

    def eta_cone(self, state: TrackState, target_lat: float, target_lon: float) -> Optional[Dict[str, Any]]:
        """
        Calculates Estimated Time of Arrival (ETA) to target and projects
        probabilistic uncertainty cone based on velocity covariance.
        """
        te, tn = latlon_to_enu(target_lat, target_lon, state.ref_lat, state.ref_lon)
        ce, cn = state.x[0], state.x[1]
        ve, vn = state.x[2], state.x[3]

        de = te - ce
        dn = tn - cn
        dist_m = math.hypot(de, dn)
        speed = math.hypot(ve, vn)

        if speed < 2.0 or dist_m < 50.0:
            return None

        heading_rad = math.atan2(ve, vn)
        bearing_to_target = math.atan2(de, dn)

        diff_rad = math.atan2(math.sin(bearing_to_target - heading_rad), math.cos(bearing_to_target - heading_rad))
        diff_deg = abs(math.degrees(diff_rad))

        sigma_ve = math.sqrt(max(0.1, state.P[2][2]))
        sigma_vn = math.sqrt(max(0.1, state.P[3][3]))
        sigma_v = math.sqrt(sigma_ve**2 + sigma_vn**2)

        cone_half_angle_rad = max(math.radians(10.0), min(math.radians(60.0), 2.0 * math.atan2(sigma_v, speed)))
        cone_half_angle_deg = math.degrees(cone_half_angle_rad)

        is_in_corridor = diff_deg <= cone_half_angle_deg

        v_min = max(5.0, speed - 2.0 * sigma_v)
        v_max = speed + 2.0 * sigma_v

        eta_sec = dist_m / speed
        eta_min_sec = dist_m / v_max
        eta_max_sec = dist_m / v_min

        cone_length = min(dist_m * 1.5, max(15000.0, speed * 600.0))

        le = ce + cone_length * math.sin(heading_rad - cone_half_angle_rad)
        ln = cn + cone_length * math.cos(heading_rad - cone_half_angle_rad)
        re = ce + cone_length * math.sin(heading_rad + cone_half_angle_rad)
        rn = cn + cone_length * math.cos(heading_rad + cone_half_angle_rad)

        lat_c, lon_c = enu_to_latlon(ce, cn, state.ref_lat, state.ref_lon)
        lat_l, lon_l = enu_to_latlon(le, ln, state.ref_lat, state.ref_lon)
        lat_r, lon_r = enu_to_latlon(re, rn, state.ref_lat, state.ref_lon)

        return {
            "is_in_corridor": is_in_corridor,
            "dist_km": round(dist_m / 1000.0, 2),
            "speed_kmh": round(speed * 3.6, 1),
            "speed_mps": round(speed, 1),
            "speed_sigma_mps": round(sigma_v, 2),
            "heading_deg": round((math.degrees(heading_rad) + 360.0) % 360.0, 1),
            "bearing_deg": round((math.degrees(bearing_to_target) + 360.0) % 360.0, 1),
            "angle_diff_deg": round(diff_deg, 1),
            "cone_half_angle_deg": round(cone_half_angle_deg, 1),
            "eta_sec": round(eta_sec, 0),
            "eta_min_sec": round(eta_min_sec, 0),
            "eta_max_sec": round(eta_max_sec, 0),
            "eta_time_str": f"{int(eta_sec // 60)}m {int(eta_sec % 60)}s",
            "cone_polygon": [
                [round(lat_c, 6), round(lon_c, 6)],
                [round(lat_l, 6), round(lon_l, 6)],
                [round(lat_r, 6), round(lon_r, 6)],
                [round(lat_c, 6), round(lon_c, 6)]
            ]
        }
