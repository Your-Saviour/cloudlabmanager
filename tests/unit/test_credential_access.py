"""Tests for app/credential_access.py — credential RBAC filtering logic."""
import json
import pytest

from database import (
    CredentialAccessRule, InventoryObject, InventoryTag, InventoryType,
    Role, User,
)
from permissions import seed_permissions, invalidate_cache, get_user_permissions
from credential_access import (
    user_can_view_credential,
    filter_portal_credentials,
    check_personal_key_required,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_credential(session, cred_type, *, tag_names=None):
    """Create a credential InventoryObject with given type and tags."""
    inv_type = session.query(InventoryType).filter_by(slug="credential").first()
    if not inv_type:
        inv_type = InventoryType(slug="credential", label="Credential")
        session.add(inv_type)
        session.flush()

    obj = InventoryObject(
        type_id=inv_type.id,
        data=json.dumps({"name": f"test-{cred_type}", "credential_type": cred_type}),
    )
    session.add(obj)
    session.flush()

    for tn in (tag_names or []):
        tag = session.query(InventoryTag).filter_by(name=tn).first()
        if not tag:
            tag = InventoryTag(name=tn, color="#aaaaaa")
            session.add(tag)
            session.flush()
        obj.tags.append(tag)

    session.flush()
    return obj


def _make_role_with_user(session, role_name):
    """Create a role + user with that role, return (role, user)."""
    from auth import hash_password
    from datetime import datetime, timezone

    role = Role(name=role_name)
    session.add(role)
    session.flush()

    user = User(
        username=f"user-{role_name}",
        password_hash=hash_password("pass1234"),
        is_active=True,
        email=f"{role_name}@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    user.roles.append(role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return role, user


# ---------------------------------------------------------------------------
# Tests: user_can_view_credential
# ---------------------------------------------------------------------------

class TestUserCanViewCredential:
    """Test the user_can_view_credential filtering function."""

    def test_super_admin_always_allowed(self, admin_user, seeded_db):
        cred = _make_credential(seeded_db, "password", tag_names=["instance:web-01"])
        assert user_can_view_credential(seeded_db, admin_user, cred) is True

    def test_no_rules_means_allowed(self, seeded_db):
        """When no CredentialAccessRules exist for a user's roles, allow access."""
        role, user = _make_role_with_user(seeded_db, "viewer")
        cred = _make_credential(seeded_db, "password", tag_names=["instance:web-01"])
        assert user_can_view_credential(seeded_db, user, cred) is True

    def test_user_with_no_roles_denied(self, regular_user, seeded_db):
        """User with zero roles is denied."""
        cred = _make_credential(seeded_db, "password")
        assert user_can_view_credential(seeded_db, regular_user, cred) is False

    def test_rule_scope_all_allows(self, seeded_db):
        """A rule with scope_type='all' and matching cred type grants access."""
        role, user = _make_role_with_user(seeded_db, "ops")
        cred = _make_credential(seeded_db, "ssh_key", tag_names=["instance:db-01"])

        rule = CredentialAccessRule(
            role_id=role.id, credential_type="ssh_key",
            scope_type="all", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()
        invalidate_cache(user.id)

        assert user_can_view_credential(seeded_db, user, cred) is True

    def test_rule_wildcard_cred_type(self, seeded_db):
        """A rule with credential_type='*' matches any credential type."""
        role, user = _make_role_with_user(seeded_db, "star-ops")
        cred = _make_credential(seeded_db, "token", tag_names=["instance:app-01"])

        rule = CredentialAccessRule(
            role_id=role.id, credential_type="*",
            scope_type="all", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert user_can_view_credential(seeded_db, user, cred) is True

    def test_rule_wrong_cred_type_denies(self, seeded_db):
        """A rule for 'ssh_key' does not grant access to 'password' credentials."""
        role, user = _make_role_with_user(seeded_db, "ssh-only")
        cred = _make_credential(seeded_db, "password", tag_names=["instance:web-01"])

        rule = CredentialAccessRule(
            role_id=role.id, credential_type="ssh_key",
            scope_type="all", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert user_can_view_credential(seeded_db, user, cred) is False

    def test_rule_instance_scope_matches(self, seeded_db):
        """Instance scope matches the credential's instance: tag."""
        role, user = _make_role_with_user(seeded_db, "inst-ops")
        cred = _make_credential(seeded_db, "password", tag_names=["instance:web-01", "svc:nginx"])

        rule = CredentialAccessRule(
            role_id=role.id, credential_type="password",
            scope_type="instance", scope_value="web-01", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert user_can_view_credential(seeded_db, user, cred) is True

    def test_rule_instance_scope_wrong_host_denies(self, seeded_db):
        """Instance scope 'db-01' doesn't match a credential tagged 'instance:web-01'."""
        role, user = _make_role_with_user(seeded_db, "wrong-host")
        cred = _make_credential(seeded_db, "password", tag_names=["instance:web-01"])

        rule = CredentialAccessRule(
            role_id=role.id, credential_type="password",
            scope_type="instance", scope_value="db-01", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert user_can_view_credential(seeded_db, user, cred) is False

    def test_rule_service_scope_matches(self, seeded_db):
        """Service scope matches the credential's svc: tag."""
        role, user = _make_role_with_user(seeded_db, "svc-ops")
        cred = _make_credential(seeded_db, "password", tag_names=["svc:splunk", "instance:log-01"])

        rule = CredentialAccessRule(
            role_id=role.id, credential_type="password",
            scope_type="service", scope_value="splunk", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert user_can_view_credential(seeded_db, user, cred) is True

    def test_rule_tag_scope_matches(self, seeded_db):
        """Tag scope matches any tag on the credential."""
        role, user = _make_role_with_user(seeded_db, "tag-ops")
        cred = _make_credential(seeded_db, "password", tag_names=["env:prod", "instance:web-01"])

        rule = CredentialAccessRule(
            role_id=role.id, credential_type="password",
            scope_type="tag", scope_value="env:prod", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert user_can_view_credential(seeded_db, user, cred) is True

    def test_multiple_rules_first_match_wins(self, seeded_db):
        """If one rule matches, access is granted even if others don't."""
        role, user = _make_role_with_user(seeded_db, "multi-rule")
        cred = _make_credential(seeded_db, "password", tag_names=["instance:web-01"])

        # Non-matching rule
        rule1 = CredentialAccessRule(
            role_id=role.id, credential_type="ssh_key",
            scope_type="all", created_by=user.id,
        )
        # Matching rule
        rule2 = CredentialAccessRule(
            role_id=role.id, credential_type="password",
            scope_type="instance", scope_value="web-01", created_by=user.id,
        )
        seeded_db.add_all([rule1, rule2])
        seeded_db.commit()

        assert user_can_view_credential(seeded_db, user, cred) is True


# ---------------------------------------------------------------------------
# Tests: filter_portal_credentials
# ---------------------------------------------------------------------------

class TestFilterPortalCredentials:
    """Test the filter_portal_credentials function."""

    def test_super_admin_sees_all(self, admin_user, seeded_db):
        outputs = [
            {"type": "credential", "credential_type": "password", "value": "secret"},
            {"type": "url", "value": "http://example.com"},
        ]
        result = filter_portal_credentials(seeded_db, admin_user, outputs, "nginx", "web-01")
        assert len(result) == 2

    def test_no_rules_sees_all(self, seeded_db):
        """No rules for the user's role → backwards-compatible, all visible."""
        role, user = _make_role_with_user(seeded_db, "norule-portal")
        outputs = [
            {"type": "credential", "credential_type": "password", "value": "secret"},
            {"type": "url", "value": "http://example.com"},
        ]
        result = filter_portal_credentials(seeded_db, user, outputs, "nginx", "web-01")
        assert len(result) == 2

    def test_matching_rule_includes_credential(self, seeded_db):
        role, user = _make_role_with_user(seeded_db, "portal-match")
        rule = CredentialAccessRule(
            role_id=role.id, credential_type="password",
            scope_type="service", scope_value="nginx", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        outputs = [
            {"type": "credential", "credential_type": "password", "value": "secret"},
            {"type": "url", "value": "http://example.com"},
        ]
        result = filter_portal_credentials(seeded_db, user, outputs, "nginx", "web-01")
        creds = [o for o in result if o.get("type") == "credential"]
        assert len(creds) == 1

    def test_non_matching_rule_excludes_credential(self, seeded_db):
        role, user = _make_role_with_user(seeded_db, "portal-nomatch")
        rule = CredentialAccessRule(
            role_id=role.id, credential_type="ssh_key",
            scope_type="all", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        outputs = [
            {"type": "credential", "credential_type": "password", "value": "secret"},
            {"type": "url", "value": "http://example.com"},
        ]
        result = filter_portal_credentials(seeded_db, user, outputs, "nginx", "web-01")
        creds = [o for o in result if o.get("type") == "credential"]
        assert len(creds) == 0
        # Non-credential outputs always pass through
        urls = [o for o in result if o.get("type") == "url"]
        assert len(urls) == 1

    def test_non_credential_outputs_always_pass(self, seeded_db):
        """Non-credential type outputs are never filtered."""
        role, user = _make_role_with_user(seeded_db, "portal-noncred")
        rule = CredentialAccessRule(
            role_id=role.id, credential_type="password",
            scope_type="all", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        outputs = [
            {"type": "url", "value": "http://a.com"},
            {"type": "text", "value": "hello"},
        ]
        result = filter_portal_credentials(seeded_db, user, outputs, "nginx", "web-01")
        assert len(result) == 2

    def test_instance_scope_matches_hostname(self, seeded_db):
        role, user = _make_role_with_user(seeded_db, "portal-inst")
        rule = CredentialAccessRule(
            role_id=role.id, credential_type="password",
            scope_type="instance", scope_value="web-01", created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        outputs = [{"type": "credential", "credential_type": "password", "value": "s"}]
        result = filter_portal_credentials(seeded_db, user, outputs, "nginx", "web-01")
        assert len(result) == 1

    def test_user_no_roles_gets_no_credentials(self, regular_user, seeded_db):
        outputs = [
            {"type": "credential", "credential_type": "password", "value": "secret"},
            {"type": "url", "value": "http://example.com"},
        ]
        result = filter_portal_credentials(seeded_db, regular_user, outputs, "nginx", "web-01")
        creds = [o for o in result if o.get("type") == "credential"]
        assert len(creds) == 0
        # Non-credential still passes
        urls = [o for o in result if o.get("type") != "credential"]
        assert len(urls) == 1


# ---------------------------------------------------------------------------
# Tests: check_personal_key_required
# ---------------------------------------------------------------------------

class TestCheckPersonalKeyRequired:
    """Test the check_personal_key_required helper."""

    def test_no_rules_returns_false(self, seeded_db):
        role, user = _make_role_with_user(seeded_db, "nokey-role")
        assert check_personal_key_required(seeded_db, user, "ssh_key", "nginx", "web-01") is False

    def test_rule_with_personal_key_true(self, seeded_db):
        role, user = _make_role_with_user(seeded_db, "key-role")
        rule = CredentialAccessRule(
            role_id=role.id, credential_type="ssh_key",
            scope_type="all", require_personal_key=True, created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert check_personal_key_required(seeded_db, user, "ssh_key", "nginx", "web-01") is True

    def test_rule_with_personal_key_false(self, seeded_db):
        role, user = _make_role_with_user(seeded_db, "nokey-role2")
        rule = CredentialAccessRule(
            role_id=role.id, credential_type="ssh_key",
            scope_type="all", require_personal_key=False, created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert check_personal_key_required(seeded_db, user, "ssh_key", "nginx", "web-01") is False

    def test_personal_key_wrong_cred_type_not_required(self, seeded_db):
        """Rule requires personal key for ssh_key but we're checking password."""
        role, user = _make_role_with_user(seeded_db, "key-mismatch")
        rule = CredentialAccessRule(
            role_id=role.id, credential_type="ssh_key",
            scope_type="all", require_personal_key=True, created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert check_personal_key_required(seeded_db, user, "password", "nginx", "web-01") is False

    def test_personal_key_instance_scope(self, seeded_db):
        role, user = _make_role_with_user(seeded_db, "key-inst")
        rule = CredentialAccessRule(
            role_id=role.id, credential_type="ssh_key",
            scope_type="instance", scope_value="web-01",
            require_personal_key=True, created_by=user.id,
        )
        seeded_db.add(rule)
        seeded_db.commit()

        assert check_personal_key_required(seeded_db, user, "ssh_key", "nginx", "web-01") is True
        assert check_personal_key_required(seeded_db, user, "ssh_key", "nginx", "db-01") is False

    def test_user_no_roles_returns_false(self, regular_user, seeded_db):
        assert check_personal_key_required(seeded_db, regular_user, "ssh_key", "nginx", "web-01") is False
