Go to [[Introduction]]

All API endpoints are prefixed with `/api/`. Protected endpoints require a Bearer token in the `Authorization` header (obtained from login). Permission requirements are shown in the Permission column — see [[RBAC]] for details.

## Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/auth/setup-required` | No | Check if first-time setup is needed |
| POST | `/api/auth/setup` | No | Create initial admin account + set vault password |
| POST | `/api/auth/login` | No | Login with username/password, returns JWT |
| GET | `/api/auth/me` | Yes | Validate token, return current user info + permissions |
| POST | `/api/auth/invite/{token}` | No | Accept invite, set password |
| POST | `/api/auth/forgot-password` | No | Request password reset email |
| POST | `/api/auth/password-reset/{token}` | No | Reset password with token |

### POST `/api/auth/setup`

Only works once (before any users exist). Request body:

```json
{
  "username": "admin",
  "password": "your-password",
  "vault_password": "ansible-vault-password"
}
```

Returns: `{ "access_token": "...", "token_type": "bearer" }`

### POST `/api/auth/login`

```json
{
  "username": "admin",
  "password": "your-password"
}
```

Returns: `{ "access_token": "...", "token_type": "bearer" }`

### POST `/api/auth/invite/{token}`

```json
{
  "password": "new-password"
}
```

### POST `/api/auth/forgot-password`

```json
{
  "email": "user@example.com"
}
```

### POST `/api/auth/password-reset/{token}`

```json
{
  "password": "new-password"
}
```

## Instances

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/instances` | `instances.view` | List cached Vultr instances |
| GET | `/api/instances/refresh` | `instances.refresh` | Re-query Vultr API via generate-inventory |
| POST | `/api/instances/{label}/{region}/stop` | `instances.stop` | Stop a specific instance |

## Services

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/services` | `services.view` | List all deployable services |
| GET | `/api/services/active-deployments` | `services.view` | List services with active deployments |
| GET | `/api/services/{name}` | `services.view` | Get service detail (parsed instance.yaml) |
| POST | `/api/services/{name}/dry-run` | `services.deploy` | Preview deployment plan with cost estimate and validation |
| POST | `/api/services/{name}/deploy` | `services.deploy` | Start a deployment job |
| POST | `/api/services/{name}/run` | `services.deploy` | Run a named script from scripts.yaml |
| POST | `/api/services/{name}/stop` | `services.stop` | Stop instances for this service |
| POST | `/api/services/actions/stop-all` | `system.stop_all` | Stop all running Vultr instances |

### Service Config Management

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/services/{name}/configs` | `services.config.view` | List config files (instance.yaml, config.yaml, etc.) |
| GET | `/api/services/{name}/configs/{filename}` | `services.config.view` | Read a config file |
| PUT | `/api/services/{name}/configs/{filename}` | `services.config.edit` | Write a config file |

### Config Version History

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/services/{name}/configs/{filename}/versions` | `services.config.view` | List all versions (newest first) |
| GET | `/api/services/{name}/configs/{filename}/versions/{id}` | `services.config.view` | Get full content of a specific version |
| GET | `/api/services/{name}/configs/{filename}/versions/{id}/diff` | `services.config.view` | Unified diff vs previous version (`?compare_to=` for custom comparison) |
| POST | `/api/services/{name}/configs/{filename}/versions/{id}/restore` | `services.config.edit` | Restore a version (creates new version, writes to disk) |

Equivalent endpoints exist under `/api/inventory/service/{obj_id}/configs/{filename}/versions/...` for inventory-based access.

The PUT config endpoint (`/api/services/{name}/configs/{filename}`) now accepts an optional `change_note` field in the request body. Each save automatically creates a new version. The system retains the last 50 versions per file — older versions are pruned automatically.

#### POST restore body

```json
{
  "change_note": "Optional reason for restoring"
}
```

