"""
worker/track_fusion_v2.py
P1 (Multi-INT Data Fusion Engine): Модуль Кінематики та ETA.
Квадратична модель процесного шуму q_eff(v) + фізичні аеродинамічні ліміти (AeroLimits) + ETA Cone.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import numpy as np

try:
    from shapely.geometry import Polygon
except ImportError:
    Polygon = None


@dataclass(frozen=True)
class AeroLimits:
    v_stall_ms: float  # Швидкість звалювання (мінімальна)
    v_dive_ms: float   # Швидкість пікірування (максимальна)
    q_base: float      # Базовий шум процесу
    q_max: float       # Максимальний шум процесу (насичення)
    beta: float        # Коефіцієнт маневреності
    v_ref: float       # Крейсерська швидкість


# База ТТХ на основі OSINT-даних (AlabugaLeaks, звіти)
AERO_DB: Dict[str, AeroLimits] = {
    "SHAHED_136": AeroLimits(v_stall_ms=33.0, v_dive_ms=75.0, q_base=5.0, q_max=35.0, beta=0.8, v_ref=50.0),
    "GERAN_2": AeroLimits(v_stall_ms=33.0, v_dive_ms=75.0, q_base=5.0, q_max=40.0, beta=0.9, v_ref=50.0),
    "ORLAN_10": AeroLimits(v_stall_ms=25.0, v_dive_ms=45.0, q_base=2.0, q_max=15.0, beta=0.5, v_ref=30.0),
    "SHAHED_238": AeroLimits(v_stall_ms=70.0, v_dive_ms=190.0, q_base=10.0, q_max=50.0, beta=0.6, v_ref=100.0),
    "KH_101": AeroLimits(v_stall_ms=180.0, v_dive_ms=270.0, q_base=15.0, q_max=80.0, beta=0.4, v_ref=200.0),
    "TACHION": AeroLimits(v_stall_ms=12.0, v_dive_ms=35.0, q_base=1.5, q_max=15.0, beta=1.2, v_ref=25.0),
    "ISKANDER_M": AeroLimits(v_stall_ms=1500.0, v_dive_ms=2100.0, q_base=50.0, q_max=500.0, beta=0.1, v_ref=1800.0),
    "GENERIC_UAV": AeroLimits(v_stall_ms=15.0, v_dive_ms=60.0, q_base=5.0, q_max=35.0, beta=0.8, v_ref=50.0),
}

# Aliases
AERO_DB["DRONE"] = AERO_DB["GENERIC_UAV"]
AERO_DB["UAV"] = AERO_DB["GENERIC_UAV"]


class KalmanTrackFilterV2:
    def __init__(self, threat_type: str = "GERAN_2"):
        key = threat_type.upper().replace("-", "_")
        self.threat_type = threat_type
        self.limits = AERO_DB.get(key, AERO_DB.get("GERAN_2", AERO_DB["SHAHED_136"]))

    def calculate_q_eff(self, current_v_ms: float) -> float:
        """
        Розрахунок динамічного процесного шуму на основі поточної швидкості.
        q_eff(v) = min(q_max, q_base * (1.0 + beta * (v_clamped / v_ref)^2))
        """
        # Обмеження швидкості фізичними аеродинамічними лімітами
        v_clamped = max(self.limits.v_stall_ms, min(current_v_ms, self.limits.v_dive_ms))

        # Квадратична модель
        q_calc = self.limits.q_base * (1.0 + self.limits.beta * (v_clamped / self.limits.v_ref)**2)
        return min(self.limits.q_max, q_calc)

    def estimate_eta_cone(self, state_x: float, state_y: float, heading: float, v_ms: float, time_horizon_sec: int) -> Dict[str, Any]:
        """
        Розрахунок ETA-полігону з урахуванням аеродинаміки.
        """
        v_min = self.limits.v_stall_ms
        v_max = self.limits.v_dive_ms
        # Розрахунок мінімальної та максимальної дальності за заданий час
        dist_min = v_min * time_horizon_sec
        dist_max = v_max * time_horizon_sec

        # Кут розкриття конуса залежить від q_eff (високий q_eff -> ширший конус)
        eff_v = max(1.0, v_ms)
        q_eff = self.calculate_q_eff(eff_v)
        theta_cone = float(np.degrees(np.arctan(q_eff / eff_v)))
        theta_cone = max(3.0, min(45.0, theta_cone))

        polygon = self._build_polygon(state_x, state_y, heading, dist_min, dist_max, theta_cone)

        return {
            "dist_min_m": round(dist_min, 1),
            "dist_max_m": round(dist_max, 1),
            "theta_cone_deg": round(theta_cone, 2),
            "q_eff": round(q_eff, 3),
            "eta_polygon": polygon
        }

    def _build_polygon(self, x: float, y: float, heading: float, d_min: float, d_max: float, theta: float) -> List[List[float]]:
        """
        Будує координати полігону конуса розсіювання (сектор досяжності).
        """
        # Heading 0 deg = North (+y), 90 deg = East (+x)
        h_rad = math.radians(heading)
        t_rad = math.radians(theta)

        angles = np.linspace(h_rad - t_rad, h_rad + t_rad, 7)
        outer_points = []
        for a in angles:
            px = x + d_max * math.sin(a)
            py = y + d_max * math.cos(a)
            outer_points.append([round(px, 3), round(py, 3)])

        inner_points = []
        for a in reversed(angles):
            px = x + d_min * math.sin(a)
            py = y + d_min * math.cos(a)
            inner_points.append([round(px, 3), round(py, 3)])

        poly = outer_points + inner_points
        if poly:
            poly.append(poly[0])  # Замикаємо полігон
        return poly
