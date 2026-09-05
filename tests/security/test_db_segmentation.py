import os
from database.models import (
    SanitizedEvent,
    SimulationRun,
    TacticalEvent,
    AccessRequest,
    AccessApproval,
    SecurityAuditTrail
)

def test_sql_migration_syntax_and_schemas():
    path = "database/migrations/001_security_segmentation.sql"
    assert os.path.exists(path), "Migration file must exist"
    with open(path) as f:
        content = f.read()
    assert "CREATE SCHEMA IF NOT EXISTS public_osint;" in content
    assert "CREATE SCHEMA IF NOT EXISTS research;" in content
    assert "CREATE SCHEMA IF NOT EXISTS restricted_ops;" in content
    assert "CREATE SCHEMA IF NOT EXISTS audit_sec;" in content
    assert "CREATE ROLE okint_public_ro" in content
    assert "CREATE ROLE okint_restricted_rw" in content
    assert "CREATE RULE no_update_audit" in content
    assert "CREATE RULE no_delete_audit" in content

def test_sqlalchemy_tri_contour_models_instantiation():
    ev = SanitizedEvent(
        event_uid="test_uid_01",
        event_type="explosion",
        detected_at=None,
        oblast="kyiv_city",
        rough_lat=50.45,
        rough_lng=30.52,
        significance_level="HIGH",
        verification_status="VERIFIED"
    )
    assert ev.rough_lat == 50.45

    sim = SimulationRun(
        run_id="sim_01",
        scenario_name="test_scenario",
        parameters="{}",
        created_by="analyst_1"
    )
    assert sim.run_id == "sim_01"

    tac = TacticalEvent(
        incident_id="INC-001",
        exact_lat=50.450123,
        exact_lng=30.523456,
        target_type="shahed_136",
        confidence_score=95
    )
    assert tac.exact_lat == 50.450123
