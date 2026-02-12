"""Playwright test fixtures — runs the test FastAPI app via uvicorn in a thread."""
import os
import sys
import pytest
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))


@pytest.fixture(scope="session")
def app_port():
    return 8199


@pytest.fixture(scope="session")
def base_url(app_port):
    return f"http://localhost:{app_port}"


@pytest.fixture(scope="session")
def playwright_test_app():
    """Create a dedicated FastAPI test app for Playwright (session-scoped)."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base
    from permissions import seed_permissions

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

    Base.metadata.create_all(bind=engine)

    import database
    import importlib
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.engine = engine

    # Patch SessionLocal everywhere
    for mod_name in ["database", "auth", "db_session", "routes.auth_routes",
                     "routes.job_routes", "routes.inventory_routes", "routes.user_routes"]:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "SessionLocal"):
                mod.SessionLocal = TestSession
        except ImportError:
            pass

    # Seed permissions
    session = TestSession()
    seed_permissions(session)
    session.commit()
    session.close()

    import tempfile, ansible_runner
    tmp = tempfile.mkdtemp()
    svc_dir = os.path.join(tmp, "services")
    os.makedirs(svc_dir)
    test_svc = os.path.join(svc_dir, "test-service")
    os.makedirs(test_svc)
    with open(os.path.join(test_svc, "deploy.sh"), "w") as f:
        f.write("#!/bin/bash\necho 'deploying'\n")
    os.chmod(os.path.join(test_svc, "deploy.sh"), 0o755)
    with open(os.path.join(test_svc, "instance.yaml"), "w") as f:
        f.write("instances:\n  - label: test\n")
    with open(os.path.join(test_svc, "config.yaml"), "w") as f:
        f.write("setting: value\n")

    ansible_runner.SERVICES_DIR = svc_dir

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from ansible_runner import AnsibleRunner
    from routes.auth_routes import router as auth_router
    from routes.service_routes import router as service_router
    from routes.job_routes import router as job_router
    from routes.user_routes import router as user_router
    from routes.role_routes import router as role_router
    from routes.inventory_routes import router as inventory_router

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

    return app


@pytest.fixture(scope="session", autouse=True)
def start_test_server(app_port, playwright_test_app):
    """Start the test FastAPI app in a background thread for Playwright tests.

    Uses a dedicated session-scoped test app with in-memory SQLite so no
    real startup.py / git clone / vault is needed.
    """
    import uvicorn

    config = uvicorn.Config(
        app=playwright_test_app,
        host="0.0.0.0",
        port=app_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to be ready
    import httpx
    for _ in range(30):
        try:
            resp = httpx.get(f"http://localhost:{app_port}/api/auth/status", timeout=2)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        server.should_exit = True
        raise RuntimeError("Test server failed to start")

    yield server

    server.should_exit = True
    thread.join(timeout=5)
