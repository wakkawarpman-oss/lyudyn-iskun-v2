# 🛰️ LYUDYN-ISKUN V2 | ARCHITECTURE, PROJECT STRUCTURE & AGENT ROADMAP

> **Target Audience:** AI Coding Agents, Autonomous Subagents, System Architects & Senior OSINT Engineers.  
> **Last Verified & Calibrated:** September 2026  
> **Status:** Production / Active on Oracle/GCP VPS (`iskun-server`)  
> **Repository:** `https://github.com/wakkawarpman-oss/lyudyn-iskun-v2.git`

---

## 📌 1. EXECUTIVE SUMMARY & MISSION

**Lyudyn-Iskun V2** is a sovereign, real-time tactical OSINT (Open-Source Intelligence) and C4ISR warning platform dedicated to **Kyiv and Kyiv Region (Київ та Київська область)**.

The system continuously monitors 20+ military, official, and situational Telegram monitoring channels, parses unverified incoming messages via Groq LLM & Regex NLP, verifies spatial coordinates with PostGIS, computes C2 consensus scores, calculates blast danger radii, and delivers actionable alerts via Telegram Bot and an interactive OpenStreetMap GEOINT dashboard.

---

## 🗂️ 2. REPOSITORY FILE STRUCTURE

```text
lyudyn-iskun-v2/
├── .env                              # Environment variables & API tokens (DO NOT COMMIT SECRETS)
├── .env.example                      # Template for environment configuration
├── .gitignore                        # Git ignore patterns
├── Dockerfile                        # Multi-stage Python 3.11-slim container definition
├── docker-compose.yml                # Microservices orchestration (7 services)
├── requirements.txt                  # Locked Python dependencies
│
├── api/                              # 🌐 FASTAPI & WEB GEOINT DASHBOARD
│   ├── main.py                       # FastAPI application & REST endpoints (/api/events, /api/stats, /api/shelters, /api/geoint/zones)
│   └── static/
│       └── index.html                # Leaflet.js interactive OpenStreetMap dashboard with shelter layers & blast radii
│
├── api/cot.py                        # Cursor-on-Target (CoT) XML + ATAK DataPackage ZIP export, token-gated
├── services/analytics_service.py     # Report formatting (analytics/top events) over database/repository.py
├── database/repository.py            # EventRepository — query layer used by services/
│
├── bot/                              # 🤖 AIOGRAM 3 TELEGRAM BOT INTERFACE
│   ├── main.py                       # Bot entrypoint, dispatcher & long-polling loop
│   ├── handlers/                     # Modular command & callback handlers, split by domain:
│   │   ├── __init__.py               #   aggregates sub-routers in declaration-order
│   │   ├── admin.py                  #   /clean, /sync, /delkey, key management (admin-gated)
│   │   ├── alerts.py                 #   incoming alert formatting & delivery
│   │   ├── analytics.py              #   /analytics, /top
│   │   ├── common.py                 #   /start, shared keyboard/menu handlers
│   │   ├── osint.py                  #   Photo OSINT (EXIF/GeoSpy/Vision), /key
│   │   ├── radar.py                  #   /report, /resonance
│   │   ├── shelters.py               #   bomb shelter / metro station lookup
│   │   └── utils.py                  #   shared helpers: safe_send, is_admin, admin_only, redis_client
│   ├── keyboards.py                  # Reply & inline keyboard layouts
│   ├── map_generator.py              # Static OSM map PNG renderer using Pillow Lanczos & staticmap
│   ├── memes_db.py                   # Black humor & Dasha meme database (psychological decompression)
│   └── threat_report.py              # Strategic threat assessment generator & TTX reference card
│
├── database/                         # 🗄️ POSTGIS DATABASE & PERSISTENCE
│   └── models.py                     # SQLAlchemy models: DetectedEvent, UserApiKey, BombShelter
│
├── listener/                         # 📡 TELETHON TELEGRAM INGESTION
│   └── telethon_client.py            # Async Telethon listener across 20+ monitored channels (channel
│                                      # whitelist is inline in worker/tasks.py, not a separate file)
│
├── worker/                           # ⚙️ CELERY AI PROCESSING PIPELINE
│   ├── celery_app.py                 # Celery app config, queue routing & Celery Beat schedules
│   ├── tasks.py                      # Main message processing task, deduplication, 24h retention pruning
│   ├── llm_engine.py                 # Groq LLM extraction (openai/gpt-oss-120b) + Fallback regex + Kyiv filter
│   ├── canonical_geo.py              # Toponym → canonical name/coords resolver, is_fallback_geo detection
│   ├── geo_extractors/               # Regex address parser + tactical POI matcher (60+ landmarks)
│   ├── schemas.py                    # Pydantic schemas for event extraction validation
│   ├── watchdog.py                   # Liveness monitor, health checker & tunnel sync
│   └── osint/                        # 🔍 SPECIALIZED OSINT ANALYSIS MODULES
│       ├── ai_geolocation.py         # GeoSpy AI visual landscape recognition
│       ├── exif_extractor.py         # EXIF metadata, GPS coordinates & camera extractor
│       ├── geoint_engine.py          # Solar azimuth, shadow chrono-location & blast danger radii
│       ├── rss_intel.py              # RSS OSINT feed parser (used in worker/tasks.py: fetch_rss_news_task)
│       └── sentiment.py              # Groq-powered psychological tension/panic scorer (openai/gpt-oss-20b) —
│                                      # NOT YET wired into the pipeline, see roadmap below
│
├── alembic/                          # Schema migrations (script_location — see alembic.ini)
│
├── tests/                            # 🧪 AUTOMATED TESTS
│   └── (see tests/ directory directly — grows per feature, no fixed manifest here)
│
└── AGENT_ARCHITECTURE_ROADMAP.md     # 📖 THIS MASTER GUIDE
```

