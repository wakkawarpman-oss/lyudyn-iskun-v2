import math
import datetime
from zoneinfo import ZoneInfo

KYIV_TZ = ZoneInfo("Europe/Kyiv")

class GeointEngine:
    """Lightweight military-grade GEOINT analysis engine:
    1. Solar Azimuth & Chrono-location (Shadow Analysis)
    2. Blast Radius & Danger Zone Modeling
    3. Spatial Coordinate Interpolation
    """

    @staticmethod
    def calculate_sun_position(lat: float, lon: float, dt_utc: datetime.datetime = None):
        """Calculates exact Solar Azimuth, Solar Elevation (altitude), and Shadow Direction.
        Used to verify the time of day from shadows on photos (anti-spoofing/anti-IPSO).
        """
        if dt_utc is None:
            dt_utc = datetime.datetime.now(datetime.timezone.utc)
        elif dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=datetime.timezone.utc)

        # Day of year and fractional hour
        day_of_year = dt_utc.timetuple().tm_yday
        hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0

        # Fractional year in radians
        gamma = (2 * math.pi / 365) * (day_of_year - 1 + (hour - 12) / 24)

        # Equation of time in minutes
        eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                           - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))

        # Solar declination angle in radians
        decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
                - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
                - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))

        # True solar time
        time_offset = eqtime + 4 * lon
        tst = hour * 60 + time_offset
        solar_hour_angle = (tst / 4) - 180
        if solar_hour_angle < -180:
            solar_hour_angle += 360

        # Convert to radians
        lat_rad = math.radians(lat)
        ha_rad = math.radians(solar_hour_angle)

        # Solar Zenith and Elevation
        cos_zenith = math.sin(lat_rad) * math.sin(decl) + math.cos(lat_rad) * math.cos(decl) * math.cos(ha_rad)
        cos_zenith = max(-1.0, min(1.0, cos_zenith))
        zenith = math.acos(cos_zenith)
        elevation = 90.0 - math.degrees(zenith)

        # Solar Azimuth
        cos_azimuth = (math.sin(decl) * math.cos(lat_rad) - math.cos(decl) * math.sin(lat_rad) * math.cos(ha_rad)) / math.sin(zenith) if math.sin(zenith) != 0 else 0
        cos_azimuth = max(-1.0, min(1.0, cos_azimuth))
        azimuth = math.degrees(math.acos(cos_azimuth))
        if solar_hour_angle > 0:
            azimuth = 360.0 - azimuth

        # Shadow direction is exactly opposite to the sun's azimuth (180 deg)
        shadow_azimuth = (azimuth + 180.0) % 360.0

        # Shadow length multiplier (1 meter tall object casts X meters shadow)
        shadow_ratio = 1.0 / math.tan(math.radians(elevation)) if elevation > 0 else 0.0

        kyiv_time_str = dt_utc.astimezone(KYIV_TZ).strftime("%H:%M")

        return {
            "solar_elevation_deg": round(elevation, 1),
            "solar_azimuth_deg": round(azimuth, 1),
            "shadow_direction_deg": round(shadow_azimuth, 1),
            "shadow_ratio": round(shadow_ratio, 2) if elevation > 0 else "Нічний час (сонце нижче горизонту)",
            "is_daylight": elevation > 0,
            "kyiv_time": kyiv_time_str
        }

    @staticmethod
    def get_tactical_danger_zones(lat: float, lon: float, event_type: str, resonance: int):
        """Calculates standard military tactical blast radii and safety zones."""
        # Scale blast radii based on weapon resonance and event type
        is_high_threat = resonance >= 80 or event_type in ['direct_strike', 'explosion']
        
        red_radius = 60 if is_high_threat else 30      # Fatal blast & collapse zone
        orange_radius = 180 if is_high_threat else 90  # Structural damage & shockwave
        yellow_radius = 450 if is_high_threat else 200 # Glass shatter & shrapnel zone

        return {
            "center": {"lat": lat, "lon": lon},
            "fatal_zone_m": red_radius,
            "shockwave_zone_m": orange_radius,
            "shrapnel_zone_m": yellow_radius,
            "evacuation_recommended": is_high_threat
        }

geoint_engine = GeointEngine()
