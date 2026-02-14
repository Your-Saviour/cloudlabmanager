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
| Inventory | `inventory.tags.manage` | Create/edit/delete tags |

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

## Implementation

- **Engine**: `app/permissions.py` — `require_permission()`, `has_permission()`, caching
- **Inventory layer**: `app/inventory_auth.py` — `check_inventory_permission()`, `check_type_permission()`
- **Models**: `app/database.py` — `Role`, `Permission`, `ObjectACL`, `TagPermission` tables
- **Seeding**: `permissions.py:seed_permissions()` — called on startup, creates/updates all permissions
