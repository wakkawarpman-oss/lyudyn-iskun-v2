# Graph Report - /Users/gonzo/Desktop/V2/lyudyn-iskun-v2  (2026-09-02)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 256 nodes · 478 edges · 31 communities (30 shown, 1 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 7 edges (avg confidence: 0.63)
- Token cost: 1,090 input · 326 output

## Graph Freshness
- Built from commit: `b5018133`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Bot Command Handlers
- Backup and Alert System
- LLM Resonance Tuning
- Image Geolocation Analysis
- Threat Assessment Generation
- API Data Endpoints
- Telegram Message Sync
- GEOINT Tactical Engine
- RSS Intelligence Aggregator
- Meme Keyboard Callbacks
- Database Migration Environment
- End-to-End Pipeline Tests
- Meme Generation Tests
- Alembic Migration Config
- Test Execution Script

## God Nodes (most connected - your core abstractions)
1. `safe_send()` - 27 edges
2. `DetectedEvent` - 18 edges
3. `process_with_llm()` - 14 edges
4. `cmd_report_12h()` - 10 edges
5. `cmd_resonance()` - 10 edges
6. `cmd_top_events()` - 9 edges
7. `generate_live_threat_assessment()` - 9 edges
8. `DatabaseBackup` - 7 edges
9. `CriticalAlertSystem` - 7 edges
10. `search_and_send_shelters()` - 7 edges

## Surprising Connections (you probably didn't know these)
- `DatabaseBackup` --uses--> `DetectedEvent`  [INFERRED]
  bot/auto_backup.py → database/models.py
- `CriticalAlertSystem` --uses--> `DetectedEvent`  [INFERRED]
  bot/critical_alerts.py → database/models.py
- `format_factcheck_badge()` --references--> `DetectedEvent`  [EXTRACTED]
  bot/handlers.py → database/models.py
- `_save_user_key()` --calls--> `UserApiKey`  [EXTRACTED]
  bot/handlers.py → database/models.py
- `handle_photo()` --calls--> `EXIFExtractor`  [EXTRACTED]
  bot/handlers.py → worker/osint/exif_extractor.py

## Import Cycles
- None detected.

## Communities (31 total, 1 thin omitted)

### Community 0 - "Bot Command Handlers"
Cohesion: 0.10
Nodes (55): clean_event_snippet(), cmd_analytics(), cmd_back_to_menu(), cmd_catch_raw_key(), cmd_csv_export(), cmd_dasha_humor_combined(), cmd_deep_osint(), cmd_del_key() (+47 more)

### Community 1 - "Backup and Alert System"
Cohesion: 0.09
Nodes (23): asyncio, Base, DatabaseBackup, Bot, CriticalAlertSystem, Bot, generate_csv_export(), BytesIO (+15 more)

### Community 2 - "LLM Resonance Tuning"
Cohesion: 0.10
Nodes (26): BaseModel, evaluate_on_golden(), calibrate_resonance_threshold(), get_resonance(), Enum, patch, str, parametrize (+18 more)

### Community 3 - "Image Geolocation Analysis"
Cohesion: 0.13
Nodes (18): shared_task, test_consensus_math(), test_verifier_tier_mapping(), AIGeolocation, EXIFExtractor, Converts EXIF DMS (Degrees, Minutes, Seconds) tuple to decimal degrees., cached_geocode(), cleanup_old_events() (+10 more)

### Community 4 - "Threat Assessment Generation"
Cohesion: 0.19
Nodes (14): calculate_threat_levels(), _find_evidence_event(), format_event_type(), format_verified_source_link(), generate_live_threat_assessment(), generate_reference_card(), Deterministic threat assessment based ONLY on evidence in the database. Every…, Deterministically renders a bilingual verified intelligence report. Every claim… (+6 more)

### Community 5 - "API Data Endpoints"
Cohesion: 0.44
Nodes (8): get_cached(), get_danger_zones(), get_events(), get_map_shelters(), get_stats(), set_cached(), get, Session

### Community 6 - "Telegram Message Sync"
Cohesion: 0.39
Nodes (7): chunk_list(), listen_for_sync_commands(), main(), perform_sync(), Fetches the latest messages from the last 24 hours from all target channels., Listens for on-demand sync events published via Redis., Yield successive chunks from lst to distribute channels.

### Community 7 - "GEOINT Tactical Engine"
Cohesion: 0.29
Nodes (5): GeointEngine, datetime, Calculates exact Solar Azimuth, Solar Elevation (altitude), and Shadow…, Lightweight military-grade GEOINT analysis engine: 1. Solar Azimuth & Chrono-…, Calculates standard military tactical blast radii and safety zones.

### Community 8 - "RSS Intelligence Aggregator"
Cohesion: 0.43
Nodes (3): EnhancedRSSIntel, datetime, Розширений RSS-агрегатор ЗМІ України. Покриває ТОП джерела новин для крос-…

### Community 9 - "Meme Keyboard Callbacks"
Cohesion: 0.47
Nodes (5): callback_meme(), cb_meme_filter(), get_meme_keyboard(), callback_query, CallbackQuery

### Community 10 - "Database Migration Environment"
Cohesion: 0.40
Nodes (4): Run migrations in 'offline' mode., Run migrations in 'online' mode., run_migrations_offline(), run_migrations_online()

### Community 11 - "End-to-End Pipeline Tests"
Cohesion: 0.40
Nodes (4): Бот після перезапуску — не втрачає дані, Імітує повідомлення з каналу і перевіряє звіт, test_cold_start(), test_full_pipeline()

### Community 12 - "Meme Generation Tests"
Cohesion: 0.70
Nodes (4): mock_meme_gen(), test_meme_has_disclaimer(), test_meme_no_repeat(), test_meme_not_operational()

### Community 13 - "Alembic Migration Config"
Cohesion: 0.67
Nodes (3): Run migrations in 'offline' mode., run_migrations_offline(), run_migrations_online()

## Knowledge Gaps
- **2 isolated node(s):** `run_tests.sh script`, `DATABASE_URL`
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DetectedEvent` connect `Backup and Alert System` to `Bot Command Handlers`, `Image Geolocation Analysis`, `Threat Assessment Generation`, `API Data Endpoints`?**
  _High betweenness centrality (0.156) - this node is a cross-community bridge._
- **Why does `process_with_llm()` connect `LLM Resonance Tuning` to `Image Geolocation Analysis`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `EXIFExtractor` connect `Image Geolocation Analysis` to `Bot Command Handlers`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `DetectedEvent` (e.g. with `DatabaseBackup` and `CriticalAlertSystem`) actually correct?**
  _`DetectedEvent` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `run_tests.sh script`, `DATABASE_URL` to the rest of the system?**
  _2 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Bot Command Handlers` be split into smaller, more focused modules?**
  _Cohesion score 0.09837092731829573 - nodes in this community are weakly interconnected._
- **Should `Backup and Alert System` be split into smaller, more focused modules?**
  _Cohesion score 0.08536585365853659 - nodes in this community are weakly interconnected._