# CLAUDE.md

## Project Overview

CloudLabManager is a FastAPI web application that provides a browser-based management interface for [CloudLab](../cloudlab) infrastructure. It deploys services, manages Vultr instances, runs Ansible playbooks, and provides RBAC-controlled access to infrastructure inventory.

## Quick Start

```bash
# Build and start
docker compose up -d --build

# Open http://localhost:8000
```

On first boot, create an admin account and enter the Ansible vault password.

## Architecture

- **Backend**: FastAPI (Python) with SQLAlchemy ORM and SQLite database
- **Frontend**: Vanilla HTML/CSS/JS SPA (hash-routed, no build step)
- **Auth**: JWT tokens (24h expiry) with RBAC permission system
- **Ansible**: Runs playbooks via `asyncio.create_subprocess_exec`
- **Database**: SQLite at `/data/cloudlab.db` (WAL mode)

## Project Structure

```
cloudlabmanager/
├── app/
│   ├── routes/                # API route handlers
│   │   ├── auth_routes.py     # /api/auth/*
│   │   ├── inventory_routes.py# /api/inventory/*
│   │   ├── instance_routes.py # /api/instances/*
│   │   ├── service_routes.py  # /api/services/*
│   │   ├── job_routes.py      # /api/jobs/*
│   │   ├── user_routes.py     # /api/users/*
│   │   ├── role_routes.py     # /api/roles/*
│   │   ├── health_routes.py   # /api/health/*
│   │   ├── schedule_routes.py # /api/schedules/*
│   │   └── audit_routes.py    # /api/audit/*
│   ├── static/                # Frontend SPA
│   ├── app.py                 # FastAPI entry point
│   ├── startup.py             # Startup: clone, symlinks, DB init, sync
│   ├── database.py            # SQLAlchemy ORM models
│   ├── auth.py                # JWT, password hashing, invite/reset tokens
│   ├── permissions.py         # RBAC engine, permission seeding
│   ├── inventory_auth.py      # 4-layer inventory permission checks
│   ├── inventory_sync.py      # Sync adapters (Vultr, services, users, deployments)
│   ├── type_loader.py         # YAML inventory type loader
│   ├── ansible_runner.py      # Async Ansible execution + job tracking
│   ├── scheduler.py           # Background cron scheduler for recurring jobs
│   ├── health_checker.py      # Health check config loader + background poller
│   ├── audit.py               # Audit logging
│   ├── email_service.py       # Sendamatic email integration
│   ├── models.py              # Pydantic request/response models
│   ├── db_session.py          # DB session dependency
│   ├── migration.py           # JSON→SQLite migration
│   ├── config.py              # YAML config loader
│   ├── actions.py             # Startup action engine
│   └── dns.py                 # Cloudflare DNS integration
├── tests/
│   ├── unit/                  # Unit tests
│   ├── integration/           # API integration tests
│   ├── playwright/            # Browser UI tests
│   ├── e2e/                   # Real Vultr deployment tests
│   └── conftest.py            # Shared fixtures
├── data/
│   ├── persistent/            # Survives container restarts
│   └── startup_action.conf.yaml
├── CloudLabManager/           # Obsidian documentation vault
├── docker-compose.yaml
├── Dockerfile
├── requirements.txt
└── requirements-test.txt
```

## Key Commands

```bash
# Run tests (unit + integration)
docker compose exec cloudlabmanager pytest tests/unit tests/integration

# Run specific test file
docker compose exec cloudlabmanager pytest tests/unit/test_permissions.py -v

# Run playwright tests (requires browser deps)
docker compose exec cloudlabmanager pytest tests/playwright -v

# Run e2e tests (real Vultr — costs money)
docker compose exec cloudlabmanager pytest tests/e2e -m e2e -v

# Reset password from CLI
docker compose exec cloudlabmanager python3 /app/reset_password.py --username jake
```

## Key Patterns

- **Permission checks**: Routes use `Depends(require_permission("category.action"))` from `permissions.py`
- **Audit logging**: Call `log_action(session, user_id, username, action, resource)` in route handlers
- **DB sessions**: Use `session: Session = Depends(get_db_session)` — auto-commits on success, rolls back on error
- **Inventory types**: Defined in YAML files, loaded by `type_loader.py`, synced by `inventory_sync.py`
- **Dynamic permissions**: Generated from inventory type configs as `inventory.{slug}.{action}`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token |
| `HOST_HOSTNAME` | Yes | Hostname identifier |
| `VAULT_PASSWORD` | No | Ansible vault password (alt to UI entry) |
| `LOCAL_MODE` | No | Skip Cloudflare DNS validation |
| `SENDAMATIC_API_KEY` | No | Email API key |
| `SENDAMATIC_SENDER_EMAIL` | No | Sender email address |
| `SENDAMATIC_SENDER_NAME` | No | Sender display name |
| `ALLOWED_ORIGINS` | No | CORS origins (default: `*`) |

## Database

SQLite with SQLAlchemy ORM. Key tables: `users`, `roles`, `permissions`, `inventory_types`, `inventory_objects`, `inventory_tags`, `object_acl`, `tag_permissions`, `scheduled_jobs`, `job_records`, `health_check_results`, `audit_log`, `app_metadata`, `invite_tokens`, `password_reset_tokens`, `config_versions`.

See `app/database.py` for full schema.
