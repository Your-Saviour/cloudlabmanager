Go to [[Introduction]]

## High-Level Flow

```
Browser --> FastAPI (static files + API) --> Ansible CLI (subprocess) --> Vultr/Cloudflare
                    |
             SQLite database (/data/cloudlab.db)
```

## Project Structure

```
cloudlabmanager/
├── app/
│   ├── app.py                  # FastAPI entry point, route registration, static mount
│   ├── startup.py              # Startup: clone repos, symlinks, DB init, sync
│   ├── database.py             # SQLAlchemy ORM models (all tables)
│   ├── db_session.py           # Database session dependency for routes
│   ├── migration.py            # JSON→SQLite migration (one-time)
│   ├── auth.py                 # JWT auth, password hashing, invite/reset tokens
│   ├── permissions.py          # RBAC engine, permission seeding, caching
│   ├── inventory_auth.py       # 4-layer inventory permission checks
│   ├── inventory_sync.py       # Sync adapters (Vultr, services, users, deployments)
│   ├── type_loader.py          # YAML inventory type loader + validation
│   ├── ansible_runner.py       # Async Ansible execution + job tracking
│   ├── scheduler.py            # Background cron scheduler for recurring jobs
│   ├── health_checker.py       # Health check config loader and background poller
│   ├── audit.py                # Audit logging to database
│   ├── email_service.py        # Sendamatic email integration
│   ├── models.py               # Pydantic request/response models
│   ├── config.py               # YAML config loader
│   ├── actions.py              # Startup action engine (ENV, CLONE, RUN, RETURN)
│   ├── plan_pricing.py          # Vultr plan cost lookup from cached data
│   ├── dry_run.py               # Pre-deployment validation engine and preview builder
│   ├── dns.py                  # Cloudflare DNS integration
│   ├── data.py                 # Legacy JSON utilities (migration only)
│   ├── reset_password.py       # CLI password reset script
│   ├── routes/
│   │   ├── auth_routes.py      # /api/auth/* endpoints
│   │   ├── instance_routes.py  # /api/instances/* endpoints
│   │   ├── service_routes.py   # /api/services/* endpoints (configs, files, scripts)
│   │   ├── job_routes.py       # /api/jobs/* endpoints
│   │   ├── user_routes.py      # /api/users/* endpoints
│   │   ├── role_routes.py      # /api/roles/* endpoints
│   │   ├── inventory_routes.py # /api/inventory/* endpoints (types, objects, tags, ACLs, SSH)
│   │   ├── health_routes.py    # /api/health/* endpoints
│   │   ├── schedule_routes.py  # /api/schedules/* endpoints
│   │   └── audit_routes.py     # /api/audit/* endpoints
│   └── static/
│       ├── index.html          # SPA shell
│       ├── style.css           # Styles
│       └── app.js              # Frontend logic (hash-routed)
├── tests/
│   ├── conftest.py             # Shared fixtures (in-memory SQLite, auth, test app)
│   ├── unit/                   # Unit tests (models, auth, permissions)
│   ├── integration/            # API integration tests
│   ├── playwright/             # Browser UI tests
│   └── e2e/                    # Real Vultr deployment tests
├── data/
│   ├── cloudlab.db             # SQLite database (gitignored)
│   ├── persistent/             # Data surviving container restarts
│   │   ├── services/           # Per-service outputs
│   │   ├── inventory/          # Inventory files
│   │   └── inputs/             # Input files
│   ├── startup_action.conf.yaml
│   └── key_*                   # SSH keys (gitignored)
├── Dockerfile
├── docker-compose.yaml
├── requirements.txt
└── requirements-test.txt
```

## Startup Sequence

1. FastAPI lifespan calls `startup.main()`
2. Loads startup action config from `/data/startup_action.conf.yaml`
3. Loads core settings from `cloudlabsettings/startup.conf.yaml`
4. Clones CloudLab repo to `/app/cloudlab/` (if configured)
5. Restores persistent data from `/data/persistent/` (outputs, inventory, inputs)
6. Creates symlinks so Ansible paths resolve (note: `/vault` is a Docker volume mount, not a symlink — see [[Ansible Integration]]):
   - `/vault` — volume mount from `../cloudlab/vault` (gitignored, not in clone)
   - `/config.yml` → `/app/cloudlab/config.yml`
   - `/services` → `/app/cloudlab/services`
   - `/init_playbook` → `/app/cloudlab/init_playbook`
   - `/scripts` → `/app/cloudlab/scripts`
   - `/inventory` → `/app/cloudlab/inventory`
   - `/inputs`, `/outputs` → `/app/cloudlab/inputs`, `/app/cloudlab/outputs`
   - `/instance_templates`, `/inventory_types` → corresponding dirs
7. Initializes SQLite database, runs migration from JSON if needed
8. Loads inventory type definitions from YAML files
9. Seeds permissions (static + dynamic from inventory types)
10. Runs inventory sync adapters (Vultr, services, users, deployments)
11. Ensures initial admin user has Super Admin role
12. Writes vault password file if previously configured
13. Loads health check configs from `services/*/health.yaml`
14. Creates `AnsibleRunner` instance in app state
15. Starts background `Scheduler` (checks for due scheduled jobs every 30 seconds)
16. Starts background `HealthPoller` (checks service health at configured intervals)
17. Populates plans cache if empty (immediate `refresh_costs()`) and starts periodic plans/cost cache refresh (every 6 hours)

## Deployment Job Flow

When a service is deployed, `AnsibleRunner` follows the same pattern as the CloudLab shell scripts:

1. `ansible-playbook start-instances.yaml` — creates Vultr VMs
2. Sleep 15s — wait for SSH readiness
3. `ansible-playbook docker-base/main.yaml` — install Docker on VMs
4. `ansible-playbook services/{name}/main.yaml` — deploy the service

Each step's stdout is captured line-by-line and stored in the Job object. The frontend polls `/api/jobs/{id}` every second to display live output. Jobs are also persisted to the `job_records` table in SQLite.

## Data Storage

All persistent state is stored in SQLite (`/data/cloudlab.db`) using SQLAlchemy ORM with WAL mode for concurrent reads.

### Key Tables

| Table | Purpose |
|-------|---------|
| `users` | User accounts (username, email, password hash, roles) |
| `roles` | Permission groups (name, is_system flag) |
| `permissions` | Individual permissions (codename, category, label) |
| `user_roles` | Many-to-many: users ↔ roles |
| `role_permissions` | Many-to-many: roles ↔ permissions |
| `inventory_types` | Type definitions (slug, label, config hash) |
| `inventory_objects` | Typed objects (JSON data, search text, tags) |
| `inventory_tags` | Tags for organization and access control |
| `object_acl` | Per-object access control rules |
| `tag_permissions` | Tag-based permission grants |
| `scheduled_jobs` | Cron-based recurring job definitions |
| `job_records` | Deployment and action job history |
| `audit_log` | User action audit trail |
| `health_check_results` | Health check polling results (status, response time, errors) |
| `config_versions` | Service config file version history (content, hash, author, change notes) |
| `app_metadata` | Key-value store (secret key, vault password, cache) |
| `invite_tokens` | User invitation tokens (72h expiry) |
| `password_reset_tokens` | Password reset tokens (1h expiry) |

### Persistent Storage

The `/data/persistent/` directory preserves data across container rebuilds:

- `persistent/services/{name}/outputs/` — service deployment outputs (temp inventories, generated files)
- `persistent/inventory/` — inventory data files
- `persistent/inputs/` — uploaded input files

On startup, persistent data is symlinked back into the cloned CloudLab repo so playbooks can access it.