### Service File Management

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/services/{name}/files/{subdir}` | `services.files.view` | List files in inputs/ or outputs/ |
| GET | `/api/services/{name}/files/{subdir}/{filename}` | `services.files.view` | Download a file |
| POST | `/api/services/{name}/files/{subdir}` | `services.files.edit` | Upload a file (multipart) |
| PUT | `/api/services/{name}/files/{subdir}/{filename}` | `services.files.edit` | Edit a file (text content) |
| DELETE | `/api/services/{name}/files/{subdir}/{filename}` | `services.files.edit` | Delete a file |

### Multi-Script Support

Services with a `scripts.yaml` file can define multiple runnable scripts. Use `POST /api/services/{name}/run`:

```json
{
  "script": "add-user",
  "inputs": {
    "username": "jake"
  }
}
```

### Deployment Dry-Run

`POST /api/services/{name}/dry-run` runs validation and cost estimation without executing any Ansible playbooks. Returns an execution preview showing what a deployment would do.

Response:

```json
{
  "instances": [
    {
      "label": "Jump Host",
      "hostname": "jumphost1",
      "plan": "vc2-1c-1gb",
      "region": "mel",
      "os": "Ubuntu 24.04 LTS x64",
      "tags": ["jump-hosts"]
    }
  ],
  "dns_records": [
    { "type": "A", "hostname": "jumphost1.ye-et.com" }
  ],
  "ssh_keys": {
    "type": "ed25519",
    "location": "/services/jump-hosts/outputs/sshkey",
    "name": "jump-hosts"
  },
  "cost_estimate": {
    "total_monthly": 5.0,
    "instances": [...],
    "plans_cache_available": true
  },
  "validations": [
    { "check": "vault_available", "status": "pass", "message": "..." },
    { "check": "instance_yaml_valid", "status": "pass", "message": "..." },
    { "check": "valid_region", "status": "pass", "message": "..." },
    { "check": "valid_plan", "status": "pass", "message": "..." },
    { "check": "duplicate_hostname", "status": "pass", "message": "..." },
    { "check": "deploy_script_exists", "status": "pass", "message": "..." },
    { "check": "cross_service_hostname", "status": "pass", "message": "..." },
    { "check": "port_conflicts", "status": "pass", "message": "..." },
    { "check": "os_availability", "status": "pass", "message": "..." }
  ],
  "permissions_check": { "has_permission": true },
  "summary": { "status": "pass" }
}
```

Summary status values: `pass` (all checks passed), `warn` (no failures but some warnings), `fail` (one or more failures). The frontend disables the deploy button when status is `fail`.

Validation checks performed:
- **vault_available** — vault password is configured
- **instance_yaml_valid** — required fields present (keyLocation, name, temp_inventory, instances)
- **instances_have_required_fields** — each instance has label, hostname, plan, region, os
- **valid_region** — regions exist in Vultr (warns if not found)
- **valid_plan** — plan IDs exist in plans cache (warns if not found)
- **duplicate_hostname** — hostnames not already running in instances cache
- **deploy_script_exists** — deploy.sh exists for the service
- **cross_service_hostname** — no other service configs define the same hostname
- **port_conflicts** — best-effort detection of port overlaps on shared hosts
- **os_availability** — requested OS exists in cached OS list

Logged as `service.dry_run` in the audit log.

### Service Discovery

A directory in `cloudlab/services/` is considered a deployable service if it contains `deploy.sh`.

## Jobs

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/jobs` | `jobs.view_own` / `jobs.view_all` | List jobs (filterable by user/service) |
| GET | `/api/jobs/{id}` | `jobs.view_own` / `jobs.view_all` | Get job detail including full output |
| DELETE | `/api/jobs/{id}` | `jobs.cancel` | Cancel a running job |
| WebSocket | `/api/jobs/ws/{id}` | Yes | Real-time job output streaming |

### Job Object

```json
{
  "id": "a1b2c3d4",
  "service": "n8n-server",
  "action": "deploy",
  "status": "running",
  "started_at": "2025-01-01T00:00:00+00:00",
  "finished_at": null,
  "output": ["$ ansible-playbook ...", "PLAY [Create instances] ..."],
  "user_id": 1,
  "username": "jake"
}
```

