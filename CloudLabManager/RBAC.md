Go to [[Introduction]]

## Overview

CloudLabManager uses a role-based access control (RBAC) system to manage permissions. Users are assigned roles, and roles contain permissions that control access to features, API endpoints, and inventory objects.

## Roles

A **role** is a named collection of permissions. Roles can be:

- **System roles** — created automatically (e.g., "Super Admin"), cannot be modified or deleted
- **Custom roles** — created by administrators via the UI or API

The **Super Admin** role is seeded on startup with all permissions (static + dynamic). It is always kept up-to-date when new permissions are added.

Users can have multiple roles. Permissions are additive — a user's effective permissions are the union of all permissions from all assigned roles.

## Permissions

Permissions are identified by a **codename** string (e.g., `services.deploy`) and organized by **category**.

### Static Permissions

These are always present:

| Category | Codename | Description |
|----------|----------|-------------|
| Instances | `instances.view` | View Vultr instances |
| Instances | `instances.refresh` | Refresh instance cache |
| Instances | `instances.stop` | Stop instances |
| Services | `services.view` | View services |
| Services | `services.deploy` | Deploy services |
| Services | `services.stop` | Stop services |
| Services | `services.config.view` | View service configs |
| Services | `services.config.edit` | Edit service configs |
| Services | `services.files.view` | View service files |
| Services | `services.files.edit` | Upload/edit/delete files |
| Jobs | `jobs.view_own` | View own jobs |
| Jobs | `jobs.view_all` | View all jobs |
| Jobs | `jobs.cancel` | Cancel running jobs |
| Jobs | `jobs.rerun` | Rerun completed or failed jobs |
| Users | `users.view` | View user list |
| Users | `users.create` | Invite new users |
| Users | `users.edit` | Edit user profiles |
| Users | `users.delete` | Deactivate users |
| Users | `users.assign_roles` | Assign roles to users |
| Users | `users.mfa_reset` | Force-disable MFA for other users |
| Roles | `roles.view` | View roles and permissions |
| Roles | `roles.create` | Create custom roles |
| Roles | `roles.edit` | Edit custom roles |
| Roles | `roles.delete` | Delete custom roles |
| System | `system.stop_all` | Stop all instances |
| System | `system.audit_log` | View audit log |
| Schedules | `schedules.view` | View scheduled job definitions |
| Schedules | `schedules.create` | Create new scheduled jobs |
| Schedules | `schedules.edit` | Edit existing scheduled jobs |
| Schedules | `schedules.delete` | Delete scheduled jobs |
| Snapshots | `snapshots.view` | View snapshot list and details |
| Snapshots | `snapshots.create` | Take new snapshots of instances |
| Snapshots | `snapshots.delete` | Delete snapshots from Vultr |
| Snapshots | `snapshots.restore` | Create new instances from snapshots |
| Portal | `portal.view` | View the service access portal |
| Portal | `portal.bookmarks.edit` | Create, edit, and delete personal portal bookmarks |
| Inventory | `inventory.tags.manage` | Create/edit/delete tags |
| Inventory | `inventory.acl.manage` | Manage service ACLs |
| Personal Jump Hosts | `personal_jumphosts.create` | Create and list own personal jump hosts |
| Personal Jump Hosts | `personal_jumphosts.destroy` | Destroy own personal jump hosts |
| Personal Jump Hosts | `personal_jumphosts.view_all` | View all users' personal jump hosts |
| Personal Jump Hosts | `personal_jumphosts.manage_all` | Manage (destroy, extend) any user's hosts |
| Feedback | `feedback.submit` | Submit feature requests and bug reports |
| Feedback | `feedback.view_all` | View feedback from all users |
| Feedback | `feedback.manage` | Update status, add notes, delete feedback |
| Credential Access | `credential_access.view` | View credential access rules |
| Credential Access | `credential_access.manage` | Create, edit, and delete credential access rules |

### Dynamic Permissions

Generated automatically from inventory type definitions (YAML files). For each inventory type with slug `{slug}`, the following permissions are created:

