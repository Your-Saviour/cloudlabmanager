Go to [[Introduction]]

## Overview

CloudLabManager has a comprehensive test suite covering unit tests, API integration tests, browser tests, and end-to-end deployment tests.

## Test Structure

```
tests/
├── conftest.py           # Shared fixtures (DB, auth, test app)
├── unit/                 # Fast, isolated tests
│   ├── test_database.py      # ORM model tests
│   ├── test_auth.py          # JWT and password verification
│   ├── test_models.py        # Pydantic validation
│   ├── test_permissions.py   # RBAC permission checks
│   └── test_ansible_runner.py# Ansible execution logic
├── integration/          # API endpoint tests with test client
│   ├── test_auth_routes.py       # Auth endpoints
│   ├── test_user_routes.py       # User management
│   ├── test_role_routes.py       # Role management
│   ├── test_service_routes.py    # Service deployment
│   ├── test_inventory_routes.py  # Inventory CRUD and ACLs
│   └── test_job_routes.py        # Job tracking
├── playwright/           # Browser UI tests
│   ├── test_login.py
│   ├── test_dashboard.py
│   ├── test_services.py
│   ├── test_jobs.py
│   └── test_setup_flow.py
└── e2e/                  # Real infrastructure tests
    └── test_vultr_deploy.py
```

## Running Tests

```bash
# All unit + integration tests
pytest tests/unit tests/integration

# Specific test file
pytest tests/unit/test_permissions.py -v

# Specific test by name
pytest tests/integration/test_auth_routes.py -k "test_login_success" -v

# Playwright browser tests
pytest tests/playwright -v

# E2E tests (real Vultr — costs money, use sparingly)
pytest tests/e2e -m e2e -v

# With coverage
pytest tests/unit tests/integration --cov=app --cov-report=term-missing
```

## Pytest Configuration

From `pyproject.toml`:

- **asyncio_mode**: `auto` — async tests run automatically without `@pytest.mark.asyncio`
- **timeout**: 30 seconds per test
- **markers**:
  - `e2e` — real Vultr deployment tests
  - `playwright` — browser UI tests
  - `slow` — tests taking >30 seconds

## Key Fixtures (`conftest.py`)

### Database

| Fixture | Scope | Description |
|---------|-------|-------------|
| `test_engine` | session | In-memory SQLite with `StaticPool` for shared state |
| `setup_test_db` | function | Patches `SessionLocal` across all modules before each test |
| `db_session` | function | Transactional session — rolls back after each test |
| `seeded_db` | function | DB with all permissions pre-seeded |

### Users & Auth

| Fixture | Description |
|---------|-------------|
| `admin_user` | User with Super Admin role |
| `regular_user` | User with no roles |
| `auth_token` | JWT token for admin user |
| `auth_headers` | `{"Authorization": "Bearer <token>"}` dict |

### App & Client

| Fixture | Description |
|---------|-------------|
| `mock_services_dir` | Temp directory with a fake service (`test-service/`) |
| `test_app` | FastAPI app with test DB and mocked startup |
| `client` | Async `httpx.AsyncClient` bound to test app |

## Mocking Strategy

- **Database**: In-memory SQLite with `StaticPool` — shared across a test session, rolled back per test
- **SessionLocal patching**: `setup_test_db` patches `SessionLocal` in every module that imports it (`database`, `auth`, `permissions`, `db_session`, etc.)
- **Ansible execution**: Mocked in integration tests — no real subprocess calls
- **Services directory**: `mock_services_dir` creates a temporary directory structure mimicking real services
- **Email**: Not mocked in unit tests (functions are async, just verify calls)

## Writing New Tests

### Unit Test Example

```python
def test_permission_check(seeded_db, admin_user):
    """Admin should have all permissions."""
    from permissions import has_permission
    assert has_permission(admin_user, "services.deploy") is True
```

### Integration Test Example

```python
async def test_list_services(client, auth_headers):
    """Authenticated user can list services."""
    resp = await client.get("/api/services", headers=auth_headers)
    assert resp.status_code == 200
    assert "services" in resp.json()
```

### Conventions

- Test files mirror the module they test: `test_auth.py` tests `auth.py`
- Integration tests use the `client` fixture for HTTP requests
- Use `auth_headers` for authenticated requests, omit for unauthenticated
- Use `seeded_db` when tests need permissions to exist
- Mark slow tests with `@pytest.mark.slow`
- Mark real deployment tests with `@pytest.mark.e2e`
