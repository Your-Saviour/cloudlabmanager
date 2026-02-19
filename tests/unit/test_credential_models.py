"""Tests for credential-related Pydantic models."""
import pytest
from pydantic import ValidationError

from models import CredentialAccessRuleCreate, CredentialAccessRuleUpdate


class TestCredentialAccessRuleCreate:
    def test_valid_minimal(self):
        m = CredentialAccessRuleCreate(
            role_id=1, credential_type="ssh_key", scope_type="all",
        )
        assert m.role_id == 1
        assert m.require_personal_key is False
        assert m.scope_value is None

    def test_valid_with_scope_value(self):
        m = CredentialAccessRuleCreate(
            role_id=1, credential_type="password",
            scope_type="instance", scope_value="web-01",
        )
        assert m.scope_value == "web-01"

    def test_valid_with_personal_key(self):
        m = CredentialAccessRuleCreate(
            role_id=1, credential_type="ssh_key",
            scope_type="all", require_personal_key=True,
        )
        assert m.require_personal_key is True

    def test_invalid_scope_type(self):
        with pytest.raises(ValidationError, match="scope_type"):
            CredentialAccessRuleCreate(
                role_id=1, credential_type="password", scope_type="invalid",
            )

    def test_missing_role_id(self):
        with pytest.raises(ValidationError):
            CredentialAccessRuleCreate(
                credential_type="password", scope_type="all",
            )

    def test_missing_credential_type(self):
        with pytest.raises(ValidationError):
            CredentialAccessRuleCreate(
                role_id=1, scope_type="all",
            )


class TestCredentialAccessRuleUpdate:
    def test_all_optional(self):
        m = CredentialAccessRuleUpdate()
        assert m.credential_type is None
        assert m.scope_type is None
        assert m.scope_value is None
        assert m.require_personal_key is None

    def test_partial_update(self):
        m = CredentialAccessRuleUpdate(credential_type="token")
        assert m.credential_type == "token"
        assert m.scope_type is None

    def test_invalid_scope_type(self):
        with pytest.raises(ValidationError, match="scope_type"):
            CredentialAccessRuleUpdate(scope_type="bogus")