- `inventory.{slug}.view` — View objects of this type
- `inventory.{slug}.create` — Create objects
- `inventory.{slug}.edit` — Edit objects
- `inventory.{slug}.delete` — Delete objects
- `inventory.{slug}.{action}` — One per action defined in the type config

For example, the "server" type with a "ssh" action generates: `inventory.server.view`, `inventory.server.create`, `inventory.server.edit`, `inventory.server.delete`, `inventory.server.ssh`.

## User Lifecycle

1. **Invite** — An admin creates a user with username and email via `POST /api/users`. An invite email is sent with a 72-hour token.
2. **Accept** — The user clicks the email link and sets their password via `POST /api/auth/invite/{token}`.
3. **Login** — The user logs in with username + password, receives a 24-hour JWT.
4. **Password Reset** — If forgotten, an admin or the user requests a reset via `POST /api/auth/forgot-password`. A 1-hour reset token is emailed.

The first user is created via the Setup page (no invite needed).

## Permission Caching

User permissions are cached in memory with a **60-second TTL** to reduce database queries. The cache is:

- **Per-user** — each user has their own cached permission set
- **Invalidated** when roles are modified (`invalidate_cache()`)
- **Invalidated** when a specific user's roles change (`invalidate_cache(user_id)`)

## Inventory Permission Layers

Inventory objects use a 4-layer permission check (see [[Inventory System]] for details):

1. **Wildcard** — `"*"` permission grants super-admin access
2. **Per-object ACL deny** — Explicit deny rules on the object block access
3. **Per-object ACL allow** — Explicit allow rules on the object grant access
4. **Tag-based permissions** — Tags on the object grant access via `TagPermission` rules
5. **Role-based fallback** — Falls back to `inventory.{type}.{permission}` role check

## Service-Level Access Control

In addition to global RBAC, CloudLabManager supports **per-service ACLs** that restrict which roles can view, deploy, stop, or configure individual services. This is useful for multi-team or training environments where different users should only operate their assigned services.

### How It Works

Service ACLs are an **additional layer** on top of global RBAC:

1. **Wildcard** — users with `*` permission (super-admin) bypass all service ACL checks
2. **ACL exists for service** — if any ACL rows exist for a service, the user must have a matching ACL through one of their roles (exact permission or `full`)
3. **No ACLs defined** — if no ACL rows exist for a service, global RBAC permissions apply (backwards compatible)

This means existing deployments are unaffected — services only become restricted when an admin explicitly adds ACL rules.

### Service Permissions

| Permission | Grants Access To |
|------------|-----------------|
| `view` | View the service in lists, see its details and outputs |
| `deploy` | Deploy the service, run scripts, create dry-runs |
| `stop` | Stop the service |
| `config` | View and edit service config files |
| `full` | All of the above (meta-permission) |

### Enforcement Scope

Service ACLs are enforced consistently across:

- **Service API routes** — all `GET/POST/PUT/DELETE /api/services/{name}/*` endpoints
- **Service list** — `GET /api/services` returns only services the user can view
- **Bulk operations** — `bulk-deploy` and `bulk-stop` skip services the user lacks permission for (reported in `skipped`)
- **Summaries and outputs** — filtered by view permission
- **Webhooks** — creating/updating/listing `service_script` webhooks checks service ACLs
- **Schedules** — creating/updating/listing `service_script` schedules checks service ACLs

### Database

The `service_acl` table stores ACL rules:

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer (PK) | Auto-increment ID |
| `service_name` | String(100) | Service name (indexed) |
| `role_id` | Integer (FK → roles.id) | Target role (CASCADE delete) |
| `permission` | String(20) | One of: `view`, `deploy`, `stop`, `config` |
| `created_at` | DateTime | When the rule was created |
| `created_by` | Integer (FK → users.id) | Who created the rule (nullable) |

Unique constraint on `(service_name, role_id, permission)`.

### UI

- **Service Config Page** — a "Permissions" tab (visible to users with `inventory.acl.manage` permission) shows a grid of roles and their permissions, with add/remove controls
- **Services Page** — bulk "Manage Access" action lets admins select multiple services and grant a role access in one operation
- **Service Cross-Links** — an orange "ACL" chip appears on services with ACL rules, linking to the Permissions tab
- **Users Page** — a "Service Access" option in the user dropdown shows which services a user can access, with what permissions, and the source (ACL role, Global RBAC, or Superadmin)

