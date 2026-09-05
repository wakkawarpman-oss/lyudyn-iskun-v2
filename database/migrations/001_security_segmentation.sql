-- security_level: restricted (Architecture DDL, synthetic placeholders)
-- Master Plan: 001_security_segmentation.sql

-- 1. Створення ізольованих схем
CREATE SCHEMA IF NOT EXISTS public_osint;
CREATE SCHEMA IF NOT EXISTS research;
CREATE SCHEMA IF NOT EXISTS restricted_ops;
CREATE SCHEMA IF NOT EXISTS audit_sec;

-- 2. Створення ролей найменших привілеїв
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'okint_public_ro') THEN
        CREATE ROLE okint_public_ro WITH LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'okint_research_rw') THEN
        CREATE ROLE okint_research_rw WITH LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'okint_restricted_rw') THEN
        CREATE ROLE okint_restricted_rw WITH LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'okint_auditor_ro') THEN
        CREATE ROLE okint_auditor_ro WITH LOGIN;
    END IF;
END $$;

-- 3. Публічний контур: санітизовані події
CREATE TABLE IF NOT EXISTS public_osint.sanitized_events (
    id BIGSERIAL PRIMARY KEY,
    event_uid UUID NOT NULL UNIQUE,
    event_type VARCHAR(64) NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    oblast VARCHAR(64) NOT NULL,
    district VARCHAR(64),
    rough_lat DOUBLE PRECISION NOT NULL,
    rough_lng DOUBLE PRECISION NOT NULL,
    rough_geom GEOMETRY(POINT, 4326),
    significance_level VARCHAR(32) NOT NULL,
    verification_status VARCHAR(64) NOT NULL,
    sources_count INT DEFAULT 1,
    sanitized_summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Дослідницький контур: симуляції, датасети, replay
CREATE TABLE IF NOT EXISTS research.simulation_runs (
    run_id UUID PRIMARY KEY,
    scenario_name VARCHAR(128) NOT NULL,
    parameters JSONB NOT NULL,
    synthetic_targets_count INT,
    kalman_tuning_metrics JSONB,
    created_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Обмежений операційний контур: бойові треки WGS-84
CREATE TABLE IF NOT EXISTS restricted_ops.tactical_events (
    id BIGSERIAL PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL,
    exact_lat DOUBLE PRECISION NOT NULL,
    exact_lng DOUBLE PRECISION NOT NULL,
    exact_geom GEOMETRY(POINT, 4326) NOT NULL,
    altitude_m DOUBLE PRECISION,
    speed_kmh DOUBLE PRECISION,
    heading_deg DOUBLE PRECISION,
    target_type VARCHAR(64) NOT NULL,
    raw_telemetry JSONB,
    source_channel VARCHAR(128),
    confidence_score INT NOT NULL,
    security_level VARCHAR(32) DEFAULT 'restricted',
    detected_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Затвердження доступу (Approvals)
CREATE TABLE IF NOT EXISTS restricted_ops.access_requests (
    request_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    user_email VARCHAR(128) NOT NULL,
    requested_resource VARCHAR(64) NOT NULL,
    target_sector VARCHAR(64) NOT NULL,
    justification TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'PENDING',
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    decided_by UUID,
    decision_reason TEXT
);

CREATE TABLE IF NOT EXISTS restricted_ops.access_approvals (
    approval_id UUID PRIMARY KEY,
    request_id UUID REFERENCES restricted_ops.access_requests(request_id),
    user_id UUID NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    geo_scope VARCHAR(64) NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    granted_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_approvals_lookup 
    ON restricted_ops.access_approvals (user_id, resource_type, valid_from, valid_to);

-- 7. Незмінний WORM-аудит (Append-Only)
CREATE TABLE IF NOT EXISTS audit_sec.security_audit_trail (
    log_id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_id UUID NOT NULL,
    actor_role VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(128),
    decision VARCHAR(32) NOT NULL,
    reason VARCHAR(128),
    client_ip INET NOT NULL,
    user_agent TEXT,
    request_payload_sha256 VARCHAR(64)
);

CREATE RULE no_update_audit AS ON UPDATE TO audit_sec.security_audit_trail DO INSTEAD NOTHING;
CREATE RULE no_delete_audit AS ON DELETE TO audit_sec.security_audit_trail DO INSTEAD NOTHING;

-- 8. Права доступу
REVOKE ALL ON ALL TABLES IN SCHEMA public_osint FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA research FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA restricted_ops FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA audit_sec FROM PUBLIC;

GRANT USAGE ON SCHEMA public_osint TO okint_public_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public_osint TO okint_public_ro;

GRANT USAGE ON SCHEMA research TO okint_research_rw;
GRANT ALL ON ALL TABLES IN SCHEMA research TO okint_research_rw;

GRANT USAGE ON SCHEMA restricted_ops TO okint_restricted_rw;
GRANT ALL ON ALL TABLES IN SCHEMA restricted_ops TO okint_restricted_rw;

GRANT USAGE ON SCHEMA audit_sec TO okint_auditor_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA audit_sec TO okint_auditor_ro;
GRANT INSERT ON audit_sec.security_audit_trail TO okint_restricted_rw;
