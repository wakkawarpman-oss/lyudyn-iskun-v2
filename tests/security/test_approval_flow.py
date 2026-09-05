import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock
from api.main import (
    submit_access_request,
    decide_access_request,
    create_research_replay,
    get_research_simulations,
    AccessRequestPayload,
    AccessApprovalPayload,
    ReplayPayload
)
from api.security.authz import UserIdentity, RoleEnum, SecurityClearance

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

    # 3. Approval by Security Officer Bet Trx
    officer_user = UserIdentity(
        user_id="8965828778",
        username="btntrx",
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
        assert appr_res["decided_by"] == "8965828778"
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
