import pytest
import datetime
from database.models import SessionLocal, DetectedEvent, HITLFeedbackAudit, init_db
from api.main import get_hitl_audit, get_ops_health_summary
from scripts.ops_health_guard import audit_system_health
from scripts.rotate_bearer_token import rotate_token

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    init_db()
    db = SessionLocal()
    # Create test event
    ev = DetectedEvent(
        source_channel="test_channel",
        message_id=99991,
        message_text="Test incident for HITL audit",
        detected_at=datetime.datetime.utcnow(),
        event_type="explosion",
        verification_status="UNVERIFIED_SINGLE_SOURCE",
        confidence_score=55
    )
    db.add(ev)
    db.commit()

    # Create test HITL audit
    audit = HITLFeedbackAudit(
        event_id=ev.id,
        analyst_id=123456789,
        analyst_name="TestAnalyst",
        decision="CONFIRM",
        source_channel="test_channel",
        reputation_before=50.0,
        reputation_after=75.0,
        created_at=datetime.datetime.utcnow(),
        notes="Verified via CCTV"
    )
    db.add(audit)
    db.commit()
    db.close()

def test_hitl_audit_function():
    db = SessionLocal()
    try:
        data = get_hitl_audit(limit=10, db=db)
        assert isinstance(data, list)
        assert len(data) >= 1
        record = data[0]
        assert record["decision"] == "CONFIRM"
        assert record["analyst_name"] == "TestAnalyst"
        assert record["reputation_after"] == 75.0
    finally:
        db.close()

def test_ops_health_summary_function():
    db = SessionLocal()
    try:
        data = get_ops_health_summary(db=db)
        assert "status" in data
        assert "components" in data
        assert "database" in data["components"]
        assert data["components"]["database"]["status"] == "HEALTHY"
        assert data["components"]["database"]["hitl_audit_records"] >= 1
    finally:
        db.close()

def test_ops_health_guard_script():
    res = audit_system_health(queue_limit=500, mem_limit_mb=500.0)
    assert "status" in res
    assert "metrics" in res
    assert "database" in res["metrics"]
    assert res["metrics"]["database"]["status"] == "OK"

def test_rotate_bearer_token_dry_run():
    token = rotate_token(env_path="non_existent.env", dry_run=True)
    assert token.startswith("tac_")
    assert len(token) > 20