---

## ⚡ 3. CORE SUBSYSTEMS & DATA PIPELINE

```mermaid
graph TD
    A[📡 Telegram Channels 20+] -->|New Message| B(listener/telethon_client.py)
    B -->|Publish JSON Payload| C[(Redis Queue: messages)]
    C -->|Consume Task| D(worker/tasks.py: process_message)
    D -->|1. LLM / Regex Extraction| E(worker/llm_engine.py)
    E -->|2. Kyiv Toponym & Blacklist Filter| F{Is Kyiv / Oblast?}
    F -->|No| G[Discard Non-Kyiv Event]
    F -->|Yes| H[3. Spatial Deduplication & PostGIS Query]
    H -->|4. Cross-Reference Consensus| I(Database: detected_events)
    I -->|5. Real-Time Delivery| J[🤖 Telegram Bot UI: bot_ui]
    I -->|6. REST API & OSM Map| K[🌐 FastAPI: web_api]
```

### 1. Ingestion (`listener`)
* **Telethon async client** connects to Telegram MTProto and monitors 20+ channels.
* Channels are strictly partitioned into:
  - `pure_kyiv_channels`: Always processed (`va_kyiv`, `kyivcityofficial`, `kyivoperat`, `kyivoperativ`, `dsns_kyiv_region`, `kyiv24`, `t_kyiv`, `los_solomas`).
  - `all_ukraine_channels`: Processed **only** if explicit Kyiv toponyms are detected (`povitryanatrivogaaa`, `war_monitor`, `kpszsu`, `eradarrua`, `ssternenko`).

### 2. AI & Extraction Engine (`worker/llm_engine.py`)
* **Primary LLM:** Groq API with `openai/gpt-oss-120b` (Latency: ~0.60s, Temp: 0.1).
* **Fallback Parser:** Zero-external-dependency regex parser (`F1: 93.0%`).
* **Strict Blacklist:** Rejects non-Kyiv cities (Kropyvnytskyi, Odesa, Kharkiv, Dnipro, Lviv, Zaporizhzhia, etc.).

