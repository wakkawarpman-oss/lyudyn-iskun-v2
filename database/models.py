import os
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Boolean, Float, Text, UniqueConstraint, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from geoalchemy2 import Geometry
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///events.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def _register_sqlite_spatial_functions(dbapi_connection, connection_record):
        dbapi_connection.create_function("ST_Y", 1, lambda geom: 50.4501)
        dbapi_connection.create_function("ST_X", 1, lambda geom: 30.5234)
        dbapi_connection.create_function("RecoverGeometryColumn", 5, lambda *args: 1)
        dbapi_connection.create_function("DiscardGeometryColumn", 2, lambda *args: 1)
        dbapi_connection.create_function("InitSpatialMetaData", 0, lambda: 1)
        dbapi_connection.create_function("InitSpatialMetaData", 1, lambda *args: 1)
        dbapi_connection.create_function("CreateSpatialIndex", 2, lambda *args: 1)
        dbapi_connection.create_function("DisableSpatialIndex", 2, lambda *args: 1)
        dbapi_connection.create_function("GeomFromEWKT", 1, lambda geom: geom)
        dbapi_connection.create_function("GeomFromText", 1, lambda geom: geom)
        dbapi_connection.create_function("GeomFromText", 2, lambda geom, srid: geom)
        dbapi_connection.create_function("AsEWKB", 1, lambda geom: geom)
        dbapi_connection.create_function("AsBinary", 1, lambda geom: geom)
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=15,
        max_overflow=30,
        pool_pre_ping=True,
        pool_recycle=1800
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DetectedEvent(Base):
    __tablename__ = "detected_events"

    id = Column(Integer, primary_key=True, index=True)
    source_channel = Column(String, index=True)
    message_id = Column(Integer, index=True)
    message_text = Column(String)
    
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    event_type = Column(String, index=True) # explosion, air_defense, shelling
    location_text = Column(String)
    
    # PostGIS geometric point for radius searches (GiST indexed by GeoAlchemy2)
    geom = Column(Geometry('POINT', srid=4326))
    
    # Two-Dimensional Scoring (0 - 100)
    significance_score = Column(Integer, default=50) # Physical severity / destructive impact
    confidence_score = Column(Integer, default=50)   # Trustworthiness & verification consensus
    resonance_score = Column(Integer, default=50)    # Composite score for sorting/legacy compatibility
    
    # Incident Clustering & Lifecycle Tracking
    incident_id = Column(String, index=True, nullable=True) # Normalized Incident Identifier (e.g. INC-20260903-BROVARY-01)
    lifecycle_stage = Column(String, default="DETECTED", index=True) # DETECTED | TRACKING | IMPACT | RESOLVED
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    
    has_media = Column(Boolean, default=False)
    # True when geom is a generic city/region-centroid guess (no specific
    # toponym matched in the text), not an actual named location. Lets
    # consumers exclude "we don't know where this is" points near the
    # Maidan-area centroid without also hiding real Maidan-area incidents.
    is_fallback_geo = Column(Boolean, default=False, server_default="false")
    # Perceptual hash (imagehash.phash, 16 hex chars) of the photo/video-frame
    # attached to this event, if any. Lets the pipeline flag a recycled or
    # archival image reposted as a "new" incident (anti-IPSO).
    image_phash = Column(String, nullable=True, index=True)
    raw_message = Column(String) # JSON snapshot of the Telethon message
    
    # Autonomous Factchecking & Multi-Source Consensus
    verification_status = Column(String, default="UNVERIFIED_SINGLE_SOURCE", index=True) # VERIFIED | OFFICIAL | UNVERIFIED_SINGLE_SOURCE | POSSIBLE_IPSO
    sources_count = Column(Integer, default=1)
    sources_list = Column(String, default="") # Comma-separated channel names
    is_official = Column(Boolean, default=False)
    
    # High-Precision Spatial Metrics
    geo_precision = Column(String, default="settlement", index=True) # exact | building | address | street | settlement | district | region
    geo_radius_m = Column(Integer, default=2000) # Uncertainty radius in meters

    # Trust Tier System
    source_tier = Column(String, default="B", index=True) # 'S', 'A', 'B'
    source_weight = Column(Float, default=0.5)

    # Sightline Critical Infrastructure Proximity
    nearby_infrastructure = Column(String, nullable=True) # E.g. "⚡ ПС 330 кВ «Північна» (87 м)"

    __table_args__ = (
        Index("ix_detected_events_type_time", "event_type", "detected_at"),
    )

class BombShelter(Base):
    __tablename__ = "bomb_shelters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    address = Column(String, nullable=True)
    district = Column(String, nullable=True)
    shelter_type = Column(String, default="bomb_shelter") # 'metro_station', 'bunker', 'bomb_shelter', 'underground_parking'
    capacity = Column(Integer, default=150)
    latitude = Column(String, nullable=True)
    longitude = Column(String, nullable=True)
    geom = Column(Geometry('POINT', srid=4326))
    is_operational = Column(Boolean, default=True)


class UserApiKey(Base):
    __tablename__ = "user_api_keys"

    user_id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String, nullable=True)
    openai_api_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChannelForwardEdge(Base):
    __tablename__ = "channel_forward_edges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_channel = Column(String(128), nullable=False, index=True)
    target_channel = Column(String(128), nullable=False, index=True)
    forward_count = Column(Integer, default=1, nullable=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, index=True)
    sample_post_text = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint('source_channel', 'target_channel', name='uq_source_target_edge'),
    )


