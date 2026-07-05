"""Tests for OIDC group→role mapping application and the Authentik API client config."""
import pytest

from database import OidcGroupMapping, Role, User
from oidc_groups import apply_group_mappings


def _mk_role(session, name):
    role = Role(name=name)
    session.add(role)
    session.flush()
    return role


def _mk_user(session, username="ssouser", roles=()):
    user = User(username=username, email=f"{username}@example.com", is_active=True)
    user.roles = list(roles)
    session.add(user)
    session.flush()
    return user


def _mk_mapping(session, group, role):
    m = OidcGroupMapping(group_name=group, role_id=role.id)
    session.add(m)
    session.flush()
    return m


class TestApplyGroupMappings:
    def test_no_mappings_is_noop(self, db_session):
        role = _mk_role(db_session, "member")
        user = _mk_user(db_session, roles=[role])
        assert apply_group_mappings(db_session, user, ["clm-admins"]) is False
        assert [r.name for r in user.roles] == ["member"]

    def test_grants_mapped_role_for_group(self, db_session):
        admin = _mk_role(db_session, "admin")
        _mk_mapping(db_session, "clm-admins", admin)
        user = _mk_user(db_session)
        assert apply_group_mappings(db_session, user, ["clm-admins"]) is True
        assert {r.name for r in user.roles} == {"admin"}

    def test_removes_mapped_role_when_group_lost(self, db_session):
        admin = _mk_role(db_session, "admin")
        _mk_mapping(db_session, "clm-admins", admin)
        user = _mk_user(db_session, roles=[admin])
        assert apply_group_mappings(db_session, user, []) is True
        assert user.roles == []

    def test_unmapped_roles_untouched(self, db_session):
        manual = _mk_role(db_session, "special")
        admin = _mk_role(db_session, "admin")
        _mk_mapping(db_session, "clm-admins", admin)
        user = _mk_user(db_session, roles=[manual])
        apply_group_mappings(db_session, user, ["clm-admins"])
        assert {r.name for r in user.roles} == {"special", "admin"}
        apply_group_mappings(db_session, user, [])
        assert {r.name for r in user.roles} == {"special"}

    def test_multiple_groups_to_one_role(self, db_session):
        vm = _mk_role(db_session, "vm-user")
        _mk_mapping(db_session, "clm-vm-users", vm)
        _mk_mapping(db_session, "clm-vm-admins", vm)
        user = _mk_user(db_session)
        apply_group_mappings(db_session, user, ["clm-vm-admins"])
        assert {r.name for r in user.roles} == {"vm-user"}
        # Still granted while in the other mapped group
        apply_group_mappings(db_session, user, ["clm-vm-users"])
        assert {r.name for r in user.roles} == {"vm-user"}

    def test_none_groups_treated_as_empty(self, db_session):
        admin = _mk_role(db_session, "admin")
        _mk_mapping(db_session, "clm-admins", admin)
        user = _mk_user(db_session, roles=[admin])
        assert apply_group_mappings(db_session, user, None) is True
        assert user.roles == []

    def test_no_change_returns_false(self, db_session):
        admin = _mk_role(db_session, "admin")
        _mk_mapping(db_session, "clm-admins", admin)
        user = _mk_user(db_session, roles=[admin])
        assert apply_group_mappings(db_session, user, ["clm-admins"]) is False


class TestAuthentikApiConfig:
    def test_not_configured_without_env_or_outputs(self, monkeypatch, tmp_path):
        import authentik_api
        monkeypatch.delenv("AUTHENTIK_API_URL", raising=False)
        monkeypatch.delenv("AUTHENTIK_API_TOKEN", raising=False)
        monkeypatch.setattr(authentik_api, "OUTPUTS_PATHS", [str(tmp_path / "missing.yaml")])
        assert authentik_api.is_configured() is False

    def test_env_config_wins(self, monkeypatch):
        import authentik_api
        monkeypatch.setenv("AUTHENTIK_API_URL", "https://auth.example.com/api/v3/")
        monkeypatch.setenv("AUTHENTIK_API_TOKEN", "tok")
        assert authentik_api.is_configured() is True
        assert authentik_api.api_url() == "https://auth.example.com/api/v3"

    def test_outputs_fallback(self, monkeypatch, tmp_path):
        import authentik_api
        monkeypatch.delenv("AUTHENTIK_API_URL", raising=False)
        monkeypatch.delenv("AUTHENTIK_API_TOKEN", raising=False)
        outputs = tmp_path / "service_outputs.yaml"
        outputs.write_text(
            "outputs:\n"
            "  - name: web_url\n    value: https://auth.example.com\n"
            "  - name: bootstrap_token\n    value: secret-token\n"
        )
        monkeypatch.setattr(authentik_api, "OUTPUTS_PATHS", [str(outputs)])
        monkeypatch.setattr(authentik_api, "_outputs_cache", {})
        assert authentik_api.is_configured() is True
        assert authentik_api.api_url() == "https://auth.example.com/api/v3"
        assert authentik_api.api_token() == "secret-token"
        assert authentik_api.public_url() == "https://auth.example.com"

    def test_enroll_url(self, monkeypatch):
        import authentik_api
        monkeypatch.setenv("AUTHENTIK_API_URL", "https://auth.example.com/api/v3")
        monkeypatch.setenv("AUTHENTIK_API_TOKEN", "tok")
        monkeypatch.delenv("AUTHENTIK_ONBOARDING_FLOW", raising=False)
        monkeypatch.setattr(authentik_api, "_outputs_cache", {})
        monkeypatch.setattr(authentik_api, "OUTPUTS_PATHS", [])
        url = authentik_api.enroll_url("abc-123")
        assert url == "https://auth.example.com/if/flow/clm-onboarding/?itoken=abc-123"

    def test_slugify(self):
        import authentik_api
        assert authentik_api._slugify("Jane Doe!") == "jane-doe"
        assert authentik_api._slugify("") == "invite"
