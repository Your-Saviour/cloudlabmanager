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
