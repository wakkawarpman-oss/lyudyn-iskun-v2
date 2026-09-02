import os
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Boolean
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

def init_db():
    Base.metadata.create_all(bind=engine)
