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

class DamageLevelEnum(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ParsedEventSchema(BaseModel):
    is_kyiv_region: bool = Field(default=False, description="Чи стосується повідомлення Києва або Київської області")
    is_confirmed_incident: bool = Field(default=False, description="Чи є подія підтвердженим фактом вибуху/прильоту/пожежі")
    is_radar_track: bool = Field(default=False, description="Чи є це радарним відстеженням руху БпЛА/ракети")
    event_type: EventTypeEnum = Field(default=EventTypeEnum.GENERAL_ALERT, description="Тип події")
    location: str = Field(default="Київ та область", description="Назва міста/району/вулиці")
    osm_query: str = Field(default="Київ", description="Точний запит для OpenStreetMap")
    casualties: bool = Field(default=False, description="Наявність жертв або поранених")
    damage_level: DamageLevelEnum = Field(default=DamageLevelEnum.NONE, description="Рівень руйнувань")
    short_summary: str = Field(default="Оперативна інформація", description="Стислий факт без оціночних суджень")

class ThreatAssessmentSlotSchema(BaseModel):
    current_status_summary: str = Field(description="1-2 речення аналізу поточної активності ворога")
    ballistic_risk_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(description="Рівень балістичного ризику")
    drone_activity_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(description="Рівень активності БпЛА")
    aviation_status: Literal["HIGH_ALERT", "STANDARD_PATROL", "STANDBY"] = Field(description="Статус стратегічної авіації")
    safety_recommendation: str = Field(description="Коротка порада цивільної безпеки")
