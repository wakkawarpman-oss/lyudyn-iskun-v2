from unittest.mock import MagicMock
from api.security.authz import (
    get_current_user,
    RoleEnum,
    SecurityClearance
)

def test_guest_user_resolution():
    req = MagicMock()
    req.headers = {}
    req.query_params = {}
    user = get_current_user(request=req, token=None)
    assert user.role == RoleEnum.GUEST
    assert user.clearance == SecurityClearance.PUBLIC

def test_admin_user_with_tactical_token(monkeypatch):
    monkeypatch.setenv("TACTICAL_API_TOKEN", "super_tactical_secret_token_123")
    req = MagicMock()
    req.headers = {"X-Tactical-Token": "super_tactical_secret_token_123"}
    req.query_params = {}
    user = get_current_user(request=req, token=None)
    assert user.role == RoleEnum.ADMIN
    assert user.clearance == SecurityClearance.RESTRICTED

def test_research_user_resolution(monkeypatch):
    monkeypatch.setenv("RESEARCH_API_TOKEN", "research_secret_456")
    req = MagicMock()
    req.headers = {"Authorization": "Bearer research_secret_456"}
    req.query_params = {}
    user = get_current_user(request=req, token=None)
    assert user.role == RoleEnum.ANALYST_RESEARCH
    assert user.clearance == SecurityClearance.RESEARCH
