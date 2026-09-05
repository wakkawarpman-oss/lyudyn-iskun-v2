import pytest
import time
from fastapi import HTTPException
from unittest.mock import MagicMock
from api.main import (
    submit_access_request,
    decide_access_request,
    trigger_break_glass_emergency_access,
    create_research_replay,
    get_research_simulations,
    check_rate_limit,
    AccessRequestPayload,
    AccessApprovalPayload,
    BreakGlassPayload,
    ReplayPayload,
    _local_rate_limit_cache
)
from api.security.authz import UserIdentity, RoleEnum, SecurityClearance, anonymize_ip, log_security_event

def test_access_request_submission_and_approval():
    # 1. Submission
    operator_user = UserIdentity(
        user_id="operator_77",
        username="duty_operator",
        role=RoleEnum.OPERATOR,
        clearance=SecurityClearance.RESTRICTED
    )
    mock_db = MagicMock()
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("api.main.get_current_user", lambda *args, **kwargs: operator_user)
        mp.setattr("api.main.dispatch_telegram_approval_request", MagicMock())
        req_res = submit_access_request(
            AccessRequestPayload(
                requested_resource="tactical_events",
                target_sector="kyiv_city",
                justification="Active Shahed threat vector verification",
                user_email="operator_77@tactical.gov.ua"
            ),
            db=mock_db
        )
        assert req_res["status"] == "PENDING"
        assert req_res["validity_ttl_hours"] == 24
        req_id = req_res["request_id"]
        assert mock_db.add.called
        assert mock_db.commit.called

    # 2. Rejection by Non-Officer
    guest_user = UserIdentity(
        user_id="intruder",
        username="guest",
        role=RoleEnum.GUEST,
        clearance=SecurityClearance.PUBLIC
    )
    with pytest.raises(HTTPException) as exc:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("api.main.get_current_user", lambda *args, **kwargs: guest_user)
            decide_access_request(
                AccessApprovalPayload(request_id=req_id, decision="APPROVED", hours=24),
                db=mock_db
            )
    assert exc.value.status_code == 403

    # 3. Approval by Security Officer (Synthetic ID)
    officer_user = UserIdentity(
        user_id="SECURITY_OFFICER_1",
        username="security_officer_1",
        role=RoleEnum.SECURITY_OFFICER,
        clearance=SecurityClearance.RESTRICTED
    )
    mock_request_record = MagicMock(
        request_id=req_id,
        user_id="operator_77",
        requested_resource="tactical_events",
        target_sector="kyiv_city",
        status="PENDING"
    )
    mock_db.query.return_value.filter.return_value.first.return_value = mock_request_record

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("api.main.get_current_user", lambda *args, **kwargs: officer_user)
        appr_res = decide_access_request(
            AccessApprovalPayload(
                request_id=req_id,
                decision="APPROVED",
                hours=24,
                reason="Identity and mission verified"
            ),
            db=mock_db
        )
        assert appr_res["status"] == "APPROVED"
        assert appr_res["validity_hours"] == 24
        assert appr_res["decided_by"] == "SECURITY_OFFICER_1"
        assert mock_request_record.status == "APPROVED"


def test_research_replay_simulation_pipeline():
    researcher = UserIdentity(
        user_id="dr_osint",
        username="lead_analyst",
        role=RoleEnum.ANALYST_RESEARCH,
        clearance=SecurityClearance.RESEARCH
    )
    mock_db = MagicMock()
    mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
        MagicMock(
            run_id="sim_abc123",
            scenario_name="Historical Replay Incident #99",
            synthetic_targets_count=14,
            created_by="dr_osint",
            created_at=None
        )
    ]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("api.main.get_current_user", lambda *args, **kwargs: researcher)
        replay = create_research_replay(
            ReplayPayload(incident_id="incident_99", speed_factor=1.5),
            db=mock_db
        )
        assert replay["contour"] == "research"
        assert replay["status"] == "simulation_initialized"
        assert mock_db.add.called
        assert mock_db.commit.called

        sims = get_research_simulations(db=mock_db)
        assert sims["contour"] == "research"
        assert sims["count"] == 1
        assert sims["simulations"][0]["run_id"] == "sim_abc123"


def test_break_glass_procedure():
    mock_db = MagicMock()
    
    # 1. Invalid token rejected
    bad_payload = BreakGlassPayload(
        break_glass_token="wrong_token",
        justification="Critical defense emergency",
        operator_callsign="GRIFFIN_1"
    )
    with pytest.raises(HTTPException) as exc:
        trigger_break_glass_emergency_access(bad_payload, db=mock_db)
    assert exc.value.status_code == 403

    # 2. Valid Break Glass token grants emergency access
    good_payload = BreakGlassPayload(
        break_glass_token="bg_secret_emergency_override_2026",
        justification="Communication severed with Security Officer, incoming cruise missile swarm",
        operator_callsign="GRIFFIN_1",
        hours=3
    )
    res = trigger_break_glass_emergency_access(good_payload, db=mock_db)
    assert res["status"] == "EMERGENCY_CLEARANCE_GRANTED"
    assert res["validity_hours"] == 3
    assert "break_glass_GRIFFIN_1" in res["operator_id"]
    assert mock_db.add.called
    assert mock_db.commit.called


def test_rate_limiting_enforcement():
    _local_rate_limit_cache.clear()
    test_client_id = "test_ip_99"

    # Fill up quota for anonymous guest (mock threshold using tight loop)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("api.main.RATE_LIMIT_GUEST", 5)
        for _ in range(5):
            check_rate_limit(test_client_id, is_authenticated=False)
        
        # 6th request must trigger HTTP 429
        with pytest.raises(HTTPException) as exc:
            check_rate_limit(test_client_id, is_authenticated=False)
        assert exc.value.status_code == 429


def test_audit_log_ip_anonymization():
    # 1. Localhost remains unchanged
    assert anonymize_ip("127.0.0.1") == "127.0.0.1"
    
    # 2. External IP is hashed and does not leak plain IP
    external_ip = "198.51.100.42"
    hashed = anonymize_ip(external_ip)
    assert hashed.startswith("anon_")
    assert external_ip not in hashed
    assert len(hashed) == 21  # "anon_" + 16 chars hash


def test_anomaly_detection_for_short_justification():
    mock_db = MagicMock()
    operator_user = UserIdentity(
        user_id="operator_sus",
        username="op_test",
        role=RoleEnum.OPERATOR,
        clearance=SecurityClearance.RESTRICTED
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("api.main.get_current_user", lambda *args, **kwargs: operator_user)
        mp.setattr("api.main.dispatch_telegram_approval_request", MagicMock())
        mock_log = MagicMock()
        mp.setattr("api.main.log_security_event", mock_log)
        
        submit_access_request(
            AccessRequestPayload(
                requested_resource="tactical_events",
                target_sector="all",
                justification="pls",  # Suspiciously short (<6 chars)
                user_email="sus@test.com"
            ),
            db=mock_db
        )
        assert mock_log.called
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == "SECURITY_ANOMALY_DETECTED"
        assert call_kwargs["decision"] == "FLAGGED"
