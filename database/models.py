import os
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Boolean, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from geoalchemy2 import Geometry
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///events.db")

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
    
    # PostGIS geometric point for radius searches
    geom = Column(Geometry('POINT', srid=4326), index=True)
    
    resonance_score = Column(Integer, default=50) # Increased by views/forwards/LLM confidence
    has_media = Column(Boolean, default=False)
    raw_message = Column(String) # JSON snapshot of the Telethon message
    
    # Autonomous Factchecking & Multi-Source Consensus
    verification_status = Column(String, default="UNVERIFIED_SINGLE_SOURCE", index=True) # VERIFIED | OFFICIAL | UNVERIFIED_SINGLE_SOURCE | POSSIBLE_IPSO
    sources_count = Column(Integer, default=1)
    sources_list = Column(String, default="") # Comma-separated channel names
    is_official = Column(Boolean, default=False)
    
    # Trust Tier System
    source_tier = Column(String, default="B", index=True) # 'S', 'A', 'B'
    source_weight = Column(Float, default=0.5)

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
    geom = Column(Geometry('POINT', srid=4326), index=True)
    is_operational = Column(Boolean, default=True)


class UserApiKey(Base):
    __tablename__ = "user_api_keys"

    user_id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String, nullable=True)
    openai_api_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

import base64
import hashlib

SECRET_SALT = os.getenv("SECRET_KEY", "iskun_master_secret_salt_2026")

def encrypt_key(raw_key: str) -> str:
    """Safely encrypts user API key using Fernet derived from SECRET_KEY."""
    if not raw_key:
        return ""
    try:
        from cryptography.fernet import Fernet
        key_32 = base64.urlsafe_b64encode(hashlib.sha256(SECRET_SALT.encode()).digest())
        f = Fernet(key_32)
        return f.encrypt(raw_key.strip().encode()).decode()
    except Exception:
        return base64.b64encode(raw_key.strip().encode()).decode()

def decrypt_key(stored_key: str) -> str:
    """Safely decrypts user API key."""
    if not stored_key:
        return ""
    try:
        from cryptography.fernet import Fernet
        key_32 = base64.urlsafe_b64encode(hashlib.sha256(SECRET_SALT.encode()).digest())
        f = Fernet(key_32)
        return f.decrypt(stored_key.encode()).decode()
    except Exception:
        try:
            return base64.b64decode(stored_key.encode()).decode()
        except Exception:
            return stored_key

def init_db():
    Base.metadata.create_all(bind=engine)