### 3. C2 Synthesis & Verification Engine
* **Confidence Weights:** Tier 1 Official (1.0), Tier 2 Verified OSINT (0.7), Tier 3 Situational (0.5), Tier 4 Unverified (0.3).
* **Clustering:** real-coordinate events cluster via PostGIS `ST_DWithin` (~8-9km, 30-minute window); events without a confirmed geocode fall back to exact `location_text` match (25-minute window). A `pg_advisory_xact_lock` on the location key serializes concurrent workers to prevent duplicate-incident races.
* **Resonance Scoring (0–100):** Direct strike (95–100), Explosion (80–90), Fire (65–75), Air alert (35–50).

### 4. Database & Retention Policy (`worker/tasks.py`)
* **Rolling 24h Window:** Events older than 24 hours are pruned automatically every night at 04:00 Kyiv time via Celery Beat (`cleanup_old_events`).
* **Cache Management:** Redis cache keys (`api:events`, `api:stats`, `api:shelters`, `api:geoint:zones`) are flushed on rotation to guarantee 100% fresh data.

---

## 🚀 4. INSTRUCTIONS FOR FUTURE AGENTS

### 🛑 CRITICAL RULES FOR CODING AGENTS:
1. **NEVER modify code during analysis stage.** Observe and verify facts first.
2. **Strict Evidence Standard:** Any claim of "fixed", "optimized", or "working" MUST be proven by running actual terminal commands or Telethon tests.
3. **Strict Git & Deployment Protocol:**
   ```bash
   # 1. Edit code locally on Mac
   git add -A
   git commit -m "feat/fix: descriptive message"
   git push origin main

   # 2. Pull and rebuild on server
   gcloud compute ssh --quiet iskun-server --zone=us-central1-a --command="cd ~/lyudyn-iskun-v2 && git pull origin main && sudo docker compose build bot_ui && sudo docker compose up -d"
   ```
4. **Never Shadow Handlers:** Aiogram executes handlers in declaration order. Never define duplicate message/command handlers.
5. **Tile Layer Standards:** Always use OpenStreetMap standard tiles (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`) or Esri Imagery. Never use CartoDB without API key to avoid watermarks.

---

## 🗺️ 5. AGENT ROADMAP & NEXT PRIORITIES

```mermaid
gantt
    title Lyudyn-Iskun Tactical Roadmap
    dateFormat  YYYY-MM
    section Core Stability
    OSM & Dynamic Tunnel Sync      :done, 2026-09, 2026-09
    24h DB Retention & Pruning     :done, 2026-09, 2026-09
    Dead Code Purge (20 scripts)   :done, 2026-09, 2026-09
    CoTTAK / TAK Server Integration :done, 2026-09, 2026-09
    section Upcoming Upgrades
    Edge MLX Inference for Mac      :2026-11, 2026-12
    Multi-Region Drone Triangulation:2026-12, 2027-01
```

### ✅ Done: CoTTAK / ATAK Integration
* Cursor-on-Target (CoT) XML + DataPackage ZIP export implemented — `api/cot.py`, token-gated (`TACTICAL_API_TOKEN`, fail-closed).

### 🎯 Priority 1: Close known OSINT gaps (found by code audit, not yet scheduled elsewhere)
* `worker/osint/sentiment.py` exists but is never called from the pipeline — wire it into `worker/tasks.py: pipeline_extract` or remove it.
* No video handling anywhere: `listener/telethon_client.py` only downloads `msg.photo`; a `F.video` bot handler doesn't exist either. Channel videos (strike footage, drone POV) are currently invisible to OSINT.
* No perceptual-hash / "seen this image before" check — recycled or archival photos passed off as fresh incidents aren't caught.
* No cross-reference against live external sources (search/news) for high-resonance claims — the system trusts only its own 20 monitored channels.

### 🎯 Priority 2: Edge MLX Inference on Apple Silicon
* Enable local quantized LLM inference (`MLX` / `llama.cpp` on M-series chips) for sovereign offline deployments.

### 🎯 Priority 3: Kalman Filter Drone Flight Path Prediction
* Use `worker/osint/kalman_tracker.py` (not yet created) to project Shahed-136 flight corridors and calculate estimated time of arrival (ETA) per Kyiv city district.

---

*Last synced against the actual codebase: 2026-09-03 (Claude Code).*
*Original version verified & signed: DeepMind Advanced Agentic Coding Assistant (Antigravity).*
