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
│   │   ├── cost_routes.py     # /api/costs/*
│   │   ├── schedule_routes.py # /api/schedules/*
│   │   ├── notification_routes.py # /api/notifications/*
│   │   ├── preference_routes.py # /api/users/me/preferences
│   │   ├── portal_routes.py   # /api/portal/*
│   │   ├── webhook_routes.py  # /api/webhooks/* (CRUD + trigger)
│   │   ├── audit_routes.py    # /api/audit/*
│   │   ├── personal_instance_routes.py # /api/personal-instances/*
│   │   └── feedback_routes.py # /api/feedback/*
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
│   ├── personal_instance_cleanup.py # Personal instance TTL cleanup
│   ├── audit.py               # Audit logging
│   ├── email_service.py       # Email integration (SMTP + Sendamatic)
│   ├── notification_service.py# Notification dispatch engine
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
- **Notification permissions**: `notifications.view`, `notifications.rules.view`, `notifications.rules.manage`, `notifications.channels.manage`
- **Portal permissions**: `portal.view`, `portal.bookmarks.edit`
- **Webhook permissions**: `webhooks.view`, `webhooks.create`, `webhooks.edit`, `webhooks.delete`
- **Personal instance permissions**: `personal_instances.create`, `personal_instances.destroy`, `personal_instances.view_all`, `personal_instances.manage_all`
- **Feedback permissions**: `feedback.submit`, `feedback.view_all`, `feedback.manage`

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
| `SMTP_HOST` | No | SMTP server hostname (enables SMTP transport when set) |
| `SMTP_PORT` | No | SMTP server port (default: 587) |
| `SMTP_USERNAME` | No | SMTP authentication username |
| `SMTP_PASSWORD` | No | SMTP authentication password |
| `SMTP_USE_TLS` | No | Enable STARTTLS (default: true) |
| `SMTP_SENDER_EMAIL` | No | SMTP sender email (falls back to `SENDAMATIC_SENDER_EMAIL`) |
| `SMTP_SENDER_NAME` | No | SMTP sender name (default: "CloudLab Manager") |
| `ALLOWED_ORIGINS` | No | CORS origins (default: `*`) |

## Database

SQLite with SQLAlchemy ORM. Key tables: `users`, `roles`, `permissions`, `inventory_types`, `inventory_objects`, `inventory_tags`, `object_acl`, `tag_permissions`, `scheduled_jobs`, `job_records`, `health_check_results`, `audit_log`, `app_metadata`, `invite_tokens`, `password_reset_tokens`, `config_versions`, `cost_snapshots`, `notifications`, `notification_rules`, `notification_channels`, `user_preferences`, `portal_bookmarks`, `webhook_endpoints`, `bug_reports`, `feedback_requests`.

See `app/database.py` for full schema.
