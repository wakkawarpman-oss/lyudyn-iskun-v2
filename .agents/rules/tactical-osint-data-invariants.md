# Tactical OSINT Ingestion & Model Invariants

## Invariants:
1. **Dual Backward-Compatible Model APIs**:
   - Any enhancement to mathematical models (`KalmanTrackFilter`, `fuse_multi_domain_evidence`, `TerrainMaskingEngine`) must strictly support both modern class/dict interfaces and legacy parameter signatures called by radar sensor pipelines (`worker/osint/neptun_radar.py`).
2. **Deterministic Registry Resolution**:
   - Military units (`database/military_units_registry.json`) and physical launch sites (`database/launch_sites_registry.json`) must be looked up deterministically via pre-compiled regex/alias normalization, never guessed or hallucinated.
3. **Container-First Verification**:
   - Every modification must be tested inside the containerized execution environment before certifying production readiness.
4. **Desktop Mirroring**:
   - All modified code must be mirrored to `/Users/gonzo/Desktop/V2/CHANGED_TACTICAL_LAYERS/` to maintain the user backup invariant.