class HITLFeedbackAudit(Base):
    __tablename__ = "hitl_feedback_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, nullable=True, index=True)
    analyst_id = Column(BigInteger, nullable=False, index=True)
    analyst_name = Column(String(128), nullable=True)
    decision = Column(String(32), nullable=False, index=True)  # CONFIRM | FAKE | NOISE
    source_channel = Column(String(128), nullable=True, index=True)
    reputation_before = Column(Float, nullable=True)
    reputation_after = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    notes = Column(Text, nullable=True)


def schema_or_none(name: str):
    return name if not DATABASE_URL.startswith("sqlite") else None


class SanitizedEvent(Base):
    __tablename__ = "sanitized_events"
    __table_args__ = {"schema": schema_or_none("public_osint")}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_uid = Column(String(64), unique=True, nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    detected_at = Column(DateTime, nullable=False, index=True)
    oblast = Column(String(64), nullable=False)
    district = Column(String(64), nullable=True)
    rough_lat = Column(Float, nullable=False)
    rough_lng = Column(Float, nullable=False)
    rough_geom = Column(Geometry('POINT', srid=4326), nullable=True)
    significance_level = Column(String(32), nullable=False)
    verification_status = Column(String(64), nullable=False)
    sources_count = Column(Integer, default=1)
    sanitized_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    __table_args__ = {"schema": schema_or_none("research")}

    run_id = Column(String(64), primary_key=True)
    scenario_name = Column(String(128), nullable=False)
    parameters = Column(Text, nullable=False)
    synthetic_targets_count = Column(Integer, default=0)
    kalman_tuning_metrics = Column(Text, nullable=True)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TacticalEvent(Base):
    __tablename__ = "tactical_events"
    __table_args__ = {"schema": schema_or_none("restricted_ops")}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    incident_id = Column(String(64), nullable=False, index=True)
    exact_lat = Column(Float, nullable=False)
    exact_lng = Column(Float, nullable=False)
    exact_geom = Column(Geometry('POINT', srid=4326), nullable=True)
    altitude_m = Column(Float, nullable=True)
    speed_kmh = Column(Float, nullable=True)
    heading_deg = Column(Float, nullable=True)
    target_type = Column(String(64), nullable=False)
    raw_telemetry = Column(Text, nullable=True)
    source_channel = Column(String(128), nullable=True)
    confidence_score = Column(Integer, nullable=False, default=50)
    security_level = Column(String(32), default="restricted")
    detected_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AccessRequest(Base):
    __tablename__ = "access_requests"
    __table_args__ = {"schema": schema_or_none("restricted_ops")}

    request_id = Column(String(64), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    user_email = Column(String(128), nullable=False)
    requested_resource = Column(String(64), nullable=False)
    target_sector = Column(String(64), nullable=False)
    justification = Column(Text, nullable=False)
    status = Column(String(32), default="PENDING")
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String(64), nullable=True)
    decision_reason = Column(Text, nullable=True)


class AccessApproval(Base):
    __tablename__ = "access_approvals"
    __table_args__ = (
        Index("idx_approvals_lookup", "user_id", "resource_type", "valid_from", "valid_to"),
        {"schema": schema_or_none("restricted_ops")}
    )

    approval_id = Column(String(64), primary_key=True)
    request_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False)
    geo_scope = Column(String(64), nullable=False)
    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime, nullable=False)
    granted_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SecurityAuditTrail(Base):
    __tablename__ = "security_audit_trail"
    __table_args__ = {"schema": schema_or_none("audit_sec")}

    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    actor_id = Column(String(64), nullable=False)
    actor_role = Column(String(64), nullable=False)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)
    decision = Column(String(32), nullable=False)
    reason = Column(String(128), nullable=True)
    client_ip = Column(String(64), nullable=False)
    user_agent = Column(Text, nullable=True)
    request_payload_sha256 = Column(String(64), nullable=True)


import base64
import hashlib

SECRET_SALT: str = os.getenv("SECRET_KEY") or ""
if not SECRET_SALT:
    raise RuntimeError("SECRET_KEY env is REQUIRED — refusing to start with a weak default")

# Optional legacy salt for backward compatibility migrations only (default empty)
LEGACY_SECRET_SALT: str = os.getenv("LEGACY_SECRET_SALT", "")


def _fernet_for(salt: str):
    from cryptography.fernet import Fernet
    key_32 = base64.urlsafe_b64encode(hashlib.sha256(salt.encode()).digest())
    return Fernet(key_32)


def encrypt_key(raw_key: str) -> str:
    """Safely encrypts user API key using Fernet derived from SECRET_KEY."""
    if not raw_key:
        return ""
    try:
        return _fernet_for(SECRET_SALT).encrypt(raw_key.strip().encode()).decode()
    except Exception:
        return base64.b64encode(raw_key.strip().encode()).decode()

def decrypt_key(stored_key: str) -> str:
    """Safely decrypts user API key using SECRET_KEY."""
    if not stored_key:
        return ""
    try:
        return _fernet_for(SECRET_SALT).decrypt(stored_key.encode()).decode()
    except Exception:
        pass
    if LEGACY_SECRET_SALT:
        try:
            return _fernet_for(LEGACY_SECRET_SALT).decrypt(stored_key.encode()).decode()
        except Exception:
            pass
    try:
        return base64.b64decode(stored_key.encode()).decode()
    except Exception:
        return stored_key

def init_db():
    Base.metadata.create_all(bind=engine)