Job statuses: `running`, `completed`, `failed`

## Users

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/users` | `users.view` | List all users (paginated) |
| POST | `/api/users` | `users.create` | Invite a new user (sends email) |
| GET | `/api/users/{id}` | `users.view` | Get user details |
| PUT | `/api/users/{id}` | `users.edit` | Update user (display_name, email, is_active) |
| DELETE | `/api/users/{id}` | `users.delete` | Deactivate a user |
| POST | `/api/users/{id}/roles` | `users.assign_roles` | Assign roles to a user |
| POST | `/api/users/{id}/resend-invite` | `users.create` | Resend invitation email |
| PUT | `/api/users/profile` | Yes | Update own profile |
| POST | `/api/users/password` | Yes | Change own password |

### POST `/api/users` (Invite)

```json
{
  "username": "newuser",
  "email": "user@example.com",
  "display_name": "New User",
  "role_ids": [2]
}
```

## Roles

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/roles` | `roles.view` | List all roles with permissions |
| POST | `/api/roles` | `roles.create` | Create a custom role |
| GET | `/api/roles/{id}` | `roles.view` | Get role details |
| PUT | `/api/roles/{id}` | `roles.edit` | Update a role (name, permissions) |
| DELETE | `/api/roles/{id}` | `roles.delete` | Delete a role (non-system only) |
| GET | `/api/roles/permissions` | `roles.view` | List all available permissions (grouped by category) |

### POST `/api/roles`

```json
{
  "name": "Deployer",
  "description": "Can deploy and stop services",
  "permission_ids": [1, 4, 5, 6]
}
```

## Audit

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/audit` | `system.audit_log` | List audit log entries (cursor-paginated, filterable) |
| GET | `/api/audit/filters` | `system.audit_log` | Get available filter options (usernames, categories, actions) |
| GET | `/api/audit/export` | `system.audit_log` | Export matching entries as CSV or JSON |

Returns entries with: user, action, resource, details, IP address, timestamp.

### GET `/api/audit`

Query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `cursor` | int | Cursor for pagination (entry ID to start after) |
| `per_page` | int | Results per page (1–200, default 50) |
| `action` | string | Exact action match |
| `action_prefix` | string | Action prefix match (e.g. `service` matches `service.deploy`, `service.stop`) |
| `username` | string | Exact username match |
| `user_id` | int | Exact user ID match |
| `date_from` | string | ISO 8601 start date |
| `date_to` | string | ISO 8601 end date |
| `search` | string | Case-insensitive full-text search across action, resource, and details |

Response:

```json
{
  "entries": [...],
  "total": 142,
  "next_cursor": 95,
  "per_page": 50
}
```

`total` reflects all matching entries (not just the current page). `next_cursor` is `null` when there are no more pages.

### GET `/api/audit/filters`

Returns available values for building filter dropdowns:

```json
{
  "usernames": ["admin", "jake"],
  "action_categories": ["auth", "service", "user", "schedule"],
  "actions": ["auth.login", "service.deploy", "service.stop", "user.create"]
}
```

`action_categories` are derived from the first segment of dotted action names.

### GET `/api/audit/export`

Accepts all the same filter parameters as `GET /api/audit`, plus:

| Parameter | Type | Description |
|-----------|------|-------------|
| `format` | string | `csv` or `json` (default `csv`) |
| `limit` | int | Max entries to export (1–50,000, default 10,000) |

Returns a streaming download with `Content-Disposition` header. The export is logged as an `audit.export` entry in the audit log.

## Schedules

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/schedules` | `schedules.view` | List all scheduled jobs |
| GET | `/api/schedules/preview` | `schedules.view` | Preview next N run times for a cron expression |
| GET | `/api/schedules/{schedule_id}` | `schedules.view` | Get a single scheduled job |
| GET | `/api/schedules/{schedule_id}/history` | `schedules.view` | List past executions for a schedule (paginated) |
| POST | `/api/schedules` | `schedules.create` | Create a new scheduled job |
| PUT | `/api/schedules/{schedule_id}` | `schedules.edit` | Update a scheduled job |
| DELETE | `/api/schedules/{schedule_id}` | `schedules.delete` | Delete a scheduled job |

