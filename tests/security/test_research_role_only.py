import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock
from api.main import get_research_simulations, create_research_replay, ReplayPayload
from api.security.authz import UserIdentity, RoleEnum, SecurityClearance

def test_research_rejected_for_guest():
    mock_user = UserIdentity(
        user_id="anon",
        username="guest",
        role=RoleEnum.GUEST,
        clearance=SecurityClearance.PUBLIC
    )
    with pytest.raises(HTTPException) as exc:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("api.main.get_current_user", lambda *args, **kwargs: mock_user)
            get_research_simulations(db=MagicMock())
    assert exc.value.status_code == 403

def test_research_allowed_for_analyst_research_without_approval():
    mock_user = UserIdentity(
        user_id="research_01",
        username="analyst_research",
        role=RoleEnum.ANALYST_RESEARCH,
        clearance=SecurityClearance.RESEARCH
    )
    mock_db = MagicMock()
    mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("api.main.get_current_user", lambda *args, **kwargs: mock_user)
        res = get_research_simulations(db=mock_db)
        assert res["contour"] == "research"
        assert res["count"] == 0

        replay = create_research_replay(ReplayPayload(incident_id="INC-2024"), db=mock_db)
        assert replay["contour"] == "research"
        assert replay["status"] == "simulation_initialized"
