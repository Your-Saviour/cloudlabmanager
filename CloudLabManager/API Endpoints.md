Go to [[Introduction]]

All API endpoints are prefixed with `/api/`. Protected endpoints require a Bearer token in the `Authorization` header (obtained from login).

## Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/auth/status` | No | Check if first-time setup is complete |
| POST | `/api/auth/setup` | No | Create initial admin account + set vault password |
| POST | `/api/auth/login` | No | Login with username/password, returns JWT |
| GET | `/api/auth/me` | Yes | Validate token, return current user info |

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

## Instances

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/instances` | List cached Vultr instances |
| POST | `/api/instances/refresh` | Re-query Vultr API via generate-inventory playbook |

## Services

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/services` | List all deployable services from cloudlab/services/ |
| GET | `/api/services/{name}` | Get service detail (parsed instance.yaml config) |
| POST | `/api/services/{name}/deploy` | Start a deployment job for this service |
| POST | `/api/services/{name}/stop` | Stop instances for this service |
| POST | `/api/services/actions/stop-all` | Stop all running Vultr instances |

### Service Discovery

A directory in `cloudlab/services/` is considered a deployable service if it contains both `instance.yaml` and `main.yaml`.

## Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/jobs` | List all jobs (sorted by most recent) |
| GET | `/api/jobs/{id}` | Get job detail including full output |
| GET | `/api/jobs/{id}/stream` | SSE stream of live ansible output |

### Job Object

```json
{
  "id": "a1b2c3d4",
  "service": "n8n-server",
  "action": "deploy",
  "status": "running",
  "started_at": "2025-01-01T00:00:00+00:00",
  "finished_at": null,
  "output": ["$ ansible-playbook ...", "PLAY [Create instances] ..."]
}
```

Job statuses: `running`, `completed`, `failed`
