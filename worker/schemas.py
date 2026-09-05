from pydantic import BaseModel, Field
from typing import Literal
from enum import Enum

class EventTypeEnum(str, Enum):
    DIRECT_STRIKE = "direct_strike"
    EXPLOSION = "explosion"
    FIRE = "fire"
    DESTRUCTION = "destruction"
    CASUALTIES = "casualties"
    ARMED_CONFLICT = "armed_conflict"
    RADAR_TRACK = "radar_track"
    GENERAL_ALERT = "general_alert"
    AIR_DEFENSE = "air_defense"
    CIVILIAN_NOISE = "civilian_noise"

class DamageLevelEnum(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ParsedEventSchema(BaseModel):
    is_kyiv_region: bool = Field(default=False, description="Чи стосується повідомлення Києва або Київської області")
    target_oblast: str = Field(default="all", description="Код області (наприклад: kharkiv, odesa, dnipropetrovsk, zaporizhzhia, mykolaiv, lviv, sumy, poltava, kyiv_city, kyiv_oblast...)")
    is_confirmed_incident: bool = Field(default=False, description="Чи є подія підтвердженим фактом вибуху/прильоту/пожежі")
    is_radar_track: bool = Field(default=False, description="Чи є це радарним відстеженням руху БпЛА/ракети")
    event_type: EventTypeEnum = Field(default=EventTypeEnum.GENERAL_ALERT, description="Тип події")
    location: str = Field(default="Україна", description="Назва міста/району/вулиці")
    osm_query: str = Field(default="Україна", description="Точний запит для OpenStreetMap")
    casualties: bool = Field(default=False, description="Наявність жертв або поранених")
    damage_level: DamageLevelEnum = Field(default=DamageLevelEnum.NONE, description="Рівень руйнувань")
    short_summary: str = Field(default="Оперативна інформація", description="Стислий факт без оціночних суджень")

class ThreatAssessmentSlotSchema(BaseModel):
    current_status_summary: str = Field(description="1-2 речення аналізу поточної активності ворога")
    ballistic_risk_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(description="Рівень балістичного ризику")
    drone_activity_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(description="Рівень активності БпЛА")
    aviation_status: Literal["HIGH_ALERT", "STANDARD_PATROL", "STANDBY"] = Field(description="Статус стратегічної авіації")
    safety_recommendation: str = Field(description="Коротка порада цивільної безпеки")


# --- C4ISR Unified Multi-Domain Schemas ---

class TacticalThreatTypeEnum(str, Enum):
    SHAHED_136 = "shahed_136"
    SHAHED_238 = "shahed_238"
    CRUISE_MISSILE = "cruise_missile"
    KH_101 = "kh_101"
    BALLISTIC = "ballistic"
    ISKANDER_M = "iskander_m"
    KAB_500 = "kab_500"
    SUPER_CAM = "super_cam"
    MSTA_S = "msta_s"
    MARITIME_SALVO = "maritime_salvo"
    SIGINT_EMITTER = "sigint_emitter"
    ACOUSTIC_HIT = "acoustic_hit"
    THERMAL_ANOMALY = "thermal_anomaly"
    DRONE = "drone"


class EtaConeSchema(BaseModel):
    is_in_corridor: bool = True
    dist_km: float = 0.0
    speed_kmh: float = 0.0
    speed_mps: float = 0.0
    speed_sigma_mps: float = 0.0
    heading_deg: float = 0.0
    bearing_deg: float = 0.0
    angle_diff_deg: float = 0.0
    cone_half_angle_deg: float = 15.0
    eta_sec: float = 0.0
    eta_min_sec: float = 0.0
    eta_max_sec: float = 0.0
    eta_time_str: str = ""
    cone_polygon: list = Field(default_factory=list)


class TerrainMaskingSchema(BaseModel):
    is_terrain_masked: bool = False
    masking_type: str = "NONE"
    river_corridor: str | None = None
    river_distance_km: float | None = None
    nearest_radar: str | None = None
    dist_to_radar_km: float | None = None
    radio_horizon_km: float | None = None
    horizon_delta_km: float | None = None
    target_alt_agl_m: float = 60.0
    directive: str = "🟢 ПРЯМА ВИДИМІСТЬ РЛС (LoS Clear)"


class BayesianConfidenceSchema(BaseModel):
    posterior_probability: float = Field(ge=0.0, le=1.0)
    confidence_score: int = Field(ge=0, le=100)
    category: str = "UNCERTAIN"
    category_label: str = ""
    false_positive_rate_pct: float = 50.0
    log_odds: float = 0.0
    active_corroborating_sources_count: int = 0
    evidence_breakdown: list = Field(default_factory=list)


class EwProfileSchema(BaseModel):
    crpa_type: str | None = None
    jamming_resistance: str | None = None
    uplink_mhz: float | None = None
    frequency_mhz: float | None = None
    power_dbm: float | None = None
    source_emitter: str | None = None


class WeatherVectorSchema(BaseModel):
    air_speed_kmh: float = 185.0
    ground_speed_kmh: float = 185.0
    ground_heading_deg: float = 0.0
    drift_angle_deg: float = 0.0
    speed_delta_kmh: float = 0.0
    wind_speed_kmh: float = 0.0
    wind_dir_deg: float = 0.0


class TacticalDroneTrackSchema(BaseModel):
    id: str
    label: str = "БпЛА Shahed-136"
    category: str = "drone"
    color: str = "#ef4444"
    threat_type: str = "shahed_136"
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    heading: float = Field(default=0.0, ge=0.0, le=360.0)
    speed_kmh: float = Field(default=185.0, ge=0.0, le=3500.0)
    confidence: int = Field(default=50, ge=0, le=100)
    place: str = ""
    region: str = ""
    text: str = ""
    time: str = ""
    distance_to_kyiv_km: float = 0.0
    distance_to_dnipro_km: float = 0.0
    distance_to_zaporizhzhia_km: float = 0.0
    is_kyiv_threat: bool = False
    is_dnipro_threat: bool = False
    is_zaporizhzhia_threat: bool = False
    relevant_oblasts: list[str] = Field(default_factory=list)
    trail: list = Field(default_factory=list)
    waypoints: list = Field(default_factory=list)
    eta_cone: dict | None = None
    ew_profile: dict | None = None
    weather_vector: dict | None = None
    acoustic_corroborated: bool = False
    acoustic_sensors_count: int = 0
    corroborating_sensors: list = Field(default_factory=list)
    terrain_masking: dict | None = None
    sigint_corroboration: dict | None = None
    bayesian_confidence: dict | None = None
    military_unit: dict | None = None
    nearest_launch_site: dict | None = None


class AcousticHitSchema(BaseModel):
    hit_id: str
    sensor_id: str
    source: str = "Sky Fortress (Небесна Фортеця)"
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    azimuth: float | None = Field(default=None, ge=0.0, le=360.0)
    snr_db: float = 18.0
    confidence: int = Field(default=80, ge=0, le=100)
    frequency_hz: float = 142.0
    timestamp: str
    age_seconds: int = 0
    ttl_sec: int = 180


class SigintEmitterSchema(BaseModel):
    emitter_id: str
    type: str
    label: str
    frequency_mhz: float
    bandwidth_mhz: float = 20.0
    power_dbm: float = 30.0
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    radius_km: float = 25.0
    source: str = "Field SDR Intercept"
    threat_level: str = "HIGH"
    tactical_advisory: str = ""
    detected_at: str


class MaritimeCarrierSchema(BaseModel):
    carrier_id: str
    name: str
    project: str
    pennant: str
    missile_type: str = "3М-14 «Калібр»"
    vls_cells: int = 8
    lat: float
    lng: float
    speed_kn: float = 0.0
    heading: float = 0.0
    status: str
    status_label: str
    threat_level: str = "CRITICAL"
    sector: str
    distance_to_odesa_km: float = 0.0
    max_range_km: float = 2000.0


class MaritimeSalvoSchema(BaseModel):
    status: str = "CRITICAL"
    status_label: str = ""
    carriers_at_sea_count: int = 0
    total_salvo_potential: int = 0
    carriers: list[MaritimeCarrierSchema] = Field(default_factory=list)
    monitored_sectors: list[str] = Field(default_factory=list)
    source: str = "AIS Maritime Stream / ВМС ЗСУ Реєстр"
    updated_at: str


class FirmsThermalSchema(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    brightness_k: float = 0.0
    bright_ti5_k: float = 0.0
    frp_mw: float = 0.0
    confidence: str = "nominal"
    daynight: str = "D"
    acq_time: str
    satellite: str = "Suomi-NPP VIIRS (375m)"

