"""Shared test fixtures for CloudLabManager test suite."""
import os
import sys
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Add app directory to path so imports work like they do in the container
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, User, Role, Permission, AppMetadata
from permissions import seed_permissions, invalidate_cache


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_engine():
    """Create an in-memory SQLite engine with StaticPool.

    StaticPool ensures all sessions share ONE connection and thus see the
    same in-memory database.  We disable the default pool-return-rollback
    behaviour (pool_reset_on_return=None) so that when helper functions like
    get_secret_key() open and close their own sessions, they don't roll back
    the outer session's work.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


# All modules that do `from database import SessionLocal` at the top level.
# We must patch every one so they use the test engine.
_SESSION_LOCAL_MODULES = [
    "database",
    "auth",
    "db_session",
    "routes.auth_routes",
    "routes.job_routes",
    "routes.inventory_routes",
    "routes.user_routes",
    "routes.cost_routes",
    "routes.instance_routes",
    "routes.schedule_routes",
    "scheduler",
    "service_outputs",
    "inventory_sync",
    "migration",
    "health_checker",
]


@pytest.fixture(autouse=True)
def setup_test_db(test_engine, monkeypatch):
    """Swap the real DB engine/session with in-memory SQLite for every test.

    Creates all tables before the test and drops them after.
    """
    import database
    import importlib

    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    monkeypatch.setattr(database, "engine", test_engine)

    for mod_name in _SESSION_LOCAL_MODULES:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "SessionLocal"):
                monkeypatch.setattr(mod, "SessionLocal", TestSession)
        except ImportError:
            pass

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    invalidate_cache()


@pytest.fixture
def db_session(test_engine):
    """Provide a transactional DB session that rolls back after the test."""
    import database
    Session = database.SessionLocal
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def seeded_db(db_session):
    """DB session with all permissions seeded and super-admin role created."""
    seed_permissions(db_session)
    db_session.commit()
    return db_session


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user(seeded_db):
    """Create an active admin user with the super-admin role."""
    from auth import hash_password
    from datetime import datetime, timezone

    session = seeded_db
    super_admin = session.query(Role).filter_by(name="super-admin").first()

    user = User(
        username="admin",
        password_hash=hash_password("admin1234"),
        is_active=True,
        email="admin@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    if super_admin:
        user.roles.append(super_admin)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def regular_user(seeded_db):
    """Create an active user with no roles."""
    from auth import hash_password
    from datetime import datetime, timezone

    session = seeded_db
    user = User(
        username="regular",
        password_hash=hash_password("regular1234"),
        is_active=True,
        email="regular@test.com",
        invite_accepted_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Auth token fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_token(admin_user):
    """Return a valid JWT token for the admin user."""
    from auth import create_access_token
    return create_access_token(admin_user)


@pytest.fixture
def auth_headers(auth_token):
    """Return HTTP headers with Bearer token for the admin user."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def regular_auth_token(regular_user):
    """Return a valid JWT token for the regular (no-roles) user."""
    from auth import create_access_token
    return create_access_token(regular_user)


@pytest.fixture
def regular_auth_headers(regular_auth_token):
    """Return HTTP headers with Bearer token for the regular user."""
    return {"Authorization": f"Bearer {regular_auth_token}"}


# ---------------------------------------------------------------------------
# App / HTTP client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_services_dir(tmp_path):
    """Create a temporary services directory with a fake service."""
    services = tmp_path / "services"
    services.mkdir()

    # Create a test service with deploy.sh
    test_svc = services / "test-service"
    test_svc.mkdir()
    deploy = test_svc / "deploy.sh"
    deploy.write_text("#!/bin/bash\necho 'deploying'\n")
    deploy.chmod(0o755)

    # Create instance.yaml
    (test_svc / "instance.yaml").write_text("instances:\n  - label: test\n")
    (test_svc / "config.yaml").write_text("setting: value\n")

    return services


@pytest.fixture
def test_app(test_engine, mock_services_dir, monkeypatch):
    """Create a FastAPI test app with mocked startup and tmp services dir."""
    import database
    import ansible_runner

    monkeypatch.setattr(ansible_runner, "SERVICES_DIR", str(mock_services_dir))

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from ansible_runner import AnsibleRunner
    from routes.auth_routes import router as auth_router
    from routes.service_routes import router as service_router
    from routes.job_routes import router as job_router
    from routes.user_routes import router as user_router
    from routes.role_routes import router as role_router
    from routes.inventory_routes import router as inventory_router
    from routes.cost_routes import router as cost_router
    from routes.instance_routes import router as instance_router
    from routes.audit_routes import router as audit_router
    from routes.schedule_routes import router as schedule_router
    from routes.health_routes import router as health_router

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.ansible_runner = AnsibleRunner()
    app.state.inventory_types = []

    app.include_router(auth_router)
    app.include_router(service_router)
    app.include_router(job_router)
    app.include_router(user_router)
    app.include_router(role_router)
    app.include_router(inventory_router)
    app.include_router(cost_router)
    app.include_router(instance_router)
    app.include_router(audit_router)
    app.include_router(schedule_router)
    app.include_router(health_router)

    return app


@pytest.fixture
async def client(test_app):
    """Async httpx client bound to the test FastAPI app."""
    from httpx import AsyncClient, ASGITransport

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
