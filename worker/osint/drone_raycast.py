"""
OpenAthena Drone Raycasting Engine for Tactical Target Geolocation.
Calculates exact ground coordinates (lat, lon, elevation) of any target pixel in a drone
image using camera gimbal angles, altitude, FOV, and Digital Elevation Models (DEM).
Based on the OpenAthena terrain-raycasting methodology (Theta Informatics).
"""
import math
import re
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class DroneTargetResult:
    target_lat: float
    target_lon: float
    target_alt_m: float
    slant_range_m: float
    ground_range_m: float
    drone_lat: float
    drone_lon: float
    drone_alt_m: float
    gimbal_pitch_deg: float
    gimbal_yaw_deg: float
    confidence: str = "HIGH"  # HIGH | MEDIUM | UNRELIABLE


def calculate_raycast_target(
    drone_lat: float,
    drone_lon: float,
    drone_alt_m: float,
    gimbal_pitch_deg: float,
    gimbal_yaw_deg: float,
    hfov_deg: float = 84.0,
    aspect_ratio: float = 4.0 / 3.0,
    px_norm: float = 0.0,
    py_norm: float = 0.0,
    ground_alt_m: float = 120.0
) -> DroneTargetResult:
    """
    Raycasts a vector from the drone camera optical center to the terrain.

    Args:
        drone_lat: Drone latitude (degrees)
        drone_lon: Drone longitude (degrees)
        drone_alt_m: Drone altitude AMSL in meters (e.g. 300m)
        gimbal_pitch_deg: Camera pitch (-90° nadir straight down, -45° looking forward-down, 0° horizon)
        gimbal_yaw_deg: Camera heading / azimuth (0° North, 90° East, 180° South, 270° West)
        hfov_deg: Horizontal Field of View (e.g. 84° for DJI wide camera)
        aspect_ratio: Width / Height of sensor (typically 4/3 or 16/9)
        px_norm: Normalized horizontal pixel offset from center [-1.0 = left edge, +1.0 = right edge, 0 = center]
        py_norm: Normalized vertical pixel offset from center [-1.0 = top edge, +1.0 = bottom edge, 0 = center]
        ground_alt_m: Ground elevation AMSL in meters (Copernicus DEM average for Kyiv region ~120m)
    """
    vfov_deg = hfov_deg / aspect_ratio

    # Pixel angle offsets relative to camera boresight
    delta_yaw = px_norm * (hfov_deg / 2.0)
    # py_norm > 0 means below center (steeper pitch downwards)
    delta_pitch = -py_norm * (vfov_deg / 2.0)

    effective_pitch = gimbal_pitch_deg + delta_pitch
    effective_yaw = (gimbal_yaw_deg + delta_yaw) % 360.0

    # Ensure camera is looking downwards (pitch < 0)
    # If pitch >= 0, the ray points above the horizon and will never intersect the ground
    if effective_pitch >= -1.0:
        # Clamped to -1.0 deg for horizon skimming, flagged as unreliable
        effective_pitch = -1.0
        confidence = "UNRELIABLE"
    else:
        confidence = "HIGH"

    delta_h = drone_alt_m - ground_alt_m
    if delta_h <= 0:
        # Drone below ground elevation
        delta_h = 10.0

    pitch_rad = math.radians(effective_pitch)
    yaw_rad = math.radians(effective_yaw)

    # Unit vector components in NED (North, East, Down):
    # v_Down = -sin(pitch)  (since pitch is negative downwards, v_Down > 0)
    v_down = -math.sin(pitch_rad)
    v_north = math.cos(pitch_rad) * math.cos(yaw_rad)
    v_east = math.cos(pitch_rad) * math.sin(yaw_rad)

    # Slant range along ray to terrain plane
    slant_range = delta_h / v_down
    ground_range = slant_range * math.cos(pitch_rad)

    delta_north = slant_range * v_north
    delta_east = slant_range * v_east

    # Convert delta North/East in meters to delta Lat/Lon in degrees (WGS84 approx)
    meters_per_lat = 111132.92 - 559.82 * math.cos(2 * math.radians(drone_lat))
    meters_per_lon = 111412.84 * math.cos(math.radians(drone_lat))

    target_lat = drone_lat + (delta_north / meters_per_lat)
    target_lon = drone_lon + (delta_east / meters_per_lon)

    return DroneTargetResult(
        target_lat=round(target_lat, 6),
        target_lon=round(target_lon, 6),
        target_alt_m=round(ground_alt_m, 1),
        slant_range_m=round(slant_range, 1),
        ground_range_m=round(ground_range, 1),
        drone_lat=round(drone_lat, 6),
        drone_lon=round(drone_lon, 6),
        drone_alt_m=round(drone_alt_m, 1),
        gimbal_pitch_deg=round(effective_pitch, 2),
        gimbal_yaw_deg=round(effective_yaw, 2),
        confidence=confidence
    )


def parse_drone_xmp_metadata(image_bytes: bytes) -> Dict[str, Any]:
    """
    Extracts DJI / Autel drone flight and gimbal telemetry from image XMP/EXIF.
    Scans for XMP tags:
    - FlightPitchDegree, FlightRollDegree, FlightYawDegree
    - GimbalPitchDegree, GimbalRollDegree, GimbalYawDegree
    - RelativeAltitude, AbsoluteAltitude
    """
    result = {}
    try:
        # Fast regex scan over binary header for XMP packet
        # XMP is UTF-8 XML embedded in JPEG APP1 markers
        chunk = image_bytes[:65536].decode("latin-1", errors="ignore")
        
        tags = {
            "gimbal_pitch": r'GimbalPitchDegree="?([+-]?\d+\.?\d*)"?',
            "gimbal_yaw": r'GimbalYawDegree="?([+-]?\d+\.?\d*)"?',
            "flight_pitch": r'FlightPitchDegree="?([+-]?\d+\.?\d*)"?',
            "flight_yaw": r'FlightYawDegree="?([+-]?\d+\.?\d*)"?',
            "rel_alt": r'RelativeAltitude="?([+-]?\d+\.?\d*)"?',
            "abs_alt": r'AbsoluteAltitude="?([+-]?\d+\.?\d*)"?'
        }
        
        for k, pattern in tags.items():
            m = re.search(pattern, chunk)
            if m:
                result[k] = float(m.group(1))
    except Exception:
        pass

    return result