### POST `/api/schedules`

```json
{
  "name": "Refresh Instances Hourly",
  "description": "Keep instance cache fresh",
  "job_type": "system_task",
  "system_task": "refresh_instances",
  "cron_expression": "0 * * * *",
  "is_enabled": true,
  "skip_if_running": true
}
```

Valid `job_type` values: `service_script`, `system_task`, `inventory_action`.

- **`service_script`** — requires `service_name` and `script_name`
- **`system_task`** — requires `system_task` (one of `refresh_instances`, `refresh_costs`, `drift_check`)
- **`inventory_action`** — requires `inventory_type_slug`, `inventory_object_id`, `inventory_action_name`

### GET `/api/schedules/preview`

Query params: `expression` (cron string), `count` (number of next runs, default 5).

Returns:

```json
{
  "expression": "*/5 * * * *",
  "next_runs": ["2025-01-01T00:05:00+00:00", "2025-01-01T00:10:00+00:00", ...]
}
```

### GET `/api/schedules/{schedule_id}/history`

Query params: `page` (default 1), `per_page` (default 20).

Returns:

```json
{
  "schedule_name": "Refresh Instances Hourly",
  "total": 42,
  "jobs": [
    {
      "id": "abc123",
      "status": "completed",
      "started_at": "2025-01-01T00:00:00+00:00",
      "finished_at": "2025-01-01T00:01:30+00:00",
      "username": "scheduler:Refresh Instances Hourly"
    }
  ]
}
```

## Health Checks

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/health/status` | `health.view` | Latest health status per service/check, grouped by service with overall status |
| GET | `/api/health/history/{service_name}` | `health.view` | Historical results for a service |
| GET | `/api/health/summary` | `health.view` | Compact summary counts (healthy/unhealthy/unknown) |
| POST | `/api/health/reload` | `health.manage` | Reload health configs from disk |

### GET `/api/health/status`

Returns the latest check result per service, grouped by service with an overall status derived from individual checks (any unhealthy → unhealthy, any degraded → degraded). Services with health configs but no results yet show `"unknown"` status.

### GET `/api/health/history/{service_name}`

Query params:
- `check_name` — filter by specific check name
- `hours` — hours of history to return (default: 24)
- `limit` — max results (default: 100)

### GET `/api/health/summary`

Returns compact counts for dashboard cards:

```json
{
  "total": 7,
  "healthy": 5,
  "unhealthy": 1,
  "unknown": 1
}
```

### POST `/api/health/reload`

Reloads `health.yaml` configs from the CloudLab services directory. Use after adding or modifying health check definitions.

## Drift Detection

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/drift/status` | `drift.view` | Latest drift report with full instance, orphaned, and DNS data |
| GET | `/api/drift/summary` | `drift.view` | Compact summary for dashboard cards |
| GET | `/api/drift/history` | `drift.view` | Paginated list of past drift reports |
| GET | `/api/drift/reports/{id}` | `drift.view` | Full detail of a specific report |
| POST | `/api/drift/check` | `drift.manage` | Trigger an immediate drift check |
| GET | `/api/drift/settings` | `drift.manage` | Get notification settings |
| PUT | `/api/drift/settings` | `drift.manage` | Update notification settings |

### GET `/api/drift/status`

Returns the latest drift report including per-instance status (in_sync, drifted, missing), DNS check results, orphaned instances, and orphaned DNS records.

### GET `/api/drift/summary`

Compact summary counts for dashboard cards:

