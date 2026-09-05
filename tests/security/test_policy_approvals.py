import json
from unittest.mock import MagicMock
from api.security.authz import (
    verify_restricted_access_policy,
    UserIdentity,
    RoleEnum,
    SecurityClearance
)

def test_admin_and_officer_standing_approval():
    admin = UserIdentity(
        user_id="8965828778",
        username="btntrx",
        role=RoleEnum.SECURITY_OFFICER,
        clearance=SecurityClearance.RESTRICTED
    )
    assert verify_restricted_access_policy(admin) is True

def test_guest_and_public_denied_restricted_access():
    guest = UserIdentity(
        user_id="anon",
        username="guest",
        role=RoleEnum.GUEST,
        clearance=SecurityClearance.PUBLIC
    )
    assert verify_restricted_access_policy(guest) is False

def test_operator_with_active_redis_approval():
    mock_redis = MagicMock()
    mock_redis.keys.return_value = [b"tactical:approval:op_token_1:all"]
    mock_redis.get.return_value = json.dumps({"approved_by": "8965828778", "user_id": "op_token_1"})
    
    operator = UserIdentity(
        user_id="op_token_1",
        username="operator_1",
        role=RoleEnum.OPERATOR,
        clearance=SecurityClearance.RESTRICTED
    )
    assert verify_restricted_access_policy(operator, redis_client=mock_redis) is True

def test_operator_without_approval_is_denied():
    mock_redis = MagicMock()
    mock_redis.keys.return_value = []
    
    operator = UserIdentity(
        user_id="op_token_unapproved",
        username="operator_2",
        role=RoleEnum.OPERATOR,
        clearance=SecurityClearance.RESTRICTED
    )
    assert verify_restricted_access_policy(operator, redis_client=mock_redis) is False
