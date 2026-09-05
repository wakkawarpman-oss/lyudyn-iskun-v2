from unittest.mock import MagicMock
from api.security.authz import log_security_event

def test_log_security_event_persists_audit_trail():
    mock_db = MagicMock()
    log_security_event(
        actor_id="user_123",
        actor_role="operator",
        action="RESTRICTED_ACCESS_CHECK",
        resource_type="tactical_events",
        decision="ALLOWED",
        reason="APPROVAL_VALID",
        client_ip="192.168.1.50",
        db_session=mock_db
    )
    assert mock_db.add.called
    assert mock_db.commit.called

def test_audit_rules_present_in_migration():
    with open("database/migrations/001_security_segmentation.sql") as f:
        sql = f.read()
    assert "CREATE RULE no_update_audit" in sql
    assert "CREATE RULE no_delete_audit" in sql