```json
{
  "status": "drifted",
  "total_defined": 3,
  "in_sync": 2,
  "drifted": 1,
  "missing": 0,
  "orphaned": 0,
  "dns_in_sync": 2,
  "dns_drifted": 1,
  "dns_missing": 0,
  "orphaned_dns": 0,
  "checked_at": "2026-02-15T12:00:00+00:00"
}
```

### GET `/api/drift/history`

Query params: `limit` (default 20), `offset` (default 0).

### POST `/api/drift/check`

Triggers an immediate drift check. Returns immediately — the check runs asynchronously. If a check is already in progress, the request is silently skipped.

### PUT `/api/drift/settings`

```json
{
  "enabled": true,
  "recipients": ["admin@example.com"],
  "notify_on": ["drifted", "missing", "orphaned"]
}
```

Notifications are sent only on state transitions (clean → drifted or drifted → clean). Add `"resolved"` to `notify_on` to receive notifications when drift is resolved.

## Costs

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/costs` | `costs.view` | Cost breakdown with per-instance details |
| GET | `/api/costs/by-tag` | `costs.view` | Costs grouped by instance tag |
| GET | `/api/costs/by-region` | `costs.view` | Costs grouped by Vultr region |
| GET | `/api/costs/plans` | `costs.view` | Cached Vultr plans list with pricing |
| POST | `/api/costs/refresh` | `costs.refresh` | Trigger cost data refresh from Vultr |

### GET `/api/costs/plans`

Returns the cached Vultr plans list used for cost estimation (including dry-run previews). The cache is refreshed automatically every 6 hours and on startup if empty.

```json
{
  "plans": [
    { "id": "vc2-1c-1gb", "vcpu_count": 1, "ram": 1024, "disk": 25, "bandwidth": 1, "monthly_cost": 5.0, "hourly_cost": 0.007 }
  ],
  "count": 42,
  "cached_at": "2026-02-15T00:00:00+00:00"
}
```

## Inventory

See [[Inventory System]] for concepts. All inventory endpoints require authentication.

### Types

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/inventory/types` | Yes | List all inventory types with fields/actions |
| GET | `/api/inventory/types/{slug}` | Yes | Get type details including sync config |

### Tags

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/inventory/tags` | Yes | List all tags (with object counts) |
| POST | `/api/inventory/tags` | `inventory.tags.manage` | Create a tag |
| PUT | `/api/inventory/tags/{id}` | `inventory.tags.manage` | Update a tag |
| DELETE | `/api/inventory/tags/{id}` | `inventory.tags.manage` | Delete a tag |

### Objects

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/inventory/{type_slug}` | `inventory.{type}.view` | List objects (paginated, searchable, filterable) |
| POST | `/api/inventory/{type_slug}` | `inventory.{type}.create` | Create an object |
| GET | `/api/inventory/{type_slug}/{id}` | `inventory.{type}.view` | Get object details |
| PUT | `/api/inventory/{type_slug}/{id}` | `inventory.{type}.edit` | Update an object |
| DELETE | `/api/inventory/{type_slug}/{id}` | `inventory.{type}.delete` | Delete an object |
| POST | `/api/inventory/{type_slug}/{id}/tags` | `inventory.{type}.edit` | Update object tags |

### ACLs

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| GET | `/api/inventory/{type_slug}/{id}/acl` | `inventory.{type}.edit` | Get ACL rules for an object |
| POST | `/api/inventory/{type_slug}/{id}/acl` | `inventory.{type}.edit` | Set ACL rules for an object |

### Actions

| Method | Endpoint | Permission | Description |
|--------|----------|------------|-------------|
| POST | `/api/inventory/{type_slug}/{id}/actions/{action}` | `inventory.{type}.{action}` | Execute an action on an object |
| WebSocket | `/api/inventory/ws/{id}/action` | Yes (token param) | Real-time action output / SSH terminal |

The WebSocket endpoint accepts the JWT token as a query parameter for authentication. For SSH actions, it opens a bidirectional terminal session to the target host.
