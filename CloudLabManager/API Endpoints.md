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
| GET | `/api/audit` | `system.audit_log` | List audit log entries (paginated) |

Returns entries with: user, action, resource, details, IP address, timestamp.

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
- **`system_task`** — requires `system_task` (one of `refresh_instances`, `refresh_costs`)
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
