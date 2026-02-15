Go to [[Introduction]]

## Overview

The inventory system provides a flexible, type-driven way to track and manage infrastructure objects (servers, services, users, deployments). Types are defined in YAML files and automatically synced from external sources.

## Inventory Types

Types are defined in YAML files under the `inventory_types/` directory. Each file defines:

```yaml
slug: server
label: Servers
icon: server
description: Vultr cloud instances
fields:
  - name: hostname
    label: Hostname
    type: string
    searchable: true
  - name: ip
    label: IP Address
    type: string
    searchable: true
  - name: region
    label: Region
    type: string
  - name: plan
    label: Plan
    type: string
  - name: status
    label: Status
    type: enum
    options: [active, pending, stopped]
actions:
  - name: ssh
    label: SSH Terminal
    type: ssh
    icon: terminal
sync:
  adapter: vultr
```

### Field Types

| Type | Description |
|------|-------------|
| `string` | Single-line text |
| `text` | Multi-line text |
| `enum` | Dropdown with predefined options |
| `integer` | Whole number |
| `boolean` | True/false |
| `datetime` | Date and time |
| `secret` | Masked text (for sensitive values) |
| `json` | JSON data |

Fields marked `searchable: true` are indexed in the `search_text` column for fast full-text search.

### Loading

The `type_loader.py` module:

1. Reads all YAML files from `inventory_types/`
2. Validates required keys (`slug`, `label`, `fields`)
3. Computes a SHA256 hash of each config for change detection
4. Upserts `InventoryType` records in the database
5. Returns type configs for use by routes and sync

## Built-in Types

| Type | Slug | Sync Adapter | Description |
|------|------|-------------|-------------|
| Servers | `server` | `vultr` | Vultr cloud instances from inventory cache |
| Services | `service` | `services` | Deployable services discovered from CloudLab repo |
| Users | `user` | `users` | CloudLab Manager user accounts |
| Deployments | `deployment` | `deployments` | Completed deployment jobs with server/IP info |

## Sync Adapters

Sync adapters populate inventory objects from external sources. They run on startup and can be triggered manually.

### VultrInventorySync (`vultr`)

- Reads instances from the cached inventory (populated by `refresh_instances`)
- Creates/updates `server` objects with hostname, IP, region, plan, status, tags

### ServiceDiscoverySync (`services`)

- Scans `/services/` for directories containing `deploy.sh`
- Creates `service` objects with name, description, instance specs

### UserSync (`users`)

- Reads CloudLab Manager users from the database
- Creates `user` objects with username, email, display name, status (active/invited/inactive)

### DeploymentSync (`deployments`)

- Reads completed deployment jobs from `JobRecord` table
- Creates `deployment` objects with service name, server, IP, deployment ID, timestamps

Each adapter updates the `search_text` denormalized field for fast searching.

## Tags

Tags are labels that can be applied to any inventory object. They serve two purposes:

1. **Organization** — group and filter objects visually
2. **Access control** — grant permissions via `TagPermission` rules

Tags have a `name` and `color`. They are managed via:

- `GET /api/inventory/tags` — list all tags
- `POST /api/inventory/tags` — create tag
- `PUT /api/inventory/tags/{id}` — update tag
- `DELETE /api/inventory/tags/{id}` — delete tag
- `POST /api/inventory/{type}/{id}/tags` — assign tags to an object

## Access Control Lists (ACLs)

Per-object ACLs provide fine-grained access control beyond role-based permissions.

### Per-Object ACLs

Each object can have ACL rules that grant or deny specific permissions to specific roles:

```json
{
  "role_id": 2,
  "permission": "view",
  "effect": "allow"
}
```

Effects: `allow` or `deny`. Deny takes priority over allow.

### Tag-Based Permissions

Tags can carry permissions that apply to all objects with that tag:

```json
{
  "tag_id": 1,
  "role_id": 2,
  "permission": "view"
}
```

### Permission Resolution Order

See [[RBAC#Inventory Permission Layers]] for the full 4-layer resolution.

## Configurable Actions

Each inventory type can define actions that users can execute on objects:

```yaml
actions:
  - name: ssh
    label: SSH Terminal
    type: ssh
    icon: terminal
  - name: deploy
    label: Deploy
    type: script
    script: deploy.sh
```

Action types:

| Type | Description |
|------|-------------|
| `ssh` | Opens a WebSocket SSH terminal to the object |
| `script` | Runs a shell script |
| `playbook` | Runs an Ansible playbook |
| `script_stop` | Stops a running script |
| `dynamic_scripts` | Runs scripts from `scripts.yaml` |

Actions are executed via `POST /api/inventory/{type}/{id}/actions/{action}` and streamed via WebSocket.

## WebSocket SSH Terminal

The `ssh` action type opens a real-time SSH terminal in the browser:

1. Client connects to `ws://host/api/inventory/ws/{object_id}/action`
2. Server resolves SSH credentials from service inventory files
3. Server opens an AsyncSSH connection to the target host
4. Bidirectional WebSocket relay streams stdin/stdout between browser and host

Requires the `asyncssh` package.

## Bulk Operations

Multiple inventory objects can be acted on simultaneously via multi-select in the UI or the bulk API endpoints.

### Available Bulk Actions

| Action | Endpoint | Description |
|--------|----------|-------------|
| Delete | `POST /api/inventory/{type}/bulk/delete` | Delete multiple objects |
| Add Tags | `POST /api/inventory/{type}/bulk/tags/add` | Add tags to multiple objects |
| Remove Tags | `POST /api/inventory/{type}/bulk/tags/remove` | Remove tags from multiple objects |
| Custom Action | `POST /api/inventory/{type}/bulk/action/{name}` | Run a type action (e.g., destroy, stop) on multiple objects |

### Permission Model

Each object in a bulk request is individually checked against the user's permissions (including per-object ACLs and tag-based permissions). Objects the user lacks permission for are **skipped** — not rejected — and reported in the response with a reason. This allows partial execution when a user has mixed permissions across selected objects.

### Parent-Child Jobs

Bulk action execution (destroy, stop, etc.) creates a parent job with child jobs per object. The parent job tracks overall completion and its output summarises per-child results. See [[API Endpoints#Bulk Operations]] for request/response formats.

## API Reference

See [[API Endpoints#Inventory]] for the full endpoint list.
