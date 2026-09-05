"""
OKINT-PRO · Kalman Track Fusion Engine (ENU, per-source R, OOSM Retrodiction, ETA Cone)
Local East-North-Up (ENU) coordinates tracking with Continuous White Noise Acceleration (CWNA)
process noise, per-source measurement covariance, out-of-sequence replay buffer, and sigma-dispersion ETA cones.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

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
    threat_type: str = "drone"  # drone | cruise_missile | ballistic

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


class KalmanTrackFilter:
    """
    Continuous-Discrete Kalman Filter in local ENU frame with
    Continuous White Noise Acceleration (CWNA) and Out-Of-Sequence Measurement (OOSM) handling.
    """
    def __init__(self, q_accel: float = 8.0, max_history: int = 50):
        self.q_accel = q_accel
        self.max_history = max_history

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
        r_vel = (20.0) ** 2  # ~20 m/s initial speed uncertainty

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

    def _predict(self, x: List[float], P: List[List[float]], dt: float) -> Tuple[List[float], List[List[float]]]:
        if dt <= 0:
            return [v for v in x], [[c for c in row] for row in P]

        # F matrix:
        # [1, 0, dt,  0]
        # [0, 1,  0, dt]
        # [0, 0,  1,  0]
        # [0, 0,  0,  1]
        x_pred = [
            x[0] + dt * x[2],
            x[1] + dt * x[3],
            x[2],
            x[3]
        ]

        # Q CWNA matrix:
        # dt3_3 = q * dt^3 / 3
        # dt2_2 = q * dt^2 / 2
        # dt1   = q * dt
        dt2 = dt * dt
        dt3 = dt2 * dt
        q11 = self.q_accel * dt3 / 3.0
        q12 = self.q_accel * dt2 / 2.0
        q22 = self.q_accel * dt

        Q = [
            [q11, 0.0, q12, 0.0],
            [0.0, q11, 0.0, q12],
            [q12, 0.0, q22, 0.0],
            [0.0, q12, 0.0, q22]
        ]

        # P_pred = F * P * F^T + Q
        # Compute F * P:
        FP = [
            [P[0][c] + dt * P[2][c] for c in range(4)],
            [P[1][c] + dt * P[3][c] for c in range(4)],
            [P[2][c] for c in range(4)],
            [P[3][c] for c in range(4)]
        ]
        # Compute (FP) * F^T:
        P_pred = [
            [FP[r][0] + dt * FP[r][2] for r in range(4)],
            [FP[r][1] + dt * FP[r][3] for r in range(4)],
            [FP[r][2] for r in range(4)],
            [FP[r][3] for r in range(4)]
        ]
        # Transpose to match rows/cols and add Q:
        P_final = [[0.0]*4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                P_final[r][c] = P_pred[c][r] + Q[r][c]

        return x_pred, P_final

    def _update_measurement(self, x_pred: List[float], P_pred: List[List[float]],
                            z: Tuple[float, float], sigma_m: float) -> Tuple[List[float], List[List[float]]]:
        # Measurement matrix H = [[1, 0, 0, 0], [0, 1, 0, 0]]
        # Innovation y = z - H * x_pred
        y0 = z[0] - x_pred[0]
        y1 = z[1] - x_pred[1]

        r_val = sigma_m ** 2
        # S = H * P * H^T + R
        # S is 2x2:
        # S[0][0] = P_pred[0][0] + r_val
        # S[0][1] = P_pred[0][1]
        # S[1][0] = P_pred[1][0]
        # S[1][1] = P_pred[1][1] + r_val
        s00 = P_pred[0][0] + r_val
        s01 = P_pred[0][1]
        s10 = P_pred[1][0]
        s11 = P_pred[1][1] + r_val

        det_s = s00 * s11 - s01 * s10
        if abs(det_s) < 1e-9:
            return x_pred, P_pred

        # S^-1
        inv_s00 = s11 / det_s
        inv_s01 = -s01 / det_s
        inv_s10 = -s10 / det_s
        inv_s11 = s00 / det_s

        # P * H^T is 4x2: col 0 is P[:][0], col 1 is P[:][1]
        # Kalman Gain K = (P * H^T) * S^-1 (4x2)
        K = [[0.0, 0.0] for _ in range(4)]
        for i in range(4):
            p0 = P_pred[i][0]
            p1 = P_pred[i][1]
            K[i][0] = p0 * inv_s00 + p1 * inv_s10
            K[i][1] = p0 * inv_s01 + p1 * inv_s11

        # Updated state x = x_pred + K * y
        x_up = [x_pred[i] + K[i][0] * y0 + K[i][1] * y1 for i in range(4)]

        # Updated covariance: P = (I - K*H) * P_pred
        # KH is 4x4 where KH[i][0] = K[i][0], KH[i][1] = K[i][1], rest 0
        P_up = [[0.0]*4 for _ in range(4)]
        for i in range(4):
            for j in range(4):
                val = P_pred[i][j] - (K[i][0] * P_pred[0][j] + K[i][1] * P_pred[1][j])
                P_up[i][j] = val

        # Symmetrize P
        for i in range(4):
            for j in range(i + 1, 4):
                avg = (P_up[i][j] + P_up[j][i]) / 2.0
                P_up[i][j] = avg
                P_up[j][i] = avg

        return x_up, P_up

    def add_measurement(self, state: TrackState, meas_history: List[MeasurementRecord],
                        lat: float, lon: float, t: float, source_type: str,
                        source_id: str, custom_sigma: Optional[float] = None) -> TrackState:
        sigma_m = custom_sigma or DEFAULT_SOURCE_SIGMA.get(source_type, DEFAULT_SOURCE_SIGMA["default"])
        new_meas = MeasurementRecord(timestamp=t, lat=lat, lon=lon, source_type=source_type,
                                     source_id=source_id, cep_m=sigma_m)

        # Check if measurement is out of sequence (OOSM: t < state.t)
        if t < state.t:
            # Insert measurement in sorted order
            meas_history.append(new_meas)
            meas_history.sort(key=lambda m: m.timestamp)
            if len(meas_history) > self.max_history:
                meas_history = meas_history[-self.max_history:]

            # Re-run filter forward from earliest recorded measurement
            m0 = meas_history[0]
            curr_state, _ = self.init_track(
                track_id=state.track_id, lat=m0.lat, lon=m0.lon, t=m0.timestamp,
                source_type=m0.source_type
            )
            for m in meas_history[1:]:
                dt = m.timestamp - curr_state.t
                if dt > 0:
                    x_pred, P_pred = self._predict(curr_state.x, curr_state.P, dt)
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
            x_pred, P_pred = self._predict(state.x, state.P, dt)
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

        # Angular difference
        diff_rad = math.atan2(math.sin(bearing_to_target - heading_rad), math.cos(bearing_to_target - heading_rad))
        diff_deg = abs(math.degrees(diff_rad))

        # Velocity sigma from covariance
        sigma_ve = math.sqrt(max(0.1, state.P[2][2]))
        sigma_vn = math.sqrt(max(0.1, state.P[3][3]))
        sigma_v = math.sqrt(sigma_ve**2 + sigma_vn**2)

        # Cone opening half-angle (2-sigma transverse uncertainty)
        cone_half_angle_rad = max(math.radians(10.0), min(math.radians(60.0), 2.0 * math.atan2(sigma_v, speed)))
        cone_half_angle_deg = math.degrees(cone_half_angle_rad)

        is_in_corridor = diff_deg <= cone_half_angle_deg

        # ETA calculations with 2-sigma speed interval
        v_min = max(5.0, speed - 2.0 * sigma_v)
        v_max = speed + 2.0 * sigma_v

        eta_sec = dist_m / speed
        eta_min_sec = dist_m / v_max
        eta_max_sec = dist_m / v_min

        # Generate cone boundary polygon points (WGS84)
        left_angle = heading_rad - cone_half_angle_rad
        right_angle = heading_rad + cone_half_angle_rad
        cone_length = min(dist_m * 1.5, max(15000.0, speed * 600.0))  # 10 min projection or 1.5x dist

        le = ce + cone_length * math.sin(left_angle)
        ln = cn + cone_length * math.cos(left_angle)
        re = ce + cone_length * math.sin(right_angle)
        rn = cn + cone_length * math.cos(right_angle)

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
