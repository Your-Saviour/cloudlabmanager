"""Integration tests for service ACL enforcement on schedule routes (Phase 4)."""
import pytest
from database import Role, Permission, ServiceACL, User, ScheduledJob
from permissions import invalidate_cache


@pytest.fixture
def schedule_role(seeded_db):
    """Create a role with schedule + service permissions but no wildcard."""
    session = seeded_db
    role = Role(name="schedule-user")
    session.add(role)
    session.flush()

    for codename in ("schedules.view", "schedules.create", "schedules.edit",
                     "schedules.delete", "services.view", "services.deploy"):
        perm = session.query(Permission).filter_by(codename=codename).first()
        if perm:
            role.permissions.append(perm)
    session.commit()
    session.refresh(role)
    return role


@pytest.fixture
def schedule_user(seeded_db, schedule_role):
    """Create a user with schedule + service permissions."""
    from auth import hash_password
    from datetime import datetime, timezone

    session = seeded_db
    user = User(
        username="scheduleuser",
        password_hash=hash_password("schedule1234"),
        is_active=True,
        email="scheduleuser@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    user.roles.append(schedule_role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def schedule_auth_headers(schedule_user):
    from auth import create_access_token
    token = create_access_token(schedule_user)
    return {"Authorization": f"Bearer {token}"}


def _make_service_schedule(**overrides):
    """Build a valid service_script schedule payload."""
    payload = {
        "name": "Test Schedule",
        "job_type": "service_script",
        "service_name": "test-service",
        "script_name": "deploy.sh",
        "cron_expression": "0 0 * * *",
    }
    payload.update(overrides)
    return payload


class TestCreateScheduleACL:
    """Test that creating service_script schedules enforces service ACLs."""

    async def test_create_allowed_by_global_rbac(self, client, schedule_auth_headers):
        """No ACLs → global RBAC allows creation (user has services.deploy)."""
        resp = await client.post("/api/schedules", headers=schedule_auth_headers,
                                 json=_make_service_schedule())
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Schedule"

    async def test_create_denied_by_acl(self, client, schedule_auth_headers, schedule_user,
                                         db_session):
        """ACL exists for service but user's role not granted → 403."""
        other_role = Role(name="sched-other-role")
        db_session.add(other_role)
        db_session.flush()

        acl = ServiceACL(service_name="test-service", role_id=other_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(schedule_user.id)

        resp = await client.post("/api/schedules", headers=schedule_auth_headers,
                                 json=_make_service_schedule(name="Blocked Schedule"))
        assert resp.status_code == 403

    async def test_create_allowed_by_acl(self, client, schedule_auth_headers, schedule_user,
                                          schedule_role, db_session):
        """ACL grants deploy to user's role → creation allowed."""
        acl = ServiceACL(service_name="test-service", role_id=schedule_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(schedule_user.id)

        resp = await client.post("/api/schedules", headers=schedule_auth_headers,
                                 json=_make_service_schedule(name="Allowed Schedule"))
        assert resp.status_code == 200

    async def test_create_stop_script_requires_stop_acl(self, client, schedule_auth_headers,
                                                          schedule_user, schedule_role, db_session):
        """Stop script schedule requires 'stop' ACL."""
        acl = ServiceACL(service_name="test-service", role_id=schedule_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(schedule_user.id)

        resp = await client.post("/api/schedules", headers=schedule_auth_headers,
                                 json=_make_service_schedule(script_name="stop"))
        assert resp.status_code == 403

    async def test_create_system_task_unaffected(self, client, schedule_auth_headers):
        """Non-service schedules are not affected by service ACLs."""
        resp = await client.post("/api/schedules", headers=schedule_auth_headers, json={
            "name": "System Schedule",
            "job_type": "system_task",
            "system_task": "refresh_instances",
            "cron_expression": "0 0 * * *",
        })
        assert resp.status_code == 200


class TestUpdateScheduleACL:
    """Test that updating schedules targeting services enforces ACLs."""

    async def test_update_denied_by_acl(self, client, schedule_auth_headers, schedule_user,
                                         auth_headers, db_session):
        """User cannot update a schedule for a service they don't have access to."""
        # Admin creates the schedule
        create_resp = await client.post("/api/schedules", headers=auth_headers,
                                         json=_make_service_schedule(name="Admin Schedule"))
        schedule_id = create_resp.json()["id"]

        # Add restrictive ACL
        other_role = Role(name="sched-update-role")
        db_session.add(other_role)
        db_session.flush()
        acl = ServiceACL(service_name="test-service", role_id=other_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(schedule_user.id)

        resp = await client.put(f"/api/schedules/{schedule_id}",
                                headers=schedule_auth_headers,
                                json={"name": "Renamed"})
        assert resp.status_code == 403

    async def test_update_allowed_by_acl(self, client, schedule_auth_headers, schedule_user,
                                          schedule_role, auth_headers, db_session):
        """User can update a schedule when they have ACL access to the service."""
        create_resp = await client.post("/api/schedules", headers=auth_headers,
                                         json=_make_service_schedule(name="Editable Schedule"))
        schedule_id = create_resp.json()["id"]

        acl = ServiceACL(service_name="test-service", role_id=schedule_role.id, permission="deploy")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(schedule_user.id)

        resp = await client.put(f"/api/schedules/{schedule_id}",
                                headers=schedule_auth_headers,
                                json={"name": "Renamed Schedule"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed Schedule"


class TestListScheduleACLFiltering:
    """Test that schedule list filters service_script schedules by ACL."""

    async def test_list_filters_restricted_service_schedules(self, client, schedule_auth_headers,
                                                               schedule_user, auth_headers,
                                                               db_session):
        """Schedules for restricted services are hidden from the list."""
        await client.post("/api/schedules", headers=auth_headers,
                          json=_make_service_schedule(name="Service Schedule"))
        await client.post("/api/schedules", headers=auth_headers, json={
            "name": "System Schedule",
            "job_type": "system_task",
            "system_task": "refresh_instances",
            "cron_expression": "0 0 * * *",
        })

        other_role = Role(name="sched-list-role")
        db_session.add(other_role)
        db_session.flush()
        acl = ServiceACL(service_name="test-service", role_id=other_role.id, permission="view")
        db_session.add(acl)
        db_session.commit()
        invalidate_cache(schedule_user.id)

        resp = await client.get("/api/schedules", headers=schedule_auth_headers)
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["schedules"]]
        assert "System Schedule" in names
        assert "Service Schedule" not in names

    async def test_list_shows_all_without_acl(self, client, schedule_auth_headers, auth_headers):
        """Without ACLs, user sees all schedules (global RBAC applies)."""
        await client.post("/api/schedules", headers=auth_headers,
                          json=_make_service_schedule(name="Visible Schedule"))

        resp = await client.get("/api/schedules", headers=schedule_auth_headers)
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["schedules"]]
        assert "Visible Schedule" in names