### Audit

All ACL changes (add, delete, replace) are logged in the audit trail with action prefix `service.acl`.

## Credential Access Control

In addition to inventory-level RBAC, CloudLabManager supports **credential-type-scoped access rules** that restrict which roles can see which credential types on which instances or services. See [[Credential Access Control]] in the CloudLab docs for the full user-facing guide.

### How It Works

Credential access is controlled through `CredentialAccessRule` records. Each rule specifies:

- **Role** — which role the rule applies to
- **Credential Type** — `ssh_key`, `password`, `token`, `certificate`, `api_key`, or `*` (all)
- **Scope** — `all`, `instance` (specific hostname), `service` (specific service), or `tag`
- **Require Personal Key** — when enabled, hides shared SSH credentials and requires users to upload their own key

### Evaluation Logic

1. **Super-admins** (wildcard permission) always see all credentials
2. If **no rules exist** for any of the user's roles, all credentials are visible (backwards compatible)
3. If rules exist, at least one rule must match both the credential type AND the scope

### Auto-Tagging

All credentials are automatically tagged with `credtype:{type}` (amber `#f59e0b`) during inventory sync. This is handled in:

- `VultrInventorySync` — tags root password credentials with `credtype:password`
- `SSHCredentialSync` — tags SSH key credentials with `credtype:ssh_key`
- `sync_credentials_to_inventory()` — tags service output credentials based on `credential_type`

A backfill runs on startup to tag any pre-existing credentials that were created before this feature.

### Personal SSH Keys

Users can upload a personal SSH public key via their profile (`PUT /api/auth/me/personal-ssh-key`). When a credential access rule has `require_personal_key` enabled:

- The shared credential value is hidden in both the inventory page and portal
- The portal shows a status indicator: green checkmark if the user has a personal key, amber warning with a profile link if they don't

### Audit Events

| Event | When |
|-------|------|
| `credential.viewed` | User opens a credential detail page or reveals a masked value |
| `credential.copied` | User copies a credential value to clipboard |
| `credential.access_denied` | A credential is filtered out by access rules |

### Database

The `credential_access_rules` table:

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer (PK) | Auto-increment ID |
| `role_id` | Integer (FK → roles.id) | Target role |
| `credential_type` | String | Credential type (`ssh_key`, `password`, `token`, `certificate`, `api_key`, `*`) |
| `scope_type` | String | Scope type (`all`, `instance`, `service`, `tag`) |
| `scope_value` | String (nullable) | Scope value (hostname, service name, or tag) |
| `require_personal_key` | Boolean | Whether to require personal SSH key |
| `created_by` | Integer (FK → users.id) | Who created the rule |
| `created_at` | DateTime | When the rule was created |

Unique constraint on `(role_id, credential_type, scope_type, scope_value)`.

### UI

- **Credential Access Rules page** (`/credential-access`) — admin rule builder under the Admin section with KeyRound icon
- **Credential detail tab** — "Credential Access" tab on credential inventory objects showing which roles have access
- **Bulk "Manage Access"** — multi-select credentials in inventory → add/remove access rules for selected items
- **Profile page** — "Personal SSH Key" card for uploading/removing a personal SSH public key

## Implementation

- **Engine**: `app/permissions.py` — `require_permission()`, `has_permission()`, caching
- **Service ACL layer**: `app/service_auth.py` — `check_service_permission()`, `require_service_permission()`, `filter_services_for_user()`, `check_service_script_permission()`
- **Inventory layer**: `app/inventory_auth.py` — `check_inventory_permission()`, `check_type_permission()`
- **Credential access layer**: `app/credential_access.py` — `user_can_view_credential()`, `filter_portal_credentials()`, `check_personal_key_required()`
- **Models**: `app/database.py` — `Role`, `Permission`, `ObjectACL`, `TagPermission`, `ServiceACL`, `CredentialAccessRule` tables
- **Seeding**: `permissions.py:seed_permissions()` — called on startup, creates/updates all permissions
