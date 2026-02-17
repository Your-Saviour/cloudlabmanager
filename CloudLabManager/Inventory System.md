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
| Credentials | `credential` | `ssh_credential_sync` | SSH keys, root passwords, and other credentials |

## Sync Adapters

Sync adapters populate inventory objects from external sources. They run on startup and can be triggered manually.

### VultrInventorySync (`vultr`)

- Reads instances from the cached inventory (populated by `refresh_instances`)
- Creates/updates `server` objects with hostname, IP, region, plan, status, tags, root password, and VNC console URL
- **Credential preservation**: If `default_password` or `kvm_url` is empty in incoming data (e.g., from `generate-inventory.yaml` which may not return these fields), the sync preserves existing non-empty values from the database rather than overwriting them with blanks
- **Auto-creates credential objects**: When a server has a non-empty `default_password`, a `credential` inventory object is created (or updated) with the root password, tagged `instance:{hostname}`. If the instance's Vultr tags match a service directory, a `svc:{service_name}` tag is also added. These credentials appear in the [[Service Access Portal]] alongside service-level credentials
- **Orphan cleanup**: When a server is removed from Vultr, its associated `instance:{hostname}` **password** credential is deleted. SSH key credentials (managed by `SSHCredentialSync`) are skipped to avoid cross-adapter conflicts

### ServiceDiscoverySync (`services`)

- Scans `/services/` for directories containing `deploy.sh`
- Creates `service` objects with name, description, instance specs

### UserSync (`users`)

- Reads CloudLab Manager users from the database
- Creates `user` objects with username, email, display name, status (active/invited/inactive)

### DeploymentSync (`deployments`)

- Reads completed deployment jobs from `JobRecord` table
- Creates `deployment` objects with service name, server, IP, deployment ID, timestamps

### SSHCredentialSync (`ssh_credential_sync`)

- Scans all service directories for `outputs/temp_inventory.yaml` files, including per-instance subdirectories (personal instances)
- For each host entry with an `ansible_ssh_private_key_file`, reads the corresponding `.pub` file and creates a `credential` object of type `ssh_key`
- Stores the public key content in the `value` field and the private key file path in the `key_path` field (readonly)
- Tags each credential with `svc:{service_name}` (purple) and `instance:{hostname}` (indigo)
- **Root password backfill**: If a host has a `vultr_default_password` that hasn't been captured by `VultrInventorySync`, creates a `password` credential for it
- **Orphan cleanup**: Removes SSH credentials whose source `temp_inventory.yaml` no longer exists. Only cleans up credentials with `key_path` set, so manually-created credentials are never affected
- **Triggered automatically** after deploys, script runs, instance stops, and inventory refreshes

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
| `builtin` | Frontend-handled action (e.g., `console` opens VNC URL in a new tab) |
| `script` | Runs a shell script |
| `playbook` | Runs an Ansible playbook |
| `script_stop` | Stops a running script |
| `dynamic_scripts` | Runs scripts from `scripts.yaml` |

Actions are executed via `POST /api/inventory/{type}/{id}/actions/{action}` and streamed via WebSocket. `builtin` actions are handled entirely by the frontend and do not make API calls.

## Server Credentials and Console Access

Server objects include two fields captured from the Vultr API at instance creation time:

- **Root Password** (`default_password`, type: `secret`) — The initial root password set by Vultr. Displayed as a blurred/masked field with reveal (eye icon) and copy-to-clipboard controls on the server detail page. Shows `-` when no value is set.
- **VNC Console URL** (`kvm_url`) — Vultr's noVNC console URL. Accessible via the **Console** button on the server detail and list pages. Opens in a new browser tab.

Both the Console button and SSH button are only shown when the server is in a `running` state and has the required URL/credentials.

> **Note:** `default_password` is only captured at initial instance creation and does not update if the password is changed inside the VM. The KVM URL may expire or rotate.

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

## Job History

Each inventory object's detail page includes a **Job History** tab showing all jobs that have targeted that object. This provides a quick way to see past actions (deploys, stops, scripts, etc.) without leaving the inventory page.

- Jobs are fetched via `GET /api/jobs?object_id={id}` with 10-second polling
- Table columns: Status (badge), Action (link to job detail), Triggered By, Started (relative time), Duration
- A **last job badge** appears in the object's header showing the most recent job's status and timestamp — clicking it navigates to that job's detail page

See [[API Endpoints#Jobs]] for the `object_id` query parameter details.

## API Reference

See [[API Endpoints#Inventory]] for the full endpoint list.
