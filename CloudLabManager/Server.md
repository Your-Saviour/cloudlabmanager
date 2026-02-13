Go to [[Introduction]]

## Responsibilities

- **Startup**: Load configuration, clone CloudLab repo, create filesystem symlinks, initialize SQLite database, load inventory types, seed permissions, run sync adapters
- **Authentication**: JWT-based login with RBAC, user invitations, password resets
- **Authorization**: Role-based permission checks on all protected routes
- **Service Discovery**: Scan CloudLab services directory for deployable services
- **Ansible Execution**: Run playbooks and scripts asynchronously via subprocess
- **Job Tracking**: Track deployment jobs with live output capture and WebSocket streaming
- **Job Scheduling**: Cron-based recurring job execution via background scheduler
- **Instance Management**: Cache and serve Vultr inventory data
- **Inventory System**: Type-driven object management with tags, ACLs, and sync adapters
- **Audit Logging**: Record all user actions with timestamps and IP addresses
- **Health Monitoring**: Background poller checks deployed service health (HTTP, TCP, ICMP, SSH) at configured intervals with email notifications on state changes
- **Email**: Send invitation and password reset emails via Sendamatic
- **Static File Serving**: Serve the frontend SPA

## Key Modules

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI app, route registration, CORS, static mount, lifespan |
| `startup.py` | Startup sequence: clone, symlinks, DB init, type loading, permission seeding, sync |
| `database.py` | SQLAlchemy ORM models (all tables: users, roles, permissions, inventory, jobs, audit) |
| `db_session.py` | Database session dependency (`get_db_session`) with auto-commit/rollback |
| `migration.py` | One-time migration from JSON database to SQLite |
| `auth.py` | JWT creation/validation, password hashing, invite/reset token management |
| `permissions.py` | RBAC engine: `require_permission()`, `has_permission()`, permission caching (60s TTL), seeding |
| `inventory_auth.py` | 4-layer inventory permission checks (wildcard, object ACL, tag, role) |
| `inventory_sync.py` | Sync adapters: Vultr, service discovery, users, deployments |
| `type_loader.py` | YAML inventory type loader with validation and change detection |
| `ansible_runner.py` | Async Ansible execution, job management, config/file management, SSH credential resolution |
| `scheduler.py` | Background cron scheduler — checks for due scheduled jobs every 30s, dispatches to AnsibleRunner |
| `health_checker.py` | Health check config loader (`load_health_configs`) and background `HealthPoller` (15s tick, interval-based scheduling, data retention cleanup) |
| `audit.py` | `log_action()` — writes to `audit_log` table |
| `email_service.py` | Sendamatic API integration for invite and password reset emails |
| `models.py` | Pydantic models for all request/response schemas |
| `config.py` | YAML configuration loader |
| `actions.py` | Startup action engine (ENV, CLONE, RUN, RETURN) |
| `dns.py` | Cloudflare API integration |
| `data.py` | Legacy JSON database utilities (used only during migration) |
| `reset_password.py` | CLI script for password resets |

## Routes

| File | Prefix | Description |
|------|--------|-------------|
| `auth_routes.py` | `/api/auth` | Login, setup, invite accept, password reset |
| `instance_routes.py` | `/api/instances` | Vultr instance listing, refresh, stop |
| `service_routes.py` | `/api/services` | Service CRUD, deploy, stop, configs, files, scripts |
| `job_routes.py` | `/api/jobs` | Job listing, detail, cancel, WebSocket streaming |
| `user_routes.py` | `/api/users` | User management, invites, profile, password change |
| `role_routes.py` | `/api/roles` | Role CRUD, permission listing |
| `inventory_routes.py` | `/api/inventory` | Types, objects, tags, ACLs, actions, WebSocket SSH |
| `health_routes.py` | `/api/health` | Health check status, history, summary, config reload |
| `schedule_routes.py` | `/api/schedules` | Schedule CRUD, cron preview, execution history |
| `audit_routes.py` | `/api/audit` | Audit log listing |

## Running

```bash
docker compose up -d --build
```

The server starts on port 8000. See [[Architecture]] for the full startup sequence.
