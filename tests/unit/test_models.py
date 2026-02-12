"""Tests for app/models.py — Pydantic model validation."""
import pytest
from pydantic import ValidationError

from models import (
    SetupRequest, LoginRequest, InviteUserRequest, AcceptInviteRequest,
    ChangePasswordRequest, RoleCreateRequest, RoleUpdateRequest,
    TagCreate, ACLRuleCreate, UpdateProfileRequest, UserUpdateRequest,
)


class TestSetupRequest:
    def test_valid_setup(self):
        req = SetupRequest(username="admin", password="password123", vault_password="vp")
        assert req.username == "admin"

    def test_username_too_short(self):
        with pytest.raises(ValidationError, match="3-30 alphanumeric"):
            SetupRequest(username="ab", password="password123", vault_password="vp")

    def test_username_invalid_chars(self):
        with pytest.raises(ValidationError, match="3-30 alphanumeric"):
            SetupRequest(username="admin@!", password="password123", vault_password="vp")

    def test_username_too_long(self):
        with pytest.raises(ValidationError, match="3-30 alphanumeric"):
            SetupRequest(username="a" * 31, password="password123", vault_password="vp")

    def test_password_too_short(self):
        with pytest.raises(ValidationError, match="at least 8"):
            SetupRequest(username="admin", password="short", vault_password="vp")


class TestInviteUserRequest:
    def test_valid_invite(self):
        req = InviteUserRequest(username="newuser", email="new@example.com")
        assert req.email == "new@example.com"

    def test_email_lowercased(self):
        req = InviteUserRequest(username="newuser", email="User@EXAMPLE.COM")
        assert req.email == "user@example.com"

    def test_invalid_email(self):
        with pytest.raises(ValidationError, match="Invalid email"):
            InviteUserRequest(username="newuser", email="notanemail")

    def test_invalid_username(self):
        with pytest.raises(ValidationError, match="3-30 alphanumeric"):
            InviteUserRequest(username="a b", email="x@y.com")


class TestAcceptInviteRequest:
    def test_valid(self):
        req = AcceptInviteRequest(token="abc123", password="password123")
        assert req.token == "abc123"

    def test_password_too_short(self):
        with pytest.raises(ValidationError, match="at least 8"):
            AcceptInviteRequest(token="abc123", password="short")


class TestChangePasswordRequest:
    def test_valid(self):
        req = ChangePasswordRequest(current_password="old12345", new_password="new12345")
        assert req.new_password == "new12345"

    def test_new_password_too_short(self):
        with pytest.raises(ValidationError, match="at least 8"):
            ChangePasswordRequest(current_password="old12345", new_password="short")


class TestRoleCreateRequest:
    def test_valid(self):
        req = RoleCreateRequest(name="viewer")
        assert req.name == "viewer"

    def test_name_too_short(self):
        with pytest.raises(ValidationError, match="2-50"):
            RoleCreateRequest(name="a")

    def test_name_too_long(self):
        with pytest.raises(ValidationError, match="2-50"):
            RoleCreateRequest(name="x" * 51)


class TestRoleUpdateRequest:
    def test_valid_with_none(self):
        req = RoleUpdateRequest()
        assert req.name is None

    def test_name_too_short(self):
        with pytest.raises(ValidationError, match="2-50"):
            RoleUpdateRequest(name="a")


class TestTagCreate:
    def test_valid(self):
        tag = TagCreate(name="production")
        assert tag.name == "production"

    def test_strips_whitespace(self):
        tag = TagCreate(name="  production  ")
        assert tag.name == "production"

    def test_empty_name(self):
        with pytest.raises(ValidationError, match="1-100"):
            TagCreate(name="   ")

    def test_name_too_long(self):
        with pytest.raises(ValidationError, match="1-100"):
            TagCreate(name="x" * 101)


class TestACLRuleCreate:
    def test_valid_allow(self):
        rule = ACLRuleCreate(role_id=1, permission="view", effect="allow")
        assert rule.effect == "allow"

    def test_valid_deny(self):
        rule = ACLRuleCreate(role_id=1, permission="view", effect="deny")
        assert rule.effect == "deny"

    def test_invalid_effect(self):
        with pytest.raises(ValidationError, match="allow.*deny"):
            ACLRuleCreate(role_id=1, permission="view", effect="maybe")

    def test_default_effect_is_allow(self):
        rule = ACLRuleCreate(role_id=1, permission="view")
        assert rule.effect == "allow"


class TestUpdateProfileRequest:
    def test_valid_email(self):
        req = UpdateProfileRequest(email="user@example.com")
        assert req.email == "user@example.com"

    def test_email_lowercased(self):
        req = UpdateProfileRequest(email="USER@EXAMPLE.COM")
        assert req.email == "user@example.com"

    def test_none_email_accepted(self):
        req = UpdateProfileRequest(email=None)
        assert req.email is None

    def test_invalid_email(self):
        with pytest.raises(ValidationError, match="Invalid email"):
            UpdateProfileRequest(email="bademail")


class TestUserUpdateRequest:
    def test_valid(self):
        req = UserUpdateRequest(display_name="Test User", is_active=True)
        assert req.display_name == "Test User"

    def test_invalid_email(self):
        with pytest.raises(ValidationError, match="Invalid email"):
            UserUpdateRequest(email="nope")
